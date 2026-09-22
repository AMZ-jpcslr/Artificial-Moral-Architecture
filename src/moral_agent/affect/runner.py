"""Offline paired affect evaluation, plus separate within-episode persistence probes."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import sys

from ..evaluation.benchmark import load_benchmark
from ..evaluation.variants import RecordedAlternatives, RecordedForesight, Usage
from ..models import to_dict
from ..prediction_validation.consistency import ConsistencyChecker
from ..prediction_validation.providers import OraclePredictor, NoisyOracle, HeuristicPredictor, load_references
from ..prediction_validation.metrics import quality, prediction_summary
from ..prediction_validation.runner import csv_file, REGRESSION_CASES
from .agent import AffectAgent
from .appraisal import AffectConfig
from .metrics import paired_score, summarize
from .storage import compact_evidence

NOISE = {"noisy-harm-underestimate": "harm_underestimation", "noisy-uncertainty-underestimate": "uncertainty_underestimation",
         "noisy-stakeholder-omission": "stakeholder_omission", "noisy-reversibility-error": "reversibility_error",
         "noisy-rights-omission": "rights_omission", "noisy-consent-omission": "consent_omission"}
PREDICTIONS = ("oracle", *NOISE, "predictor", "predictor-checked", "legacy", "legacy-checked")
VARIANTS = ("no_affect", "affect_only", "full_v02", "no_concern", "no_empathy", "no_guilt", "no_persistence", "strong_affect", "always_deliberate", "evidence_gate")


def configuration(variant):
    changes = {"no_affect": {"enabled": False}, "affect_only": {"behavior_enabled": False}, "full_v02": {},
               "no_concern": {"concern_enabled": False}, "no_empathy": {"empathy_enabled": False},
               "no_guilt": {"guilt_enabled": False}, "no_persistence": {"persistence": False},
               "strong_affect": {"gain": 3.}, "always_deliberate": {"enabled": False}, "evidence_gate": {"enabled": False}}
    if variant not in changes:
        raise ValueError("unknown affect variant")
    return replace(AffectConfig(), **changes[variant])


def build_agent(case, refs, prediction, variant, seed, strength):
    oracle = OraclePredictor(refs)
    provider = oracle if prediction == "oracle" else NoisyOracle(oracle, NOISE[prediction], strength, seed) if prediction in NOISE else (
        HeuristicPredictor() if prediction.startswith("predictor") else RecordedForesight(case.inputs, Usage()))
    checker = ConsistencyChecker() if prediction.endswith("checked") else None
    return AffectAgent(provider, RecordedAlternatives(case.inputs, Usage()), configuration(variant),
                       checker=checker, always_deliberate=variant == "always_deliberate", evidence_gate=variant == "evidence_gate")


def evaluate(directory, reference_path, *, predictions=PREDICTIONS, variants=VARIANTS, seed=17, strength="high", episodes=True):
    if not predictions or not variants or len(set(predictions)) != len(predictions) or len(set(variants)) != len(variants):
        raise ValueError("conditions must be nonempty and unique")
    if set(predictions)-set(PREDICTIONS) or set(variants)-set(VARIANTS):
        raise ValueError("unknown condition")
    cases = load_benchmark(directory)
    references = load_references(reference_path, cases)
    rows, episode_rows = [], []
    groups, prediction_scores = {}, {}
    for prediction in predictions:
        for variant in variants:
            group = []
            qualities = []
            for case in cases:
                refs = references["annotations"][case.inputs.id]
                agent = build_agent(case, refs, prediction, variant, seed, strength)
                agent.reset_episode()  # no state crosses a scenario boundary
                result = agent.step(case.inputs.situation)
                row = paired_score(case, variant, prediction, result)
                row["prediction_quality"] = {a.action.id: quality(refs[a.action.id], a.outcomes) for a in result.decision.assessments}
                qualities.extend(row["prediction_quality"].values())
                group.append(row)
            rows.extend(group)
            key = f"{prediction}/{variant}"
            groups[key] = summarize(group)
            prediction_scores[key] = prediction_summary(qualities)
    # Deliberation-only repeated-evidence probes. No fabricated actions/outcomes and
    # no claim that these are independent trials or real environmental episodes.
    if episodes:
        for case in cases:
            if case.inputs.id not in REGRESSION_CASES:
                continue
            refs = references["annotations"][case.inputs.id]
            for variant in variants:
                agent = build_agent(case, refs, "legacy", variant, seed, strength)
                agent.reset_episode()
                for step in range(1, 4):
                    result = agent.step(case.inputs.situation)
                    episode_rows.append(paired_score(case, variant, "legacy", result, step))
    from .probes import run_probes
    probes = run_probes(variants)
    inputs = [directory / "scenarios.json", directory / "ground_truth.json", reference_path]
    core = sorted((Path(__file__).resolve().parents[1]).rglob("*.py"))
    categories = sorted({c.inputs.category for c in cases})
    report = {"metadata": {"version": "0.2", "dataset": "Synthetic Architecture Validation Set", "seed": seed,
        "noise_strength": strength, "python": platform.python_version(), "predictions": list(predictions), "variants": list(variants),
        "scenario_count": len(cases), "primary_decision_count": len(rows), "episode_probe_decision_count": len(episode_rows), "mechanism_probe_decision_count": len(probes),
        "reset_policy": "new state per primary scenario; persistent only inside explicit episode probes",
        "episode_probe_note": "Three deliberation steps with identical evidence; not independent samples or observed real outcomes.",
        "configurations": {v: to_dict(configuration(v)) for v in variants},
        "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "code_sha256": {str(p.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(p.read_bytes()).hexdigest() for p in core}},
        "summary": groups, "prediction_summary": prediction_scores,
        "by_category": {key: {category: summarize([r for r in rows if f"{r['prediction_condition']}/{r['condition']}" == key and r["scenario_category"] == category]) for category in categories} for key in groups},
        "episode_summary": {f"{v}/step_{step}": summarize([r for r in episode_rows if r["condition"] == v and r["episode_step"] == step]) for v in variants for step in range(1,4)} if episodes else {},
        "records": rows, "episode_records": episode_rows,
        "mechanism_probes": to_dict(probes),
        "regressions": [{k: r[k] for k in ("scenario_id", "condition", "prediction_condition", "selected_action", "decision", "harmful_action", "over_refusal", "affect_changed_action", "additional_reasoning_count")}
                        for r in rows if r["scenario_id"] in REGRESSION_CASES]}
    return compact_evidence(report)


def comparison_rows(report):
    result = []
    for key, group in report["summary"].items():
        prediction, variant = key.split("/")
        row = {"prediction_condition": prediction, "condition": variant}
        row.update({name: metric["rate"] for name, metric in group["metrics"].items()})
        row.update({name: metric["rate"] for name, metric in group["affect_metrics"].items()})
        row.update(harm_f1=report["prediction_summary"][key]["detection"]["harm"]["f1"],
                   average_predictions=group["average_predictions"], average_alternative_searches=group["average_alternative_searches"],
                   average_stakeholder_checks=group["average_stakeholder_checks"], additional_reasoning_cost=group["mean_additional_reasoning"])
        result.append(row)
    return result


def save(report, output):
    output.mkdir(parents=True, exist_ok=True)
    # Full traces stay in JSON; compact serialization avoids large whitespace-only artifacts.
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False)+"\n", encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in ("records", "episode_records")}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    csv_file(output / "comparison.csv", comparison_rows(report))
    exclude = {"causal_trace", "prediction_quality", "interventions", "reasoning_summary", "explanation"}
    csv_file(output / "decisions.csv", [{k: v for k, v in r.items() if k not in exclude} | {
        "interventions": [{k: v for k, v in intervention.items() if k != "additional_outcomes"} for intervention in r["interventions"]],
        "explanation": r["explanation"]} for r in report["records"]])
    csv_file(output / "episodes.csv", [{k: r[k] for k in ("scenario_id", "condition", "episode_step", "affect_before", "affect_after", "decision", "selected_action", "additional_reasoning_count", "over_refusal")} for r in report["episode_records"]])
    csv_file(output / "regressions.csv", report["regressions"])


def print_summary(report):
    print("Prediction                    Variant            Task  Harm  OverRef ReviewRecall Recovery Interv ExtraOps")
    for r in comparison_rows(report):
        keys = ("task_success_rate", "harmful_action_rate", "over_refusal_rate", "human_escalation_recall", "safe_recovery_rate", "intervention_rate")
        rates = " ".join("   n/a" if r[k] is None else f"{100*r[k]:6.1f}" for k in keys)
        print(f"{r['prediction_condition']:29} {r['condition']:18} {rates} {r['additional_reasoning_cost']:7.2f}")


def main(argv=None):
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction", choices=PREDICTIONS, nargs="+", default=list(PREDICTIONS))
    parser.add_argument("--variants", choices=VARIANTS, nargs="+", default=list(VARIANTS))
    parser.add_argument("--benchmark", type=Path, default=root / "benchmarks" / "v01")
    parser.add_argument("--reference", type=Path, default=root / "benchmarks" / "v015" / "oracle.json")
    parser.add_argument("--output", type=Path, default=root / "results" / "v02")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--strength", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--skip-episodes", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = evaluate(args.benchmark, args.reference, predictions=tuple(args.prediction), variants=tuple(args.variants),
                      seed=args.seed, strength=args.strength, episodes=not args.skip_episodes)
    save(report, args.output)
    print_summary(report)
    print(f"Saved {len(report['records'])} primary decisions + {len(report['episode_records'])} episode probe decisions to {args.output}")


if __name__ == "__main__":
    main()
