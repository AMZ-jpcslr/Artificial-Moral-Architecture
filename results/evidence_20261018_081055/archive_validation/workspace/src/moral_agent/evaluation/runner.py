"""Deterministic comparison and auditable JSON/CSV reports (no action execution)."""

import csv
import hashlib
import json
from pathlib import Path
import platform

from ..models import to_dict
from ..moral_evaluation import MoralPolicy
from .benchmark import load_benchmark
from .metrics import hypothesis_results, native_comparisons, score, summarize
from .variants import VARIANTS, run_variant


def _digest(paths, root):
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def paired_changes(rows):
    """Identify per-case regressions/improvements; never hide negative findings."""
    reference = {r["scenario_id"]: r for r in rows if r["agent_variant"] == "full_v01"}
    changes = []
    flags = ("task_success", "safe_task_success", "harmful_action", "rights_violation", "consent_violation",
             "over_refusal", "safe_alternative_selected", "inappropriate_decisiveness", "acceptable_decision")
    for row in rows:
        base = reference.get(row["scenario_id"])
        if row["agent_variant"] == "full_v01" or base is None:
            continue
        different = {f: {"full_v01": base[f], "variant": row[f]} for f in flags if base[f] != row[f]}
        if different:
            changes.append({"agent_variant": row["agent_variant"], "scenario_id": row["scenario_id"],
                            "scenario_category": row["scenario_category"], "differences": different})
    return changes


def run_benchmark(directory: Path, variants=VARIANTS) -> dict:
    variants = tuple(variants)
    if not variants or len(set(variants)) != len(variants) or set(variants) - set(VARIANTS):
        raise ValueError("variants must be a nonempty, unique list of known variants")
    cases = load_benchmark(directory)
    rows = [score(case, variant, run_variant(case.inputs, variant)) for variant in variants for case in cases]
    summary = summarize(rows)
    source = Path(__file__).resolve().parents[1]
    data_files = [directory / "scenarios.json", directory / "ground_truth.json"]
    manifest = directory / "manifest.json"
    version = "custom-unversioned"
    if manifest.exists():
        version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
        data_files.append(manifest)
    metadata = {
        "benchmark_version": version, "scenario_count": len(cases), "variants": list(variants),
        "category_counts": {c: sum(case.inputs.category == c for case in cases) for c in sorted({case.inputs.category for case in cases})},
        "benchmark_sha256": _digest(data_files, directory),
        "source_sha256": _digest(source.rglob("*.py"), source), "python_version": platform.python_version(),
        "policy": to_dict(MoralPolicy()), "randomness": "none", "execution": "selection-only; no executor called",
        "provenance": "Hand-authored synthetic evidence and separate hand-authored labels; not independently adjudicated.",
        "full_v01_backend": "Recorded forecasts and alternatives through existing Protocol interfaces; unchanged v0.1 policy.",
        "native_v01_backend": "Original MoralAgent defaults, without evaluation evidence adapters.",
        "unseen_scope": "Disjoint from five development demos; not a blinded holdout and not a learned model generalization test.",
    }
    return {"metadata": metadata, "summary": summary, "hypotheses": hypothesis_results(summary),
            "native_baseline_comparisons": native_comparisons(summary),
            "paired_changes": paired_changes(rows), "records": rows}


def _json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _csv(path, rows):
    if not rows:
        raise ValueError("cannot export a table with no rows")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def flatten_summary(variant, category, summary):
    row = {"agent_variant": variant, "scenario_category": category, "scenario_count": summary["scenario_count"]}
    for name, value in summary["metrics"].items():
        row[name] = value["rate"]
        row[name + "_numerator"] = value["numerator"]
        row[name + "_denominator"] = value["denominator"]
    for decision, values in summary["decision_distribution"].items():
        row[f"{decision}_count"] = values["count"]
        row[f"{decision}_rate"] = values["rate"]
    return row


def save_results(report: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    _json(output / "results.json", report)
    _json(output / "summary.json", {k: v for k, v in report.items() if k != "records"})
    _csv(output / "results.csv", [{k: v for k, v in row.items() if k != "trace"} for row in report["records"]])
    _csv(output / "summary.csv", [flatten_summary(v, "ALL", s) for v, s in report["summary"]["by_variant"].items()])
    _csv(output / "categories.csv", [flatten_summary(v, c, s) for v, categories in report["summary"]["by_category"].items() for c, s in categories.items()])


def comparison_table(report: dict) -> str:
    columns = (
        ("Task", "task_success_rate"), ("SafeTask", "safe_task_success_rate"),
        ("Harm", "harmful_action_rate"), ("Rights", "rights_violation_rate"),
        ("Consent", "consent_violation_rate"), ("OverRef", "over_refusal_rate"),
        ("SafeAlt", "safe_alternative_selection_rate"), ("Ask", "ask_human_rate"),
    )
    lines = [f"{'Agent':24}" + "".join(f"{label:>9}" for label, _ in columns)]
    for variant in report["metadata"]["variants"]:
        metrics = report["summary"]["by_variant"][variant]["metrics"]
        values = [f"{metrics[key]['rate']:.1%}" if metrics[key]["rate"] is not None else "N/A" for _, key in columns]
        lines.append(f"{variant:24}" + "".join(f"{value:>9}" for value in values))
    lines.append("Rates use documented eligibility denominators; see summary.json for counts.")
    lines.append("full_v01 uses recorded evidence; native_v01 uses the original default backends.")
    return "\n".join(lines)
