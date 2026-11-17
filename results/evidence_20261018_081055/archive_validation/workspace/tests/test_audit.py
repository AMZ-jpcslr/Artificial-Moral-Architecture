"""The audit must preserve the experiment and display every case and future."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from audit_benchmark import HARM_CASES, REFUSAL_CASES, casebook, diagnose_failure, run_audit


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / "benchmarks" / "v01"
        cls.before = {p.name: p.read_bytes() for p in cls.directory.glob("*.json")}
        cls.report, cls.cases, cls.results = run_audit(cls.directory)
        cls.notes = json.loads((ROOT / "docs" / "audit_notes.json").read_text(encoding="utf-8"))

    def test_original_benchmark_and_published_full_results_are_preserved(self):
        self.assertEqual(self.before, {p.name: p.read_bytes() for p in self.directory.glob("*.json")})
        for name, digest in self.report["input_sha256"].items():
            self.assertEqual(digest, hashlib.sha256(self.before[name]).hexdigest())
        published = json.loads((ROOT / "results" / "v01" / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(self.report["full_summary"], published["summary"]["by_variant"]["full_v01"])
        for row in published["records"]:
            if row["agent_variant"] == "full_v01":
                decision = self.results[row["scenario_id"]].decision
                self.assertEqual(decision.kind.value, row["decision"])
                self.assertEqual(decision.selected_action.id if decision.selected_action else None, row["selected_action"])

    def test_expected_failures_and_structural_coverage(self):
        failures = self.report["failures"]
        self.assertEqual({f["scenario_id"] for f in failures if f["failure"] == "harmful_action"}, set(HARM_CASES))
        self.assertEqual({f["scenario_id"] for f in failures if f["failure"] == "over_refusal"}, set(REFUSAL_CASES))
        self.assertTrue(all(not f["missing_registered_stakeholders"] for f in failures))
        self.assertTrue(self.report["stats"]["all_registered_stakeholders_present"])
        self.assertEqual(self.report["stats"]["action_count"], 75)
        self.assertEqual(self.report["stats"]["forecast_outcome_count"], 150)

    def test_controlled_forecast_replacements_change_each_failure(self):
        for failure in self.report["failures"]:
            changed = failure["probes"]["synthetic_future_replacement"]
            if failure["failure"] == "harmful_action":
                self.assertEqual((changed["decision"], changed["selected_action"]), ("MODIFY", "b"))
                self.assertTrue(changed["safe_alternative_selected"])
                self.assertEqual(failure["probes"]["raise_existing_b_utility_only"]["selected_action"], "b")
            else:
                self.assertEqual((changed["decision"], changed["selected_action"]), ("ALLOW", "a"))
                self.assertFalse(changed["over_refusal"])
            self.assertEqual(failure["probes"]["original"], failure["probes"]["add_rule_tags_only"])

    def test_one_relaxed_threshold_is_insufficient_with_multiple_triggers(self):
        for failure in self.report["failures"]:
            if len(failure["review_triggers"]) > 1:
                for name, result in failure["probes"].items():
                    if name.startswith("relax_only_"):
                        self.assertEqual(result["decision"], "ASK_HUMAN")
                self.assertEqual(failure["probes"]["relax_all_triggering_thresholds_to_0.99"]["decision"], "ALLOW")

    def test_sensitivity_exposes_tradeoffs_and_inert_probability_and_time_fields(self):
        policies = self.report["policy_sensitivity"]
        self.assertEqual(policies["original"]["summary"], self.report["full_summary"])
        self.assertEqual(policies["review_limits_relaxed"]["summary"]["metrics"]["harmful_action_rate"]["numerator"], 7)
        self.assertEqual(policies["uncertainty_limit_0.95"]["summary"]["metrics"]["inappropriate_decisiveness_rate"]["numerator"], 11)
        self.assertEqual(self.report["probability_magnitude_probe_changed_decisions"], {"1e-06": 0, "1.0": 0})
        self.assertEqual(self.report["all_horizons_immediate_changed_decisions"], 0)

    def test_numerically_identical_evidence_has_conflicting_labels(self):
        group = self.report["stats"]["largest_numeric_group"]
        self.assertEqual(group["label_counts"], {"safe": 31, "unsafe": 3})
        self.assertEqual({m["scenario_id"] for m in group["members"] if m["label"] == "unsafe"}, set(HARM_CASES))

    def test_casebook_contains_every_ground_truth_and_every_forecast(self):
        rendered = casebook(self.cases, self.results, self.notes)
        self.assertEqual(rendered.count("### Ground Truth（全フィールド）"), 50)
        self.assertEqual(rendered.count("#### 行動 "), 75)
        self.assertEqual(rendered.count("**未来予測 "), 150)
        for case in self.cases:
            section = rendered.split(f'<a id="{case.inputs.id}"></a>', 1)[1].split('<a id="', 1)[0]
            for field in vars(case.truth):
                self.assertIn(f"| {field} |", section)
            for record in case.inputs.evidence.values():
                self.assertIn(record.action.description, section)
                for outcome in (record.observation, *record.forecasts):
                    self.assertIn(outcome.description, section)
                    for impact in outcome.impacts:
                        self.assertIn(impact.explanation, section)
            self.assertIn(self.notes[case.inputs.id], section)

    def test_missing_notes_or_unrecognized_failures_are_not_silently_classified(self):
        with self.assertRaises(ValueError):
            casebook(self.cases, self.results, {})
        case = next(c for c in self.cases if c.inputs.id == "privacy_05")
        altered = replace(case, inputs=replace(case.inputs, id="new_case"))
        with self.assertRaisesRegex(ValueError, "manual diagnosis"):
            diagnose_failure(altered, self.results["privacy_05"], {"harmful_action": True})

    def test_cli_exports_full_data_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            command = [sys.executable, str(ROOT / "experiments" / "audit_benchmark.py"),
                       "--output", str(output / "data"), "--casebook", str(output / "cases.md")]
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, encoding="utf-8")
            first = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, encoding="utf-8")
            self.assertEqual(first, {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()})
            raw = json.loads((output / "data" / "all_cases.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["scenarios"], json.loads(self.before["scenarios.json"]))
            self.assertEqual(raw["ground_truth"], json.loads(self.before["ground_truth.json"]))
            self.assertEqual(len(raw["full_decisions"]), 50)


if __name__ == "__main__":
    unittest.main()
