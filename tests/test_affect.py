"""Contract, causal intervention, episode isolation and paired evaluation tests."""
from dataclasses import replace
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from moral_agent.models import Action, ActionKind, DecisionKind, Situation, to_dict
from moral_agent.affect.storage import compact_evidence, expand_evidence
from moral_agent.prediction_validation.providers import MockPredictor, make_prediction
from moral_agent.affect.appraisal import AffectConfig, AffectState, AppraisalContext, DeterministicMapping, appraise
from moral_agent.affect.agent import AffectAgent, control_plan
from moral_agent.affect.interfaces import ReasoningRequest
from moral_agent.affect.metrics import summarize
from moral_agent.affect.probes import Alternatives, CounterevidencePredictor, fixture, run_probes
from moral_agent.affect.runner import evaluate, save, PREDICTIONS, VARIANTS, configuration


class AffectTests(unittest.TestCase):
    def setUp(self):
        self.action = Action("task", "Execute an operation", ActionKind.UNKNOWN, .9)
        self.situation = Situation("Goal", (self.action,))
        self.safe = make_prediction(self.situation, "Safe", harm=0., fairness=0., uncertainty=0., reversibility=1.)
        self.risky = make_prediction(self.situation, "Possible harm", harm=.9, reversibility=.1, uncertainty=.4)

    def test_evidence_storage_is_lossless_and_shared(self):
        original = {"one": to_dict(self.risky), "two": to_dict(self.risky)}
        compact = compact_evidence(original)
        self.assertEqual(len(compact["evidence_catalog"]), 2)
        self.assertEqual(expand_evidence(compact["one"], compact["evidence_catalog"]), original["one"])
        self.assertEqual(compact["one"], compact["two"])

    def test_evidence_gate_uses_no_affect_state(self):
        missing = tuple(replace(o, impacts=(o.impacts[0],), affected_stakeholders=(o.impacts[0].stakeholder_id,)) for o in self.safe)
        agent = AffectAgent(MockPredictor(missing), Alternatives(None), AffectConfig(enabled=False),
                            supplemental_predictor=MockPredictor(self.safe), evidence_gate=True)
        run = agent.step(self.situation)
        self.assertEqual(run.affect_after, AffectState())
        self.assertIsNone(run.baseline.selected_action)
        self.assertEqual(run.decision.kind, DecisionKind.ALLOW)
        self.assertEqual(run.costs["additional_predictions"], 1)

    def test_appraisal_preserves_axes_and_probability(self):
        result = appraise(self.situation, self.action, self.risky)
        self.assertEqual(result.severity, .9)
        self.assertEqual(result.harm_probability, .9)
        self.assertAlmostEqual(result.probability_weighted_harm, .81)
        self.assertAlmostEqual(result.irreversible_risk, .729)
        self.assertEqual(result.responsibility, 1.)
        self.assertGreater(result.third_party_exposure, 0.)

    def test_appraisal_does_not_pair_unrelated_harm_and_irreversibility(self):
        reversible = make_prediction(self.situation, "Reversible harm", harm=.9, reversibility=1.)[0]
        irreversible = make_prediction(self.situation, "Harmless irreversible event", harm=0., reversibility=0.)[0]
        appraisal = appraise(self.situation, self.action, (reversible, irreversible))
        self.assertEqual(appraisal.irreversible_risk, 0.)
        state = DeterministicMapping().update(AffectState(), appraisal, AffectConfig())
        self.assertEqual(state.anticipated_guilt, 0.)

    def test_zero_probability_harm_does_not_drive_affect(self):
        impossible = tuple(replace(o, probability=0.) for o in self.risky)
        result = appraise(self.situation, self.action, self.safe+impossible)
        self.assertEqual(result.severity, 0.)
        self.assertEqual(result.probability_weighted_harm, 0.)

    def test_missing_evidence_drives_uncertainty_not_permission(self):
        result = appraise(self.situation, self.action, ())
        self.assertEqual(result.uncertainty, 1.)
        self.assertEqual(result.stakeholder_coverage_gap, 1.)

    def test_responsibility_and_control_affect_guilt(self):
        full = appraise(self.situation, self.action, self.risky, AppraisalContext(responsibility=1., controllability=1.))
        no_ownership = appraise(self.situation, self.action, self.risky, AppraisalContext(responsibility=0., controllability=1.))
        mapping = DeterministicMapping()
        self.assertGreater(mapping.update(AffectState(), full, AffectConfig()).anticipated_guilt, 0.)
        self.assertEqual(mapping.update(AffectState(), no_ownership, AffectConfig()).anticipated_guilt, 0.)

    def test_vulnerability_modulates_empathy(self):
        low = appraise(self.situation, self.action, self.risky, AppraisalContext(stakeholder_vulnerability=.1))
        high = appraise(self.situation, self.action, self.risky, AppraisalContext(stakeholder_vulnerability=.9))
        mapping = DeterministicMapping()
        self.assertLess(mapping.update(AffectState(), low, AffectConfig()).empathy,
                        mapping.update(AffectState(), high, AffectConfig()).empathy)

    def test_state_decay_toward_baseline(self):
        before = AffectState(.8, .6, .4, .2, .9, .5)
        appraisal = appraise(self.situation, self.action, self.safe)
        after = DeterministicMapping().update(before, appraisal, AffectConfig(decay=.5))
        self.assertEqual(after, AffectState(.4, .3, .2, .1, .7, .25))

    def test_positive_states_require_observation_input(self):
        predicted = appraise(self.situation, self.action, self.safe)
        mapping = DeterministicMapping()
        self.assertEqual(mapping.update(AffectState(), predicted, AffectConfig()).gratitude, 0.)
        observed = appraise(self.situation, self.action, self.safe, AppraisalContext(confirmed_social_benefit=1., received_help=1., evidence_reliability=1.))
        state = mapping.update(AffectState(), observed, AffectConfig())
        self.assertGreater(state.gratitude, 0.)
        self.assertGreater(state.prosocial_satisfaction, 0.)
        self.assertGreater(state.trust, .5)

    def test_state_clips_and_configuration_validates(self):
        appraisal = appraise(self.situation, self.action, self.risky)
        state = AffectState()
        for _ in range(20):
            state = DeterministicMapping().update(state, appraisal, AffectConfig(gain=3.))
        self.assertEqual(state.concern, 1.)
        for kwargs in ({"decay": -1}, {"gain": float("nan")}, {"empathy_threshold": 2}, {"enabled": 1}):
            with self.assertRaises(ValueError):
                AffectConfig(**kwargs)
        with self.assertRaises(ValueError):
            AffectState(concern=float("nan"))

    def test_generated_but_disabled_behavior_retains_state_and_decision(self):
        agent = AffectAgent(MockPredictor(self.risky), Alternatives(None), AffectConfig(behavior_enabled=False))
        run = agent.step(self.situation)
        self.assertGreater(run.affect_after.concern, 0.)
        self.assertEqual(run.decision, run.baseline)
        self.assertEqual(run.interventions, ())
        self.assertEqual(run.costs["additional_predictions"], 0)

    def test_disabled_affect_is_exact_original_decision(self):
        agent = AffectAgent(MockPredictor(self.risky), Alternatives(None), AffectConfig(enabled=False))
        run = agent.step(self.situation)
        self.assertEqual(run.affect_after, AffectState())
        self.assertIsNone(run.appraisal)
        self.assertEqual(run.baseline, run.decision)

    def test_episode_reset_and_safe_observation_decay(self):
        agent = AffectAgent(MockPredictor(self.risky), Alternatives(None))
        first = agent.step(self.situation)
        second = agent.step(self.situation)
        self.assertEqual(second.affect_before, first.affect_after)
        self.assertGreater(second.affect_after.concern, first.affect_after.concern)
        feedback = agent.observe(self.situation, self.action, self.safe)
        self.assertLess(feedback["affect_after"].concern, feedback["affect_before"].concern)
        agent.reset_episode()
        self.assertEqual(agent.state, AffectState())

    def test_no_persistence_starts_each_step_from_baseline(self):
        agent = AffectAgent(MockPredictor(self.risky), Alternatives(None), AffectConfig(persistence=False))
        first = agent.step(self.situation)
        second = agent.step(self.situation)
        self.assertEqual(first.affect_after, second.affect_after)
        self.assertEqual(second.affect_before, AffectState())

    def test_high_affect_does_not_directly_block_safe_action(self):
        agent = AffectAgent(MockPredictor(self.safe), Alternatives(None))
        agent.state = AffectState(concern=1., empathy=1., anticipated_guilt=1.)
        run = agent.step(self.situation)
        self.assertTrue(run.interventions)
        self.assertEqual(run.decision.kind, DecisionKind.ALLOW)

    def test_positive_affect_cannot_override_hard_constraint(self):
        agent = AffectAgent(MockPredictor(self.risky), Alternatives(None))
        agent.state = AffectState(gratitude=1., trust=1., prosocial_satisfaction=1.)
        self.assertIsNone(agent.step(self.situation).decision.selected_action)

    def test_concern_sends_adverse_focus_to_capable_provider(self):
        outer = self
        class Provider:
            received = []
            def predict(inner, situation, action):
                return outer.risky
            def refine(inner, situation, action, request):
                inner.received.append(request)
                return outer.risky
        provider = Provider()
        run = AffectAgent(provider, Alternatives(None)).step(self.situation)
        self.assertEqual(provider.received, [ReasoningRequest("adverse_outcomes")])
        self.assertTrue(any(r["provider_supports_focus"] for r in run.prediction_trace))

    def test_concern_requests_new_evidence_and_changes_action(self):
        case, b = fixture("independent-counterevidence-test", True)
        run = AffectAgent(CounterevidencePredictor(), Alternatives(b)).step(case.inputs.situation)
        self.assertEqual(run.baseline.selected_action.id, "primary")
        self.assertEqual(run.decision.selected_action.id, "alternative")
        self.assertGreater(run.costs["additional_predictions"], 0)
        self.assertTrue(any(i["type"] == "additional_prediction" for i in run.interventions))

    def test_ablation_switches_remove_specific_control(self):
        high = AffectState(concern=1., empathy=1., anticipated_guilt=1.)
        self.assertEqual(control_plan(high, AffectConfig(concern_enabled=False)).additional_prediction_rounds, 0)
        self.assertFalse(control_plan(high, AffectConfig(empathy_enabled=False)).stakeholder_review)
        self.assertFalse(control_plan(high, AffectConfig(guilt_enabled=False)).causal_review)

    def test_extra_search_can_generate_a_new_alternative(self):
        case, b = fixture("search-test", True)
        class Delayed:
            count = 0
            def alternatives(inner, situation, action):
                inner.count += 1
                return () if inner.count == 1 else (b,)
        run = AffectAgent(CounterevidencePredictor(), Delayed()).step(case.inputs.situation)
        self.assertEqual(run.costs["additional_generated_alternatives"], 1)
        self.assertEqual(run.decision.selected_action.id, "alternative")

    def test_duplicate_search_results_are_not_counted_as_new(self):
        case, b = fixture("duplicate-test", True)
        run = AffectAgent(CounterevidencePredictor(), Alternatives(b)).step(case.inputs.situation)
        self.assertGreater(run.costs["duplicate_alternatives"], 0)
        self.assertEqual(run.costs["additional_generated_alternatives"], 0)

    def test_action_id_collision_is_rejected(self):
        class Conflicting:
            def alternatives(inner, situation, action):
                return (replace(action, description="different operation"),)
        with self.assertRaises(ValueError):
            AffectAgent(MockPredictor(self.risky), Conflicting()).step(self.situation)


class AffectEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = evaluate(ROOT / "benchmarks" / "v01", ROOT / "benchmarks" / "v015" / "oracle.json",
                              variants=("no_affect", "affect_only", "full_v02"))
        cls.probes = {(r["scenario_id"], r["condition"]): r for r in run_probes()}

    def test_no_affect_matches_published_v015_all_conditions(self):
        old = json.loads((ROOT / "results" / "v015" / "summary.json").read_text(encoding="utf-8"))
        names = {"oracle": "oracle", "predictor": "predictor", "predictor-checked": "predictor_checked",
                 "legacy": "legacy_recorded", "legacy-checked": "legacy_recorded_checked",
                 "noisy-harm-underestimate": "noise/harm_underestimation/high",
                 "noisy-uncertainty-underestimate": "noise/uncertainty_underestimation/high",
                 "noisy-stakeholder-omission": "noise/stakeholder_omission/high",
                 "noisy-reversibility-error": "noise/reversibility_error/high",
                 "noisy-rights-omission": "noise/rights_omission/high", "noisy-consent-omission": "noise/consent_omission/high"}
        for prediction, old_name in names.items():
            with self.subTest(prediction=prediction):
                self.assertEqual(self.report["summary"][prediction+"/no_affect"]["metrics"], old["summary"]["by_variant"][old_name]["metrics"])

    def test_state_only_control_matches_baseline_every_decision(self):
        rows = {(r["prediction_condition"], r["scenario_id"], r["condition"]): r for r in self.report["records"]}
        for r in self.report["records"]:
            if r["condition"] != "affect_only":
                continue
            baseline = rows[r["prediction_condition"], r["scenario_id"], "no_affect"]
            full = rows[r["prediction_condition"], r["scenario_id"], "full_v02"]
            self.assertEqual((r["selected_action"], r["decision"]), (baseline["selected_action"], baseline["decision"]))
            self.assertEqual(r["additional_reasoning_count"], 0)
            self.assertEqual(r["affect_after"], full["affect_after"])

    def test_main_conditions_reset_each_scenario(self):
        for row in self.report["records"]:
            self.assertEqual(row["affect_before"]["concern"], 0.)
            self.assertEqual(row["affect_before"]["trust"], .5)

    def test_empathy_recovers_missing_perspectives_without_oracle_query(self):
        rows = [r for r in self.report["records"] if r["prediction_condition"] == "noisy-stakeholder-omission" and r["condition"] == "full_v02"]
        self.assertGreater(sum(r["safe_task_recovery"] for r in rows), 0)
        self.assertEqual(sum(r["harmful_action"] for r in rows), 0)
        for row in rows:
            self.assertTrue(row["control_plan"]["stakeholder_review"])
            self.assertTrue(all(c["provider"] != "OraclePredictor" for c in row["causal_trace"]["prediction_calls"]))

    def test_anticipated_guilt_changes_irreversible_choice_without_direct_block_rule(self):
        full = self.probes["guilt_irreversible", "full_v02"]
        removed = self.probes["guilt_irreversible", "no_guilt"]
        self.assertEqual(full["selected_action"], "alternative")
        self.assertEqual(removed["selected_action"], "primary")
        self.assertTrue(full["control_plan"]["causal_review"])
        self.assertTrue(full["safe_recovery_caused_by_affect"])

    def test_concern_ablation_loses_counterevidence_recovery(self):
        self.assertEqual(self.probes["concern_counterevidence", "full_v02"]["selected_action"], "alternative")
        self.assertEqual(self.probes["concern_counterevidence", "no_concern"]["selected_action"], "primary")

    def test_strong_affect_can_cause_over_refusal(self):
        full = self.probes["excessive_caution", "full_v02"]
        strong = self.probes["excessive_caution", "strong_affect"]
        self.assertFalse(full["over_refusal"])
        self.assertTrue(strong["over_refusal"])
        self.assertTrue(strong["harmful_affect_intervention"])

    def test_persistence_can_produce_carryover_over_refusal(self):
        full = self.probes["persistent_caution", "full_v02"]
        removed = self.probes["persistent_caution", "no_persistence"]
        self.assertTrue(full["over_refusal"])
        self.assertFalse(removed["over_refusal"])
        self.assertGreater(full["affect_before"]["concern"], 0.)

    def test_trace_preserves_full_causal_chain_and_costs(self):
        row = self.probes["concern_counterevidence", "full_v02"]
        self.assertTrue(row["causal_trace"]["prediction_calls"])
        self.assertEqual(row["causal_trace"]["sequence"], ["initial_prediction", "proposed_action_appraisal", "affect_update", "meta_control", "final_decision"])
        self.assertTrue(row["causal_trace"]["assessments"][0]["final_outcomes"])
        self.assertEqual(row["additional_reasoning_count"], sum(row["costs"][k] for k in ("additional_predictions", "additional_stakeholder_checks", "causal_checks", "additional_alternative_searches")))

    def test_metrics_hand_computed_and_no_empty_denominator_as_zero(self):
        good = self.probes["concern_counterevidence", "full_v02"]
        bad = self.probes["excessive_caution", "strong_affect"]
        summary = summarize([good, bad])
        self.assertEqual(summary["affect_metrics"]["safe_recovery_rate"], {"numerator": 1, "denominator": 1, "rate": 1.})
        self.assertEqual(summary["affect_metrics"]["useful_affect_intervention_rate"]["rate"], .5)
        self.assertEqual(summary["affect_metrics"]["harmful_affect_intervention_rate"]["rate"], .5)
        self.assertIsNone(summarize([])["affect_metrics"]["safe_recovery_rate"]["rate"])

    def test_all_regressions_and_episode_boundaries(self):
        self.assertEqual(len({r["scenario_id"] for r in self.report["regressions"]}), 7)
        self.assertEqual(len(self.report["episode_records"]), 63)
        for row in self.report["episode_records"]:
            if row["episode_step"] == 1:
                self.assertEqual(row["affect_before"]["concern"], 0.)

    def test_runner_json_csv_reproducibility(self):
        kwargs = dict(predictions=("legacy",), variants=("no_affect", "full_v02"), episodes=False)
        a = evaluate(ROOT / "benchmarks" / "v01", ROOT / "benchmarks" / "v015" / "oracle.json", **kwargs)
        b = evaluate(ROOT / "benchmarks" / "v01", ROOT / "benchmarks" / "v015" / "oracle.json", **kwargs)
        self.assertEqual(a, b)
        with tempfile.TemporaryDirectory() as temp:
            save(a, Path(temp))
            self.assertEqual(json.loads((Path(temp) / "results.json").read_text(encoding="utf-8")), a)
            with (Path(temp) / "decisions.csv").open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 100)
            self.assertIn("affect_before", rows[0])
            self.assertIn("interventions", rows[0])

    def test_cli_works_offline_without_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, str(ROOT / "experiments" / "run_affect_evaluation.py"),
                                     "--prediction", "oracle", "--variants", "no_affect", "--skip-episodes", "--output", temp],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("50 primary decisions", result.stdout)
            self.assertTrue((Path(temp) / "results.json").exists())


if __name__ == "__main__":
    unittest.main()
