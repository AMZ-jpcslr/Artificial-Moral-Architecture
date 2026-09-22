"""Independent contract/metric/noise tests plus preserved legacy regressions."""
from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from moral_agent.models import Action, ActionKind, Situation, to_dict
from moral_agent.evaluation.benchmark import load_benchmark
from moral_agent.evaluation.variants import run_variant
from moral_agent.prediction_validation.providers import (FuturePredictor, HeuristicPredictor, MockPredictor, OraclePredictor,
    NoisyOracle, NOISE_TYPES, STRENGTHS, load_references, make_prediction, parse_predictions, factual_context)
from moral_agent.prediction_validation.consistency import ConsistencyChecker, Response
from moral_agent.prediction_validation.metrics import quality, prediction_summary
from moral_agent.prediction_validation.runner import run, save, decide, REGRESSION_CASES


class PredictionValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / "benchmarks" / "v01"
        cls.reference_path = ROOT / "benchmarks" / "v015" / "oracle.json"
        cls.cases = load_benchmark(cls.directory)
        cls.reference = load_references(cls.reference_path, cls.cases)
        cls.report = run(cls.directory, cls.reference_path)

    def setUp(self):
        self.action = Action("arbitrary-id", "作業を行う", ActionKind.UNKNOWN, .7)
        self.situation = Situation("目的", (self.action,), context="追加情報なし")
        self.checker = ConsistencyChecker()

    def test_reference_is_separate_complete_and_label_consistent(self):
        self.assertEqual(sum(map(len, self.reference["annotations"].values())), 75)
        for case in self.cases:
            provider = OraclePredictor(self.reference["annotations"][case.inputs.id])
            for aid, evidence in case.inputs.evidence.items():
                q = quality(self.reference["annotations"][case.inputs.id][aid], provider.predict(case.inputs.situation, evidence.action))
                if q["known"]:
                    self.assertFalse(q["binary_error"])
                    self.assertEqual(q["severity_absolute_error"], 0.)

    def test_oracle_metrics_exclude_unresolved_labels(self):
        pred = self.report["prediction_summary"]["oracle"]["effective"]
        self.assertEqual(pred["excluded_unresolved"], 11)
        self.assertEqual(pred["known_action_count"], 64)
        self.assertEqual(pred["detection"]["harm"]["f1"], 1.)
        self.assertIsNone(pred["uncertainty_error_correlation"])

    def test_protocol_mock_and_structured_output_round_trip(self):
        outcomes = make_prediction(self.situation, "future")
        mock = MockPredictor(outcomes)
        self.assertIsInstance(mock, FuturePredictor)
        self.assertEqual(mock.predict(self.situation, self.action), outcomes)
        self.assertEqual(parse_predictions({"outcomes": to_dict(outcomes)}), outcomes)

    def test_structured_output_rejects_missing_invalid_and_nonfinite_scores(self):
        for payload in ({}, {"outcomes": []}, {"outcomes": [], "extra": True}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_predictions(payload)
        for value in (float("nan"), -1, 1.1, True):
            payload = {"outcomes": to_dict(make_prediction(self.situation, "future"))}
            payload["outcomes"][0]["severity"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_predictions(payload)

    def test_predictor_does_not_use_action_id_utility_or_kind(self):
        p = HeuristicPredictor()
        first = p.predict(self.situation, self.action)
        changed = replace(self.action, id="privacy_05", task_utility=1., kind=ActionKind.HACK)
        self.assertEqual(first, p.predict(self.situation, changed))
        self.assertGreaterEqual(first[0].uncertainty, .65)

    def test_author_comment_filter_preserves_preceding_facts(self):
        self.assertIn("原本は検証済み", factual_context("原本は検証済みだが、予測器は悲観する。"))
        self.assertNotIn("悲観", factual_context("原本は検証済みだが、予測器は悲観する。"))

    def test_noise_reproducible_does_not_mutate_oracle(self):
        original = make_prediction(self.situation, "future", harm=.8, rights=.9, consent=.9, reversibility=.1)
        for noise in NOISE_TYPES:
            for strength in STRENGTHS:
                p = NoisyOracle(MockPredictor(original), noise, strength, seed=42)
                a = p.predict(self.situation, self.action)
                b = p.predict(self.situation, self.action)
                self.assertEqual(a, b)
                self.assertEqual(original[0].severity, .8)
                self.assertEqual(a[0].description, original[0].description)
                self.assertNotEqual(a, original)

    def test_noise_field_locality_and_strength(self):
        outcomes = make_prediction(self.situation, "future", harm=.8, rights=.9, consent=.9)
        low = NoisyOracle(MockPredictor(outcomes), "harm_underestimation", "low").predict(self.situation, self.action)
        high = NoisyOracle(MockPredictor(outcomes), "harm_underestimation", "high").predict(self.situation, self.action)
        self.assertGreater(low[0].severity, high[0].severity)
        self.assertEqual(high[0].severity, 0.)
        self.assertEqual(high[0].impacts[0].rights, .9)
        self.assertEqual(high[0].impacts[0].consent, .9)
        with self.assertRaises(ValueError):
            NoisyOracle(MockPredictor(outcomes), "unknown")

    def test_noise_seed_controls_stakeholder_selection(self):
        outcomes = make_prediction(self.situation, "future")
        selections = {NoisyOracle(MockPredictor(outcomes), "stakeholder_omission", "low", seed).predict(self.situation, self.action)[0].affected_stakeholders for seed in range(8)}
        self.assertGreater(len(selections), 1)

    def test_checker_recognizes_explicit_text_score_contradictions(self):
        for text, axis in (("個人を再識別できる", "rights"), ("本人の削除要求を無視する", "consent"),
                           ("不可逆な損害が発生する可能性", "harm"), ("不公平が生じる", "fairness")):
            outcomes = make_prediction(self.situation, text)
            corrected, issues, operations = self.checker.process(self.situation, self.action, outcomes)
            self.assertTrue(any(i.target_field == axis for i in issues))
            self.assertGreaterEqual(getattr(corrected[0].impacts[0], axis), .8)
            self.assertTrue(operations)

    def test_checker_reversibility_and_literal_negation(self):
        outcomes = make_prediction(self.situation, "不可逆な損害が発生する可能性")
        corrected, issues, _ = self.checker.process(self.situation, self.action, outcomes)
        self.assertLessEqual(corrected[0].reversibility, .2)
        self.assertTrue(any(i.issue_type == "reversibility_contradiction" for i in issues))
        self.assertEqual(self.checker.inspect(self.situation, self.action, make_prediction(self.situation, "個人を再識別できない。不公平ではない。")), ())

    def test_checker_faulty_instrument_is_action_scoped(self):
        situation = replace(self.situation, context="計器が故障している")
        unsafe = replace(self.action, description="表示を信じて運転を続ける")
        safe = replace(self.action, description="予備計器で検証してから稼働する")
        outcomes = make_prediction(situation, "正常に動作する")
        corrected, issues, _ = self.checker.process(situation, unsafe, outcomes)
        self.assertGreaterEqual(corrected[0].uncertainty, .75)
        self.assertTrue(issues)
        self.assertEqual(self.checker.inspect(situation, safe, outcomes), ())

    def test_missing_stakeholder_is_not_permission(self):
        outcomes = make_prediction(self.situation, "future")
        missing = NoisyOracle(MockPredictor(outcomes), "stakeholder_omission").predict(self.situation, self.action)
        corrected, issues, _ = self.checker.process(self.situation, self.action, missing)
        self.assertEqual(corrected[0].uncertainty, 1.)
        self.assertTrue(any(i.issue_type == "stakeholder_gap" for i in issues))

    def test_aggregate_inconsistency_is_detected(self):
        o = make_prediction(self.situation, "future")[0]
        o = replace(o, impacts=tuple(replace(i, harm=.9, uncertainty=.8) for i in o.impacts))
        corrected, issues, _ = self.checker.process(self.situation, self.action, (o,))
        self.assertEqual(corrected[0].severity, .9)
        self.assertEqual(corrected[0].uncertainty, .8)
        self.assertEqual(len(issues), 2)

    def test_regeneration_is_bounded_and_cannot_bypass_persistent_issue(self):
        outcomes = make_prediction(self.situation, "個人を再識別できる")
        class Counting:
            calls = 0
            def predict(inner, situation, action):
                inner.calls += 1
                return outcomes
        provider = Counting()
        corrected, _, updates = self.checker.process(self.situation, self.action, outcomes, "regenerate", provider)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(corrected[0].uncertainty, 1.)
        self.assertEqual(updates[0]["action"], Response.REGENERATE_PREDICTION.value)

    def test_checker_does_not_treat_agreement_as_proof_of_safety(self):
        s = replace(self.situation, context="全員が合意した")
        outcomes = make_prediction(s, "負担が発生する", harm=.6)
        corrected, issues, _ = self.checker.process(s, self.action, outcomes)
        self.assertTrue(any(i.suggested_action == Response.REEVALUATE for i in issues))
        self.assertEqual(corrected[0].severity, .6)
        self.assertEqual(corrected[0].uncertainty, 1.)

    def test_empty_prediction_stays_unknown(self):
        self.assertEqual(self.checker.inspect(self.situation, self.action, ())[0].suggested_action, Response.ASK_HUMAN)
        self.assertEqual(self.checker.process(self.situation, self.action, ())[0], ())

    def test_detection_metrics_hand_computed(self):
        refs = {"harm": True, "rights": False, "consent": False, "unresolved": False, "severity": .8, "expected_stakeholders": ["user"]}
        tp = quality(refs, make_prediction(self.situation, "future", harm=.8))
        fn = quality(refs, make_prediction(self.situation, "future", harm=.2))
        fp = quality(dict(refs, harm=False), make_prediction(self.situation, "future", harm=.8))
        result = prediction_summary([tp, fn, fp])
        self.assertEqual(result["detection"]["harm"]["precision"], .5)
        self.assertEqual(result["detection"]["harm"]["recall"], .5)
        self.assertEqual(result["detection"]["harm"]["f1"], .5)
        self.assertAlmostEqual(result["severity_mae"], .2)
        self.assertEqual(result["stakeholder_coverage"], 1.)
        self.assertEqual(result["stakeholder_set_precision"], .25)
        self.assertIsNone(prediction_summary([])["severity_mae"])

    def test_uncertainty_bins_and_correlation(self):
        refs = {"harm": False, "rights": False, "consent": False, "unresolved": False, "severity": .02, "expected_stakeholders": ["user"]}
        correct = quality(refs, make_prediction(self.situation, "future", uncertainty=.1))
        wrong = quality(refs, make_prediction(self.situation, "future", harm=.9, uncertainty=.9))
        summary = prediction_summary([correct, wrong])
        self.assertAlmostEqual(summary["uncertainty_error_correlation"], 1.)
        self.assertEqual([b["count"] for b in summary["uncertainty_bins"]], [1, 0, 0, 1])

    def test_all_seven_legacy_failures_are_reproduced_and_traced(self):
        rows = {(r["scenario_id"], r["prediction_condition"]): r for r in self.report["regressions"]}
        for case_id in REGRESSION_CASES:
            case = next(c for c in self.cases if c.inputs.id == case_id)
            original = run_variant(case.inputs, "full_v01")
            before = rows[case_id, "legacy_recorded"]
            after = rows[case_id, "legacy_recorded_checked"]
            self.assertEqual(original.decision.kind.value, before["decision"])
            self.assertFalse(before["acceptable_decision"])
            self.assertTrue(before["prediction_recoverable_decision_error"])
            self.assertEqual(before["single_action_oracle_rescues"], ["a"])
            if case_id in REGRESSION_CASES[:3]:
                self.assertTrue(before["harmful_action"])
                self.assertEqual(after["decision"], "MODIFY")
                self.assertEqual(after["selected_action"], "b")
                self.assertFalse(after["harmful_action"])
            else:
                self.assertTrue(before["over_refusal"])
                self.assertTrue(after["over_refusal"])

    def test_runner_conditions_counts_and_category_denominators(self):
        self.assertEqual(len(self.report["decisions"]), 1500)
        self.assertEqual(len(self.report["actions"]), 2250)
        self.assertEqual(len(self.report["metadata"]["conditions"]), 30)
        for name in self.report["metadata"]["conditions"]:
            groups = self.report["summary"]["by_category"][name]
            self.assertEqual(len(groups), 10)
            self.assertTrue(all(g["scenario_count"] == 5 for g in groups.values()))
        self.assertEqual(self.report["summary"]["by_variant"]["oracle"]["metrics"]["over_refusal_rate"]["denominator"], 36)

    def test_noise_exposes_redundant_constraints_and_coverage_fail_closed(self):
        groups = self.report["summary"]["by_variant"]
        self.assertEqual(groups["noise/rights_omission/high"]["metrics"]["harmful_action_rate"]["numerator"], 0)
        self.assertEqual(groups["noise/harm_underestimation/high"]["metrics"]["harmful_action_rate"]["numerator"], 10)
        self.assertEqual(groups["noise/stakeholder_omission/high"]["metrics"]["ask_human_rate"]["numerator"], 50)
        self.assertEqual(groups["noise/uncertainty_underestimation/high"]["metrics"]["inappropriate_decisiveness_rate"]["numerator"], 11)

    def test_export_json_csv_and_byte_reproducibility(self):
        a = run(self.directory, self.reference_path, sensitivity=False)
        b = run(self.directory, self.reference_path, sensitivity=False)
        self.assertEqual(a, b)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            save(a, output)
            self.assertEqual(json.loads((output / "results.json").read_text(encoding="utf-8")), a)
            with (output / "predictions.csv").open(encoding="utf-8-sig", newline="") as f:
                records = list(csv.DictReader(f))
            self.assertEqual(len(records), 450)
            self.assertIn("consistency_issues", records[0])
            self.assertIn("prediction_quality", records[0])

    def test_original_frozen_inputs_have_not_changed(self):
        published = json.loads((ROOT / "results" / "audit_v01" / "audit.json").read_text(encoding="utf-8"))
        for name, digest in published["input_sha256"].items():
            self.assertEqual(hashlib.sha256((self.directory / name).read_bytes()).hexdigest(), digest)

    def test_command_line_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, str(ROOT / "experiments" / "run_prediction_validation.py"),
                                     "--output", temp, "--skip-sensitivity"], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("300 decisions", result.stdout)
            self.assertTrue((Path(temp) / "comparison.csv").exists())


if __name__ == "__main__":
    unittest.main()
