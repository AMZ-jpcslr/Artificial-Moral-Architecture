"""Paired, deterministic prediction interventions with an unchanged v0.1 judge."""
import argparse
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import sys

from ..agent import MoralAgent
from ..evaluation.benchmark import load_benchmark
from ..evaluation.metrics import score, summarize
from ..evaluation.variants import RecordedAlternatives, RecordedForesight, Usage, VariantResult
from ..models import to_dict
from ..moral_evaluation import MoralPolicy
from .consistency import ConsistencyChecker
from .metrics import quality, prediction_summary
from .providers import FuturePredictor, HeuristicPredictor, OraclePredictor, NoisyOracle, NOISE_TYPES, STRENGTHS, load_references, factual_context

REGRESSION_CASES = ("privacy_05", "safety_05", "long_term_harm_05", "deception_05", "property_05", "fairness_05", "conflicting_interests_05")


class TracedPredictor:
    def __init__(self, provider: FuturePredictor, checker=None):
        self.provider, self.checker = provider, checker
        self.records = {}

    def predict(self, situation, action):
        # Drop other candidates: providers receive only this candidate, the goal,
        # factual situation and registered perspectives, never fixture metadata.
        request = replace(situation, candidates=(action,), context=factual_context(situation.context))
        raw = tuple(self.provider.predict(request, action))
        effective, issues, updates = self.checker.process(request, action, raw) if self.checker else (raw, (), ())
        self.records[action.id] = {"raw": raw, "effective": effective, "issues": issues, "updates": updates}
        return effective


def decide(inputs, provider, checker=None):
    usage = Usage()
    traced = TracedPredictor(provider, checker)
    agent = MoralAgent(foresight=traced, counterfactual=RecordedAlternatives(inputs, usage))
    decision = agent.decide(inputs.situation)
    usage.forecast_calls = usage.stakeholder_analysis_calls = usage.uncertainty_checks = len(decision.assessments)
    trace = tuple({"action_id": a.action.id, "alternative_to": a.alternative_to, "verdict": a.verdict.value,
                   "evaluation": a.evaluation, "outcomes": a.outcomes} for a in decision.assessments)
    return VariantResult(decision, usage, trace), traced.records


class PredictionMap:
    def __init__(self, values):
        self.values = values

    def predict(self, situation, action):
        return self.values[action.id]


def run(directory, reference_path, *, seed=17, noise_type="harm_underestimation", strength="high", sensitivity=True):
    cases = load_benchmark(directory)
    reference = load_references(reference_path, cases)
    conditions = [("oracle", None, None), ("noisy_oracle", noise_type, strength),
                  ("predictor", None, None), ("predictor_checked", None, None),
                  ("legacy_recorded", None, None), ("legacy_recorded_checked", None, None)]
    if sensitivity:
        conditions += [(f"noise/{n}/{s}", n, s) for n in NOISE_TYPES for s in STRENGTHS]
    rows, actions, failure_analysis = [], [], []
    for case in cases:
        refs = reference["annotations"][case.inputs.id]
        oracle = OraclePredictor(refs)
        oracle_result, oracle_records = decide(case.inputs, oracle)
        oracle_row = score(case, "oracle", oracle_result)
        for name, noise, level in conditions:
            provider = oracle if name == "oracle" else (
                NoisyOracle(oracle, noise, level, seed) if noise else
                RecordedForesight(case.inputs, Usage()) if name.startswith("legacy_recorded") else HeuristicPredictor())
            result, traces = decide(case.inputs, provider, ConsistencyChecker() if name.endswith("checked") else None)
            row = score(case, name, result)
            # Predictions are stored once at action level, not duplicated in each trace.
            for trace in row["trace"]:
                trace.pop("outcomes", None)
            row.update(prediction_condition=name, prediction_error_type=noise, noise_strength=level)
            row["prediction_recoverable_decision_error"] = not row["acceptable_decision"] and oracle_row["acceptable_decision"]
            row["single_action_oracle_rescues"] = []
            row["safe_successful_catalog_action_exists"] = bool(case.truth.expected_safe_actions & case.truth.task_success_actions)
            if not row["acceptable_decision"]:
                effective = {aid: trace["effective"] for aid, trace in traces.items()}
                for aid in effective:
                    intervention = dict(effective)
                    intervention[aid] = oracle_records[aid]["effective"]
                    changed, _ = decide(case.inputs, PredictionMap(intervention))
                    if score(case, name, changed)["acceptable_decision"]:
                        row["single_action_oracle_rescues"].append(aid)
                # Stages are evidence-based diagnostics, not claims of unique causality.
                failures = ["prediction_error"] if row["prediction_recoverable_decision_error"] else ["decision_error"]
                if row["single_action_oracle_rescues"]:
                    failures.append("evaluation_error")  # incorrect structured prediction input, not evaluator implementation
                if row["over_refusal"]:
                    failures.append("threshold_gate")  # gate activation does not prove threshold is wrong
                failure_analysis.append({"scenario_id": case.inputs.id, "prediction_condition": name,
                    "stages": failures, "oracle_replacement_recovers": row["prediction_recoverable_decision_error"],
                    "single_action_oracle_rescues": row["single_action_oracle_rescues"],
                    "alternative_error": "no_safe_successful_catalog_action" if not row["safe_successful_catalog_action_exists"] else None,
                    "threshold_error": "not_identified: gate activation is not proof of a faulty threshold",
                    "decision_error": True, "evaluation_error_note": "Oracle input substitution repairs a decision; no evaluator implementation defect is thereby established.", "situation": case.inputs.situation.context,
                    "selected_action": row["selected_action"], "explanation": row["reasoning_summary"]})
            rows.append(row)
            for assessment in result.decision.assessments:
                aid = assessment.action.id
                t = traces[aid]
                actions.append({"scenario_id": case.inputs.id, "scenario_category": case.inputs.category,
                    "action_id": aid, "action_description": assessment.action.description,
                    "prediction_condition": name, "prediction_error_type": noise, "noise_strength": level,
                    "reference": refs[aid], "prediction_quality": quality(refs[aid], t["effective"]),
                    "raw_prediction_quality": quality(refs[aid], t["raw"]),
                    "noise_changed_prediction": noise is not None and t["raw"] != oracle_records[aid]["raw"],
                    "raw_predictions": to_dict(t["raw"]),
                    "effective_predictions": to_dict(t["effective"]) if t["raw"] != t["effective"] else None,
                    "effective_equals_raw": t["raw"] == t["effective"],
                    "consistency_issues": to_dict(t["issues"]), "processing_actions": to_dict(t["updates"]),
                    "moral_evaluation": to_dict(assessment.evaluation), "action_verdict": assessment.verdict.value,
                    "decision": row["decision"], "selected_action": row["selected_action"],
                    "harmful_action": row["harmful_action"], "task_success": row["task_success"], "ask_human": row["ask_human"],
                    "explanation": row["reasoning_summary"]})
    summary = summarize(rows)
    predictions = {}
    for name, _, _ in conditions:
        selected = [a for a in actions if a["prediction_condition"] == name]
        selected_rows = [r for r in rows if r["prediction_condition"] == name]
        bad = sum(not r["acceptable_decision"] for r in selected_rows)
        recovered = sum(r["prediction_recoverable_decision_error"] for r in selected_rows)
        predictions[name] = {
            "raw": prediction_summary([a["raw_prediction_quality"] for a in selected]),
            "effective": prediction_summary([a["prediction_quality"] for a in selected]),
            "consistency_issues_detected": sum(len(a["consistency_issues"]) for a in selected),
            "actions_with_issues": sum(bool(a["consistency_issues"]) for a in selected),
            "noise_changed_actions": sum(a["noise_changed_prediction"] for a in selected),
            "prediction_recoverable_error": {"numerator": recovered, "denominator": bad, "rate": recovered/bad if bad else None},
            "by_category": {category: prediction_summary([a["prediction_quality"] for a in selected if a["scenario_category"] == category])
                            for category in sorted({a["scenario_category"] for a in selected})},
        }
    inputs = [directory / "scenarios.json", directory / "ground_truth.json", reference_path]
    code_paths = sorted(Path(__file__).parent.glob("*.py"))
    return {"metadata": {"dataset": "Synthetic Architecture Validation Set", "version": "0.1.5", "seed": seed,
            "python": platform.python_version(), "policy": to_dict(MoralPolicy()),
            "input_sha256": {str(p.name): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
            "code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths},
            "conditions": [n for n, _, _ in conditions], "reference_provenance": reference["provenance"],
            "causality_note": "Oracle substitution is a paired synthetic intervention; recoverability is not unique real-world causation."},
            "summary": summary, "prediction_summary": predictions, "decisions": rows, "actions": actions,
            "failure_analysis": failure_analysis,
            "regressions": [r for r in rows if r["scenario_id"] in REGRESSION_CASES and not r["agent_variant"].startswith("noise/")]}


def comparison_rows(report):
    records = []
    for name in report["metadata"]["conditions"]:
        metrics = report["summary"]["by_variant"][name]["metrics"]
        pred = report["prediction_summary"][name]
        row = {"prediction_condition": name}
        row.update({k: v["rate"] for k, v in metrics.items()})
        row.update(harm_f1=pred["effective"]["detection"]["harm"]["f1"],
                   rights_f1=pred["effective"]["detection"]["rights"]["f1"], consent_f1=pred["effective"]["detection"]["consent"]["f1"],
                   severity_mae=pred["effective"]["severity_mae"], stakeholder_coverage=pred["effective"]["stakeholder_coverage"],
                   consistency_issues=pred["consistency_issues_detected"], noise_changed_actions=pred["noise_changed_actions"])
        records.append(row)
    return records


def csv_file(path, records):
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        for row in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list, tuple)) else v for k, v in row.items()})


def save(report, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compact = {k: v for k, v in report.items() if k not in ("decisions", "actions")}
    (output / "summary.json").write_text(json.dumps(compact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    csv_file(output / "decisions.csv", [{k: v for k, v in r.items() if k not in ("trace", "ground_truth_summary")} for r in report["decisions"]])
    csv_file(output / "predictions.csv", [{k: v for k, v in a.items() if k not in ("raw_predictions", "effective_predictions")} for a in report["actions"]])
    csv_file(output / "comparison.csv", comparison_rows(report))
    csv_file(output / "noise_sensitivity.csv", [r for r in comparison_rows(report) if r["prediction_condition"].startswith("noise/")])


def print_comparison(report):
    print("Condition                                      Task   Harm   OverRef SafeAlt Ask    HarmF1 Issues")
    keys = ("task_success_rate", "harmful_action_rate", "over_refusal_rate", "safe_alternative_selection_rate", "ask_human_rate", "harm_f1")
    for row in comparison_rows(report):
        cells = ["  n/a " if row[k] is None else f"{row[k]*100:6.1f}" for k in keys]
        print(f"{row['prediction_condition']:46}" + " ".join(cells) + f" {row['consistency_issues']:5}")


def main(argv=None):
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=root / "benchmarks" / "v01")
    parser.add_argument("--reference", type=Path, default=root / "benchmarks" / "v015" / "oracle.json")
    parser.add_argument("--output", type=Path, default=root / "results" / "v015")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--noise-type", choices=NOISE_TYPES, default="harm_underestimation")
    parser.add_argument("--strength", choices=tuple(STRENGTHS), default="high")
    parser.add_argument("--skip-sensitivity", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = run(args.benchmark, args.reference, seed=args.seed, noise_type=args.noise_type, strength=args.strength, sensitivity=not args.skip_sensitivity)
    save(report, args.output)
    print_comparison(report)
    print(f"Saved {len(report['decisions'])} decisions / {len(report['actions'])} action predictions to {args.output}")


if __name__ == "__main__":
    main()
