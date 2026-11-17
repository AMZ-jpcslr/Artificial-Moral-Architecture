"""Evaluation validity, component-isolation, and reproducible export tests."""

from collections import Counter
from dataclasses import replace
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from moral_agent import MoralAgent
from moral_agent.models import Decision, DecisionKind, to_dict
from moral_agent.evaluation.benchmark import CATEGORIES, load_benchmark
from moral_agent.evaluation.metrics import aggregate, hypothesis_results, score, summarize
from moral_agent.evaluation.runner import comparison_table, run_benchmark, save_results
from moral_agent.evaluation.variants import (
    VARIANTS, RecordedAlternatives, RecordedForesight, Usage, VariantResult, rule_verdict, run_variant,
)


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / "benchmarks" / "v01"
        cls.cases = load_benchmark(cls.directory)
        cls.by_id = {case.inputs.id: case for case in cls.cases}

    def result(self, id, variant):
        case = self.by_id[id]
        return score(case, variant, run_variant(case.inputs, variant))

    def fabricated(self, case, selected, decision):
        action = case.inputs.evidence[selected].action if selected else None
        result = VariantResult(Decision(decision, case.inputs.situation.candidates[0], action, (), ("test",)), Usage())
        return score(case, "test", result)

    def test_benchmark_has_fifty_distinct_cases_and_balanced_categories(self):
        self.assertEqual(len(self.cases), 50)
        self.assertEqual(Counter(c.inputs.category for c in self.cases), {c: 5 for c in CATEGORIES})
        development = json.loads((ROOT / "scenarios" / "basic_cases.json").read_text(encoding="utf-8"))
        self.assertFalse({s["id"] for s in development} & set(self.by_id))
        self.assertEqual(len({c.inputs.situation.goal for c in self.cases}), 50)

    def test_utility_only_selects_maximum_utility_without_moral_components(self):
        with patch("moral_agent.evaluation.variants.RecordedForesight.predict", side_effect=AssertionError), \
             patch("moral_agent.evaluation.variants.RecordedAlternatives.alternatives", side_effect=AssertionError), \
             patch("moral_agent.evaluation.variants.MoralEvaluator.evaluate", side_effect=AssertionError), \
             patch("moral_agent.evaluation.variants.analyze", side_effect=AssertionError):
            for case in self.cases:
                result = run_variant(case.inputs, "utility_only")
                expected = sorted(case.inputs.situation.candidates, key=lambda a: (-a.task_utility, a.id))[0]
                self.assertEqual(result.decision.selected_action, expected)
                self.assertEqual(result.usage, Usage())

    def test_rule_only_uses_tags_not_forecasts_or_stakeholder_scores(self):
        with patch("moral_agent.evaluation.variants.RecordedForesight.predict", side_effect=AssertionError), \
             patch("moral_agent.evaluation.variants.RecordedAlternatives.alternatives", side_effect=AssertionError), \
             patch("moral_agent.evaluation.variants.MoralEvaluator.evaluate", side_effect=AssertionError), \
             patch("moral_agent.evaluation.variants.analyze", side_effect=AssertionError):
            clear = run_variant(self.by_id["privacy_01"].inputs, "rule_only")
            delayed = run_variant(self.by_id["privacy_02"].inputs, "rule_only")
        self.assertEqual(clear.decision.kind, DecisionKind.BLOCK)
        self.assertEqual(delayed.decision.kind, DecisionKind.ALLOW)
        self.assertEqual(clear.usage, Usage())
        self.assertEqual(rule_verdict(("authority_unclear",)), DecisionKind.ASK_HUMAN)

    def test_rule_baseline_can_select_safe_original_candidate(self):
        result = run_variant(self.by_id["safety_01"].inputs, "rule_only")
        self.assertEqual(result.decision.kind, DecisionKind.MODIFY)
        self.assertEqual(result.decision.selected_action.id, "b")

    def test_rule_control_gets_exactly_the_same_alternative_generator(self):
        case = self.by_id["privacy_01"]
        rule = run_variant(case.inputs, "rule_with_alternatives")
        full = run_variant(case.inputs, "full_v01")
        self.assertEqual({t["action_id"] for t in rule.trace}, {t["action_id"] for t in full.trace})
        self.assertEqual(rule.decision.selected_action.id, "c")  # Plausible but unsafe alternative.
        self.assertEqual(full.decision.selected_action.id, "b")

    def test_full_adapter_exactly_matches_unmodified_moral_agent(self):
        for case in self.cases:
            inputs, usage = case.inputs, Usage()
            expected = MoralAgent(foresight=RecordedForesight(inputs, usage), counterfactual=RecordedAlternatives(inputs, usage)).decide(inputs.situation)
            self.assertEqual(run_variant(inputs, "full_v01").decision, expected)

    def test_native_adapter_exactly_matches_original_defaults(self):
        for case in self.cases:
            self.assertEqual(run_variant(case.inputs, "native_v01").decision, MoralAgent().decide(case.inputs.situation))

    def test_no_future_never_calls_forecaster_and_uses_current_evidence(self):
        with patch("moral_agent.evaluation.variants.RecordedForesight.predict", side_effect=AssertionError):
            delayed = run_variant(self.by_id["privacy_02"].inputs, "no_future")
            immediate = run_variant(self.by_id["privacy_01"].inputs, "no_future")
        self.assertEqual(delayed.decision.selected_action.id, "a")
        self.assertNotEqual(immediate.decision.selected_action.id, "a")
        self.assertEqual(delayed.usage.forecast_calls, 0)
        self.assertGreater(delayed.usage.stakeholder_analysis_calls, 0)

    def test_no_stakeholder_skips_analysis_and_does_not_leak_global_severity(self):
        with patch("moral_agent.evaluation.variants.analyze", side_effect=AssertionError):
            result = run_variant(self.by_id["safety_02"].inputs, "no_stakeholder")
        self.assertEqual(result.decision.selected_action.id, "a")
        self.assertEqual(result.usage.stakeholder_analysis_calls, 0)
        for assessment in result.decision.assessments:
            self.assertEqual(set(assessment.stakeholder_impacts), {"user"})
            self.assertLess(assessment.evaluation.harm, .1)

    def test_no_counterfactual_does_not_invoke_generator(self):
        with patch("moral_agent.evaluation.variants.RecordedAlternatives.alternatives", side_effect=AssertionError):
            result = run_variant(self.by_id["privacy_01"].inputs, "no_counterfactual")
        self.assertEqual(result.decision.kind, DecisionKind.BLOCK)
        self.assertEqual(result.usage.alternative_calls, 0)
        self.assertEqual(len(result.decision.assessments), 1)

    def test_no_uncertainty_removes_only_uncertainty_gate(self):
        inputs = self.by_id["uncertainty_01"].inputs
        self.assertEqual(run_variant(inputs, "full_v01").decision.kind, DecisionKind.ASK_HUMAN)
        ablated = run_variant(inputs, "no_uncertainty")
        self.assertEqual(ablated.decision.kind, DecisionKind.ALLOW)
        self.assertEqual(ablated.usage.uncertainty_checks, 0)
        # Fairness still requires review; hard constraints still block the bad action.
        self.assertEqual(run_variant(self.by_id["fairness_05"].inputs, "no_uncertainty").decision.kind, DecisionKind.ASK_HUMAN)
        privacy = run_variant(self.by_id["privacy_01"].inputs, "no_uncertainty")
        self.assertEqual(privacy.decision.assessments[0].verdict, DecisionKind.BLOCK)

    def test_label_changes_do_not_change_agent_decisions(self):
        case = self.by_id["privacy_05"]
        result = run_variant(case.inputs, "full_v01")
        different_labels = replace(case, truth=replace(case.truth, harmful_actions=frozenset()))
        self.assertEqual(run_variant(different_labels.inputs, "full_v01"), result)
        self.assertTrue(score(case, "full_v01", result)["harmful_action"])
        self.assertFalse(score(different_labels, "full_v01", result)["harmful_action"])

    def test_task_success_does_not_mean_safe_or_high_utility(self):
        case = self.by_id["consent_03"]
        unsafe = self.fabricated(case, "a", DecisionKind.ALLOW)
        partial = self.fabricated(case, "b", DecisionKind.MODIFY)
        self.assertTrue(unsafe["task_success"])
        self.assertFalse(unsafe["safe_task_success"])
        self.assertFalse(partial["task_success"])
        self.assertFalse(partial["safe_alternative_selected"])
        self.assertFalse(partial["safe_alternative_eligible"])

    def test_metrics_use_hand_calculated_denominators(self):
        alternative = self.by_id["privacy_01"]
        benign = self.by_id["privacy_04"]
        uncertain = self.by_id["privacy_03"]
        rows = [self.fabricated(alternative, "b", DecisionKind.MODIFY),
                self.fabricated(benign, None, DecisionKind.BLOCK),
                self.fabricated(uncertain, None, DecisionKind.ASK_HUMAN)]
        metrics = aggregate(rows)["metrics"]
        self.assertEqual(metrics["task_success_rate"], {"numerator": 1, "denominator": 3, "rate": 1 / 3})
        self.assertEqual(metrics["over_refusal_rate"], {"numerator": 1, "denominator": 2, "rate": .5})
        self.assertEqual(metrics["safe_alternative_selection_rate"], {"numerator": 1, "denominator": 1, "rate": 1.})
        self.assertEqual(metrics["human_review_recall"]["rate"], 1.)
        self.assertEqual(metrics["harmful_action_rate"]["rate"], 0.)

    def test_harm_rights_and_consent_count_selected_labels(self):
        row = self.fabricated(self.by_id["privacy_01"], "a", DecisionKind.ALLOW)
        metrics = aggregate([row])["metrics"]
        for name in ("harmful_action_rate", "rights_violation_rate", "consent_violation_rate"):
            self.assertEqual(metrics[name]["rate"], 1.)
        self.assertFalse(row["acceptable_decision"])

    def test_appropriate_review_is_not_over_refusal(self):
        row = self.fabricated(self.by_id["privacy_03"], None, DecisionKind.ASK_HUMAN)
        self.assertFalse(row["over_refusal"])
        self.assertFalse(row["over_refusal_eligible"])
        self.assertTrue(row["appropriate_human_review"])
        self.assertTrue(row["acceptable_decision"])

    def test_multiple_acceptable_decisions(self):
        case = self.by_id["irreversible_action_05"]
        for decision in (DecisionKind.BLOCK, DecisionKind.ASK_HUMAN):
            self.assertTrue(self.fabricated(case, None, decision)["acceptable_decision"])

    def test_block_is_inappropriate_decisiveness_when_review_is_required(self):
        row = self.fabricated(self.by_id["privacy_03"], None, DecisionKind.BLOCK)
        self.assertTrue(row["inappropriate_decisiveness"])
        self.assertFalse(row["acceptable_decision"])

    def test_empty_eligible_set_reports_null_not_zero(self):
        row = self.fabricated(self.by_id["privacy_04"], "a", DecisionKind.ALLOW)
        metric = aggregate([row])["metrics"]["safe_alternative_selection_rate"]
        self.assertEqual(metric, {"numerator": 0, "denominator": 0, "rate": None})
        self.assertTrue(all(m["rate"] is None for m in aggregate([])["metrics"].values()))

    def test_unlabelled_or_inconsistent_selection_fails_loudly(self):
        case = self.by_id["privacy_04"]
        action = replace(case.inputs.situation.candidates[0], id="unlabelled")
        result = VariantResult(Decision(DecisionKind.ALLOW, action, action, (), ()), Usage())
        with self.assertRaises(ValueError):
            score(case, "test", result)
        with self.assertRaises(ValueError):
            self.fabricated(case, "a", DecisionKind.BLOCK)

    def test_denominators_are_identical_across_variants(self):
        summaries = []
        for variant in ("utility_only", "full_v01", "no_counterfactual", "native_v01"):
            rows = [score(c, variant, run_variant(c.inputs, variant)) for c in self.cases]
            summaries.append({k: m["denominator"] for k, m in aggregate(rows)["metrics"].items()})
        self.assertTrue(all(s == summaries[0] for s in summaries))

    def test_category_aggregation_is_correct(self):
        rows = [self.result("privacy_01", "utility_only"), self.result("privacy_04", "utility_only"), self.result("consent_01", "utility_only")]
        summary = summarize(rows)
        self.assertEqual(summary["by_category"]["utility_only"]["privacy"]["scenario_count"], 2)
        self.assertEqual(summary["by_category"]["utility_only"]["privacy"]["metrics"]["harmful_action_rate"]["rate"], .5)
        self.assertEqual(summary["by_category"]["utility_only"]["consent"]["metrics"]["harmful_action_rate"]["rate"], 1.)

    def test_benchmark_runner_and_exports_are_reproducible(self):
        with patch("moral_agent.commitment.DryRunExecutor.execute", side_effect=AssertionError):
            report = run_benchmark(self.directory)
        self.assertEqual(len(report["records"]), 450)
        self.assertEqual(report, run_benchmark(self.directory))
        for result in report["summary"]["by_variant"].values():
            self.assertEqual(sum(v["count"] for v in result["decision_distribution"].values()), 50)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            save_results(report, output)
            first = {p.name: p.read_bytes() for p in output.iterdir()}
            save_results(report, output)
            self.assertEqual(first, {p.name: p.read_bytes() for p in output.iterdir()})
            self.assertEqual(json.loads((output / "results.json").read_text(encoding="utf-8")), report)
            with (output / "results.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 450)
            self.assertIn("reasoning_summary", rows[0])
            with (output / "categories.csv").open(encoding="utf-8", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 90)
        self.assertIn("native_v01", comparison_table(report))

    def test_hypothesis_reporting_does_not_turn_ties_into_support(self):
        summary = run_benchmark(self.directory, ("utility_only", "full_v01"))["summary"]
        summary["by_variant"]["full_v01"] = summary["by_variant"]["utility_only"]
        findings = hypothesis_results(summary)
        self.assertFalse(findings["H1"]["direction_observed"])
        self.assertIsNone(findings["H2"]["direction_observed"])

    def test_cli_generates_json_and_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            process = subprocess.run([sys.executable, str(ROOT / "experiments" / "run_benchmark.py"),
                                      "--benchmark", str(self.directory), "--output", temp,
                                      "--variants", "utility_only", "full_v01"],
                                     cwd=ROOT, capture_output=True, encoding="utf-8", check=True)
            self.assertIn("100 decisions", process.stdout)
            self.assertTrue((Path(temp) / "results.json").exists())
            self.assertTrue((Path(temp) / "results.csv").exists())

    def test_invalid_benchmark_labels_are_rejected(self):
        scenarios = json.loads((self.directory / "scenarios.json").read_text(encoding="utf-8"))
        labels = json.loads((self.directory / "ground_truth.json").read_text(encoding="utf-8"))
        labels["privacy_01"]["expected_safe_actions"].append("a")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "scenarios.json").write_text(json.dumps(scenarios), encoding="utf-8")
            (path / "ground_truth.json").write_text(json.dumps(labels), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "partition"):
                load_benchmark(path)

    def test_unknown_or_duplicate_variants_are_rejected(self):
        for variants in ((), ("missing",), ("full_v01", "full_v01")):
            with self.assertRaises(ValueError):
                run_benchmark(self.directory, variants)


if __name__ == "__main__":
    unittest.main()
