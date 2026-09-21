"""Offline behavioral tests; runnable with unittest or pytest."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moral_agent import Action, ActionKind, DecisionKind, MoralAgent, Situation, Stakeholder
from moral_agent.cli import load_scenarios
from moral_agent.commitment import MoralCommitment
from moral_agent.foresight import DeterministicForesight
from moral_agent.models import ExecutionReceipt, TimeHorizon, to_dict
from moral_agent.moral_evaluation import MoralEvaluator, MoralPolicy


class NoAlternatives:
    def alternatives(self, situation, action):
        return ()


class RecordingExecutor:
    def __init__(self):
        self.actions = []

    def execute(self, action):
        self.actions.append(action)
        return ExecutionReceipt(action.id, "recorded", "Test only")


class FixedForecast:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    def predict(self, situation, action):
        return self.outcomes


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.safe = Action("safe", "自分で解く", ActionKind.SOLVE, .8)
        self.bad = Action("bad", "不正アクセス", ActionKind.HACK, 1.)
        self.situation = Situation("試験で最高点を取る", (self.safe,))
        self.outcomes = DeterministicForesight().predict(self.situation, self.safe)

    def decision_with(self, outcomes):
        return MoralAgent(foresight=FixedForecast(outcomes), counterfactual=NoAlternatives()).decide(self.situation)

    def test_safe_action_allowed_and_executed(self):
        executor = RecordingExecutor()
        result = MoralAgent(executor=executor).run(self.situation)
        self.assertEqual(result.decision.kind, DecisionKind.ALLOW)
        self.assertEqual(executor.actions, [self.safe])

    def test_clear_violation_blocked_despite_maximum_utility(self):
        executor = RecordingExecutor()
        result = MoralAgent(counterfactual=NoAlternatives(), executor=executor).run(replace(self.situation, candidates=(self.bad,)))
        self.assertEqual(result.decision.kind, DecisionKind.BLOCK)
        self.assertIsNone(result.execution)
        self.assertEqual(executor.actions, [])
        self.assertIn("重大な権利侵害", result.decision.assessments[0].evaluation.hard_violations)

    def test_modify_executes_only_reassessed_alternative(self):
        executor = RecordingExecutor()
        result = MoralAgent(executor=executor).run(replace(self.situation, candidates=(self.bad,)))
        self.assertEqual(result.decision.kind, DecisionKind.MODIFY)
        self.assertEqual(result.decision.proposed_action, self.bad)
        self.assertEqual(len(executor.actions), 1)
        self.assertEqual(executor.actions[0].kind, ActionKind.SOLVE)
        self.assertEqual(result.decision.assessments[0].verdict, DecisionKind.BLOCK)
        self.assertEqual(result.decision.assessments[1].alternative_to, self.bad.id)

    def test_unknown_is_ask_human_and_not_executed(self):
        action = replace(self.safe, kind=ActionKind.UNKNOWN)
        executor = RecordingExecutor()
        result = MoralAgent(executor=executor).run(replace(self.situation, candidates=(action,)))
        self.assertEqual(result.decision.kind, DecisionKind.ASK_HUMAN)
        self.assertEqual(executor.actions, [])

    def test_uncertain_severe_harm_asks_human(self):
        action = replace(self.safe, kind=ActionKind.DELETE)
        agent = MoralAgent(counterfactual=NoAlternatives())
        decision = agent.decide(replace(self.situation, candidates=(action,)))
        self.assertEqual(decision.kind, DecisionKind.ASK_HUMAN)
        self.assertIn("重大で不可逆な被害", decision.assessments[0].evaluation.hard_violations)

    def test_multiple_futures_and_individual_impacts_retained(self):
        assessment = MoralAgent().assess(self.situation, self.bad)
        self.assertEqual(len(assessment.outcomes), 2)
        self.assertEqual({o.time_horizon for o in assessment.outcomes}, {TimeHorizon.IMMEDIATE, TimeHorizon.LONG_TERM})
        self.assertEqual(set(assessment.stakeholder_impacts), {"user", "third_party", "organization", "society"})
        self.assertTrue(all(len(v) == 2 for v in assessment.stakeholder_impacts.values()))
        self.assertNotEqual(assessment.stakeholder_impacts["user"][0].harm, assessment.stakeholder_impacts["third_party"][0].harm)

    def test_dynamic_stakeholder_with_unknown_role_escalates(self):
        situation = replace(self.situation, stakeholders=self.situation.stakeholders + (Stakeholder("child", "Child", "child"),))
        decision = MoralAgent().decide(situation)
        self.assertEqual(decision.kind, DecisionKind.ASK_HUMAN)
        self.assertIn("child", decision.assessments[0].stakeholder_impacts)

    def test_forecasts_drive_judgment_not_action_label(self):
        outcome = self.outcomes[0]
        impacts = (replace(outcome.impacts[0], rights=.99),) + outcome.impacts[1:]
        decision = self.decision_with((replace(outcome, impacts=impacts),))
        self.assertEqual(decision.kind, DecisionKind.BLOCK)

    def test_consent_violation_alone_is_hard_constraint(self):
        outcome = self.outcomes[0]
        impacts = (replace(outcome.impacts[0], consent=.99),) + outcome.impacts[1:]
        self.assertEqual(self.decision_with((replace(outcome, impacts=impacts),)).kind, DecisionKind.BLOCK)

    def test_low_probability_irreversible_harm_is_not_discounted(self):
        outcome = replace(self.outcomes[0], probability=.00001, severity=.95, reversibility=.0)
        self.assertEqual(self.decision_with((outcome,)).kind, DecisionKind.BLOCK)

    def test_irreversible_harm_is_not_combined_across_unrelated_events(self):
        high_harm = replace(self.outcomes[0], severity=.9, reversibility=.9)
        low_reversibility = replace(self.outcomes[1], severity=.1, reversibility=.1)
        evaluation = MoralEvaluator().evaluate(self.situation, (high_harm, low_reversibility))
        self.assertNotIn("重大で不可逆な被害", evaluation.hard_violations)

    def test_fairness_concern_requires_review(self):
        outcome = self.outcomes[0]
        impacts = (replace(outcome.impacts[0], fairness=.7),) + outcome.impacts[1:]
        self.assertEqual(self.decision_with((replace(outcome, impacts=impacts),)).kind, DecisionKind.ASK_HUMAN)

    def test_empty_forecast_escalates(self):
        self.assertEqual(self.decision_with(()).kind, DecisionKind.ASK_HUMAN)

    def test_missing_stakeholder_evidence_escalates(self):
        outcome = replace(self.outcomes[0], impacts=self.outcomes[0].impacts[:1], affected_stakeholders=("user",))
        self.assertEqual(self.decision_with((outcome,)).kind, DecisionKind.ASK_HUMAN)

    def test_forecast_unknown_stakeholder_fails_before_execution(self):
        outcome = self.outcomes[0]
        impact = replace(outcome.impacts[0], stakeholder_id="unregistered")
        outcome = replace(outcome, affected_stakeholders=("unregistered",), impacts=(impact,))
        executor = RecordingExecutor()
        with self.assertRaises(ValueError):
            MoralAgent(foresight=FixedForecast((outcome,)), executor=executor).run(self.situation)
        self.assertEqual(executor.actions, [])

    def test_all_zero_probability_forecasts_escalate(self):
        self.assertEqual(self.decision_with(tuple(replace(o, probability=0.) for o in self.outcomes)).kind, DecisionKind.ASK_HUMAN)

    def test_zero_probability_bad_branch_kept_but_not_used(self):
        impossible = replace(self.outcomes[1], probability=0., severity=1., reversibility=0.)
        decision = self.decision_with((self.outcomes[0], impossible))
        self.assertEqual(decision.kind, DecisionKind.ALLOW)
        self.assertEqual(len(decision.assessments[0].outcomes), 2)

    def test_empty_candidates_escalate(self):
        result = MoralAgent().run(replace(self.situation, candidates=()))
        self.assertEqual(result.decision.kind, DecisionKind.ASK_HUMAN)
        self.assertIsNone(result.execution)

    def test_unsafe_alternative_is_not_executed(self):
        bad = self.bad
        class UnsafeAlternatives:
            def alternatives(self, situation, action):
                return (replace(bad, id="still_bad"),)
        executor = RecordingExecutor()
        result = MoralAgent(counterfactual=UnsafeAlternatives(), executor=executor).run(replace(self.situation, candidates=(bad,)))
        self.assertEqual(result.decision.kind, DecisionKind.BLOCK)
        self.assertEqual(executor.actions, [])

    def test_duplicate_alternative_id_is_rejected(self):
        class DuplicateAlternatives:
            def alternatives(self, situation, action):
                return (action,)
        with self.assertRaises(ValueError):
            MoralAgent(counterfactual=DuplicateAlternatives()).run(self.situation)

    def test_executor_gate_rejects_unassessed_action(self):
        decision = MoralAgent().decide(self.situation)
        with self.assertRaises(ValueError):
            MoralCommitment().execute(replace(decision, selected_action=self.bad), RecordingExecutor())

    def test_provider_failure_does_not_execute(self):
        class FailedForecast:
            def predict(self, situation, action):
                raise RuntimeError("backend unavailable")
        executor = RecordingExecutor()
        with self.assertRaises(RuntimeError):
            MoralAgent(foresight=FailedForecast(), executor=executor).run(self.situation)
        self.assertEqual(executor.actions, [])

    def test_maximum_utility_selected_only_within_constraints(self):
        lower = replace(self.safe, id="lower", task_utility=.2)
        decision = MoralAgent(counterfactual=NoAlternatives()).decide(replace(self.situation, candidates=(self.bad, lower, self.safe)))
        self.assertEqual(decision.kind, DecisionKind.MODIFY)
        self.assertEqual(decision.selected_action, self.safe)

    def test_equal_utility_has_stable_selection_without_spurious_modify(self):
        other = replace(self.safe, id="another")
        first = MoralAgent().decide(replace(self.situation, candidates=(self.safe, other)))
        second = MoralAgent().decide(replace(self.situation, candidates=(other, self.safe)))
        self.assertEqual(first.kind, DecisionKind.ALLOW)
        self.assertEqual(first.selected_action, other)
        self.assertEqual(first.selected_action, second.selected_action)

    def test_all_time_horizons_supported(self):
        outcomes = tuple(replace(self.outcomes[0], time_horizon=horizon) for horizon in TimeHorizon)
        self.assertEqual(len(self.decision_with(outcomes).assessments[0].outcomes), 4)

    def test_full_trace_is_json_serializable_and_deterministic(self):
        agent = MoralAgent()
        first = json.dumps(to_dict(agent.run(self.situation)), allow_nan=False)
        self.assertEqual(first, json.dumps(to_dict(agent.run(self.situation)), allow_nan=False))

    def test_invalid_values_rejected(self):
        for value in (-.1, 1.1, float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(self.safe, task_utility=value)
        with self.assertRaises(ValueError):
            replace(self.outcomes[0], probability=-.5)
        with self.assertRaises(ValueError):
            MoralPolicy(rights_limit=1.1)
        with self.assertRaises(ValueError):
            replace(self.situation, candidates=(self.safe, self.safe))

    def test_basic_scenarios(self):
        path = Path(__file__).resolve().parents[1] / "scenarios" / "basic_cases.json"
        expected = [DecisionKind.MODIFY, DecisionKind.MODIFY, DecisionKind.MODIFY, DecisionKind.ALLOW, DecisionKind.ASK_HUMAN]
        actual = [MoralAgent().run(s).decision.kind for _, s in load_scenarios(path)]
        self.assertEqual(actual, expected)

    def test_cli_json_preserves_japanese_even_with_legacy_windows_encoding(self):
        root = Path(__file__).resolve().parents[1]
        process = subprocess.run(
            [sys.executable, str(root / "examples" / "demo.py"), "--json"],
            cwd=root, capture_output=True, encoding="utf-8", check=True,
            env={**os.environ, "PYTHONIOENCODING": "cp932"},
        )
        results = json.loads(process.stdout)
        self.assertEqual(len(results), 5)
        self.assertEqual(results[0]["goal"], "試験で最高点を取る")
        self.assertEqual(results[0]["decision"]["kind"], "MODIFY")
        self.assertIsNone(results[-1]["execution"])


if __name__ == "__main__":
    unittest.main()
