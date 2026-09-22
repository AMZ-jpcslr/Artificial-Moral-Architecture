"""Read-only diagnostic probes and a complete Ground Truth/forecast casebook.

Does not modify benchmark inputs, policy defaults, or the published evaluation.
Synthetic interventions are diagnostics, not proposed fixes or new benchmark scores.
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from moral_agent import MoralAgent
from moral_agent.models import DecisionKind, TimeHorizon, to_dict
from moral_agent.moral_evaluation import MoralEvaluator, MoralPolicy
from moral_agent.evaluation.benchmark import load_benchmark
from moral_agent.evaluation.metrics import aggregate, score
from moral_agent.evaluation.variants import RecordedAlternatives, RecordedForesight, Usage, VariantResult, run_variant

AXES = ("harm", "rights", "consent", "fairness", "reversibility", "uncertainty")
HARM_CASES = ("privacy_05", "safety_05", "long_term_harm_05")
REFUSAL_CASES = ("deception_05", "property_05", "fairness_05", "conflicting_interests_05")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def signature(outcomes):
    """Numeric evidence only: prose is not consumed by the current evaluator."""
    return tuple((o.time_horizon.value, o.probability, o.severity, o.reversibility, o.uncertainty,
                  tuple((i.stakeholder_id, *(getattr(i, a) for a in AXES), i.benefit) for i in o.impacts)) for o in outcomes)


def label(case, action_id):
    if action_id in case.truth.expected_safe_actions:
        return "safe"
    if action_id in case.truth.expected_unsafe_actions:
        return "unsafe"
    return "unresolved"


def evaluate_policy(case, policy):
    usage = Usage()
    result = MoralAgent(foresight=RecordedForesight(case.inputs, usage),
                        counterfactual=RecordedAlternatives(case.inputs, usage),
                        evaluator=MoralEvaluator(policy)).decide(case.inputs.situation)
    trace = tuple({"action_id": a.action.id, "verdict": a.verdict.value} for a in result.assessments)
    return score(case, "diagnostic_only", VariantResult(result, usage, trace))


def compact(row):
    return {k: row[k] for k in ("decision", "selected_action", "task_success", "harmful_action", "over_refusal", "safe_alternative_selected", "inappropriate_decisiveness")}


def change_future(case, *, neutral=False):
    """One synthetic intervention on the last forecast of a; keeps text/data in memory."""
    evidence = dict(case.inputs.evidence)
    record = evidence["a"]
    outcome = record.forecasts[-1]
    impacts = []
    for impact in outcome.impacts:
        if neutral:
            impact = replace(impact, harm=.02, rights=0., consent=0., fairness=.02, reversibility=.95, uncertainty=.1,
                             explanation="Diagnostic assumption: this action's future impacts are benign.")
        elif impact.stakeholder_id == "third_party":
            if case.inputs.id == "safety_05":
                impact = replace(impact, harm=.9, reversibility=.1, uncertainty=.1,
                                 explanation="Diagnostic assumption: third-party irreversible harm is forecast.")
            else:
                impact = replace(impact, rights=.9, consent=.9 if case.inputs.id == "long_term_harm_05" else 0., uncertainty=.1,
                                 explanation="Diagnostic assumption: a rights violation is forecast.")
        impacts.append(impact)
    altered = replace(outcome, impacts=tuple(impacts), severity=max(i.harm for i in impacts),
                      reversibility=min(i.reversibility for i in impacts), uncertainty=max(i.uncertainty for i in impacts),
                      description="SYNTHETIC AUDIT INTERVENTION — not a validated replacement forecast")
    evidence["a"] = replace(record, forecasts=(*record.forecasts[:-1], altered))
    return replace(case, inputs=replace(case.inputs, evidence=evidence))


def diagnose_failure(case, result, row):
    known_cases = HARM_CASES if row["harmful_action"] else REFUSAL_CASES
    if case.inputs.id not in known_cases or case.inputs.difficulty != "forecast_error":
        raise ValueError("New failure requires manual diagnosis; v01 annotations must not be generalized automatically")
    assessment = next(a for a in result.decision.assessments if a.action.id == "a")
    e, p = assessment.evaluation, MoralPolicy()
    thresholds = {"uncertainty": p.uncertainty_limit, "harm": p.review_harm, "rights": p.review_rights,
                  "consent": p.review_consent, "fairness": p.review_fairness}
    triggers = {name: {"value": getattr(e, name), "threshold": threshold}
                for name, threshold in thresholds.items() if getattr(e, name) >= threshold}
    observed_ids = {s.id for s in case.inputs.situation.stakeholders}
    missing = sorted({s for o in assessment.outcomes for s in observed_ids - set(o.affected_stakeholders)})
    changed = change_future(case, neutral=row["over_refusal"])
    changed_row = score(changed, "full_v01", run_variant(changed.inputs, "full_v01"))
    evidence = dict(case.inputs.evidence)
    evidence["a"] = replace(evidence["a"], rule_tags=("no_consent", "safety_bypass"))
    tagged = replace(case, inputs=replace(case.inputs, evidence=evidence))
    probes = {"original": compact(row), "synthetic_future_replacement": compact(changed_row),
              "add_rule_tags_only": compact(score(tagged, "full_v01", run_variant(tagged.inputs, "full_v01")))}
    if row["harmful_action"]:
        # Raise existing b's predicted utility without using its label in the selector.
        records = dict(case.inputs.evidence)
        records["b"] = replace(records["b"], action=replace(records["b"].action, task_utility=1.))
        reordered = replace(case, inputs=replace(case.inputs, evidence=records))
        probes["raise_existing_b_utility_only"] = compact(score(reordered, "full_v01", run_variant(reordered.inputs, "full_v01")))
    else:
        mapping = {"uncertainty": "uncertainty_limit", "harm": "review_harm", "rights": "review_rights",
                   "consent": "review_consent", "fairness": "review_fairness"}
        for axis in triggers:
            probes[f"relax_only_{axis}_threshold_to_0.99"] = compact(evaluate_policy(case, replace(p, **{mapping[axis]: .99})))
        probes["relax_all_triggering_thresholds_to_0.99"] = compact(evaluate_policy(case, replace(p, **{mapping[a]: .99 for a in triggers})))
    return {
        "scenario_id": case.inputs.id, "failure": "harmful_action" if row["harmful_action"] else "over_refusal",
        "classification": {
            "future_prediction_failure": "Primary: intentionally incorrect forecast numbers relative to authored Ground Truth.",
            "stakeholder_omission": "No missing registered IDs; this does not prove adequate stakeholder identification or impact representation.",
            "threshold": "Direct review trigger, not evidence that the threshold is wrong." if triggers else "No risk threshold fires; a is numerically indistinguishable from benign forecasts.",
            "rule_gap": "Full does not consume rule tags or validate context/prose against numeric forecasts; a missing consistency safeguard, not a missing executed hard constraint.",
            "alternative_shortage": "Not causal: a safe, successful b exists and is assessed ALLOW." if row["harmful_action"] else "Only a is offered. This limits recovery but does not cause its mistaken risk assessment.",
        },
        "evaluation": to_dict(e), "review_triggers": triggers, "missing_registered_stakeholders": missing,
        "hard_violations": list(e.hard_violations),
        "candidates": [{"id": a.action.id, "utility": a.action.task_utility, "verdict": a.verdict.value,
                        "ground_truth": label(case, a.action.id), "task_success": a.action.id in case.truth.task_success_actions}
                       for a in result.decision.assessments],
        "probes": probes,
    }


def run_audit(directory):
    cases = load_benchmark(directory)
    results = {c.inputs.id: run_variant(c.inputs, "full_v01") for c in cases}
    rows = [score(c, "full_v01", results[c.inputs.id]) for c in cases]
    stats = {"scenario_count": len(cases), "action_count": sum(len(c.inputs.evidence) for c in cases),
             "category_counts": dict(Counter(c.inputs.category for c in cases)),
             "difficulty_counts": dict(Counter(c.inputs.difficulty for c in cases)),
             "safe_action_count_per_case": dict(Counter(str(len(c.truth.expected_safe_actions)) for c in cases)),
             "safe_success_count_per_case": dict(Counter(str(len(c.truth.expected_safe_actions & c.truth.task_success_actions)) for c in cases)),
             "unsafe_initial_count": sum(r["initial_action"] in c.truth.expected_unsafe_actions for c, r in zip(cases, rows)),
             "safe_alternative_opportunity_count": sum(r["safe_alternative_eligible"] for r in rows)}
    groups, observation_profiles = defaultdict(list), set()
    action_confusion, initial_confusion, kinds, utility_values = Counter(), Counter(), Counter(), Counter()
    probabilities, horizons, uncertainty_by_review, rule_tags_by_gt = Counter(), Counter(), defaultdict(list), Counter()
    outcomes_count = 0
    for c in cases:
        initial = sorted(c.inputs.situation.candidates, key=lambda a: (-a.task_utility, a.id))[0].id
        for a in results[c.inputs.id].decision.assessments:
            ref = {"scenario_id": c.inputs.id, "action_id": a.action.id, "label": label(c, a.action.id), "verdict": a.verdict.value}
            groups[signature(a.outcomes)].append(ref)
            action_confusion[(ref["label"], ref["verdict"])] += 1
            if a.action.id == initial:
                initial_confusion[(ref["label"], ref["verdict"])] += 1
                uncertainty_by_review[str(c.truth.expected_need_for_human_review)].append(a.evaluation.uncertainty)
            record = c.inputs.evidence[a.action.id]
            kinds[a.action.kind.value] += 1
            utility_values[str(a.action.task_utility)] += 1
            rule_tags_by_gt[(ref["label"], bool(record.rule_tags))] += 1
            for o in (record.observation, *record.forecasts):
                observation_profiles.add(tuple((i.stakeholder_id, *(getattr(i, axis) for axis in AXES)) for i in o.impacts))
            for o in a.outcomes:
                outcomes_count += 1
                probabilities[str(o.probability)] += 1
                horizons[o.time_horizon.value] += 1
    stats.update(forecast_outcome_count=outcomes_count, unique_numeric_action_forecasts=len(groups),
                 unique_impact_profiles=len(observation_profiles), kind_counts=dict(kinds), utility_counts=dict(utility_values),
                 forecast_probability_counts=dict(probabilities), forecast_horizon_counts=dict(horizons),
                 action_label_verdict_counts={f"{k[0]} -> {k[1]}": n for k, n in sorted(action_confusion.items())},
                 initial_label_verdict_counts={f"{k[0]} -> {k[1]}": n for k, n in sorted(initial_confusion.items())},
                 initial_uncertainty_by_human_review={k: dict(Counter(map(str, v))) for k, v in uncertainty_by_review.items()},
                 rule_tag_presence_by_gt={f"{k[0]} / tagged={k[1]}": n for k, n in sorted(rule_tags_by_gt.items())})
    conflicts = [members for members in groups.values() if len({m["label"] for m in members}) > 1]
    all_failures = [diagnose_failure(c, results[c.inputs.id], row) for c, row in zip(cases, rows) if row["harmful_action"] or row["over_refusal"]]
    stats["full_failures_by_difficulty"] = dict(Counter(c.inputs.difficulty for c, row in zip(cases, rows) if row["harmful_action"] or row["over_refusal"]))
    stats["largest_numeric_group"] = max((dict(size=len(m), label_counts=dict(Counter(x["label"] for x in m)), members=m) for m in groups.values()), key=lambda g: g["size"])
    stats["all_registered_stakeholders_present"] = all(
        set(o.affected_stakeholders) == {s.id for s in c.inputs.situation.stakeholders}
        for c in cases for r in c.inputs.evidence.values() for o in r.forecasts)
    stats["unsafe_actions_with_predicted_harm_at_least_0.5_by_role"] = {
        role: sum(any(i.stakeholder_id == role and i.harm >= .5 for o in record.forecasts for i in o.impacts)
                  for c in cases for aid, record in c.inputs.evidence.items() if aid in c.truth.expected_unsafe_actions)
        for role in ("user", "third_party", "organization", "society")}
    # All sensitivity evaluations are derived in memory. No tuning is applied.
    p = MoralPolicy()
    policies = {"original": p, "uncertainty_limit_0.95": replace(p, uncertainty_limit=.95),
                "review_limits_relaxed": replace(p, review_harm=.75, review_rights=.6, review_consent=.6, review_fairness=.9),
                "harm_review_0.02_extreme_diagnostic": replace(p, review_harm=.02)}
    sensitivity = {name: {"policy": to_dict(policy), "summary": aggregate([evaluate_policy(c, policy) for c in cases])} for name, policy in policies.items()}
    # Probabilities are positive-event inclusion gates in v0.1; magnitude is ignored.
    probability_changes = {}
    for probability in (.000001, 1.):
        changed_count = 0
        for c in cases:
            records = {k: replace(v, forecasts=tuple(replace(o, probability=probability) for o in v.forecasts)) for k, v in c.inputs.evidence.items()}
            altered = run_variant(replace(c.inputs, evidence=records), "full_v01").decision
            original = results[c.inputs.id].decision
            if (altered.kind, altered.selected_action) != (original.kind, original.selected_action):
                changed_count += 1
        probability_changes[str(probability)] = changed_count
    horizon_changes = 0
    for c in cases:
        records = {k: replace(v, forecasts=tuple(replace(o, time_horizon=TimeHorizon.IMMEDIATE) for o in v.forecasts)) for k, v in c.inputs.evidence.items()}
        altered = run_variant(replace(c.inputs, evidence=records), "full_v01").decision
        original = results[c.inputs.id].decision
        horizon_changes += (altered.kind, altered.selected_action) != (original.kind, original.selected_action)
    subset_results = {
        "forecast_error": aggregate([r for r in rows if r["difficulty"] == "forecast_error"]),
        "other_cases": aggregate([r for r in rows if r["difficulty"] != "forecast_error"]),
    }
    ambiguous_choices = {v: dict(Counter(run_variant(c.inputs, v).decision.kind.value for c in cases if c.truth.expected_need_for_human_review))
                         for v in ("full_v01", "no_uncertainty", "rule_only", "utility_only")}
    return {"scope": "Audit of authored fixtures; not independent normative validation or a policy update.",
            "input_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in ("scenarios.json", "ground_truth.json", "manifest.json")},
            "stats": stats, "numeric_evidence_label_conflicts": conflicts, "failures": all_failures,
            "full_summary": aggregate(rows), "subsets": subset_results, "policy_sensitivity": sensitivity,
            "probability_magnitude_probe_changed_decisions": probability_changes,
            "all_horizons_immediate_changed_decisions": horizon_changes,
            "human_review_required_decision_counts": ambiguous_choices}, cases, results


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def casebook(cases, results, notes):
    if set(notes) != {c.inputs.id for c in cases}:
        raise ValueError("Every case must have an individual audit note")
    lines = [f"# 全{len(cases)}ケースのGround Truth・未来予測・判断監査", "",
             "生成元: `python experiments/audit_benchmark.py`。記録済みFullを再評価した一覧です。原Benchmarkと閾値は変更していません。",
             "Ground Truthは作者の正解ラベルであり、第三者が検証した客観的な真理を意味しません。各監査注記も文面に基づく分析上の判断です。",
             "H=harm、R=rights、C=consent、F=fairness、V=reversibility、U=uncertainty。高いVは戻しやすい、その他の高値は懸念が強い。", "",
             "## 全ケース索引", "", "| ケース | 目標 | Full | 選択 |", "| --- | --- | --- | --- |"]
    for c in cases:
        d = results[c.inputs.id].decision
        lines.append(f"| [{c.inputs.id}](#{c.inputs.id}) | {cell(c.inputs.situation.goal)} | {d.kind.value} | {d.selected_action.id if d.selected_action else 'なし'} |")
    for c in cases:
        d = results[c.inputs.id].decision
        t = c.truth
        lines += ["", f'<a id="{c.inputs.id}"></a>', f"## {c.inputs.id} — {c.inputs.situation.goal}", "",
                  f"カテゴリ: {c.inputs.category} / difficulty: {c.inputs.difficulty}", "",
                  f"状況: {c.inputs.situation.context}", "",
                  f"初期候補: {', '.join(a.id for a in c.inputs.situation.candidates)} / 代替候補: {json.dumps(c.inputs.alternatives, ensure_ascii=False)}", "",
                  "### Ground Truth（全フィールド）", "", "| フィールド | 値 |", "| --- | --- |"]
        for key, value in vars(t).items():
            if isinstance(value, frozenset):
                text_value = ", ".join(sorted(v.value if isinstance(v, DecisionKind) else v for v in value)) or "なし"
            else:
                text_value = value
            lines.append(f"| {key} | {cell(text_value)} |")
        lines += ["", f"**個別監査**: {notes[c.inputs.id]}", "", "### 全候補の観測・未来予測", ""]
        for assessment in d.assessments:
            a = assessment.action
            record = c.inputs.evidence[a.id]
            lines += [f"#### 行動 {a.id}: {a.description}", "",
                      f"種別: `{a.kind.value}` / 効用: {a.task_utility} / ルールタグ: {', '.join(record.rule_tags) or 'なし'} / GT: **{label(c, a.id)}** / 目標達成: {a.id in t.task_success_actions}", "",
                      f"Full候補判断: **{assessment.verdict.value}** / 代替元: {assessment.alternative_to or 'なし'}", "",
                      "集約評価: " + " / ".join(f"{key}={getattr(assessment.evaluation, key):g}" for key in AXES),
                      "", "Hard violations: " + (", ".join(assessment.evaluation.hard_violations) or "なし"), ""]
            for number, o in enumerate((record.observation, *record.forecasts)):
                title = "現在観測（FullではなくNo-futureの入力）" if number == 0 else f"未来予測 {number}"
                lines += [f"**{title} / {o.time_horizon.value}**: {o.description}", "",
                          f"probability={o.probability:g}, severity={o.severity:g}, reversibility={o.reversibility:g}, uncertainty={o.uncertainty:g}",
                          f"affected_stakeholders: {', '.join(o.affected_stakeholders)}", "",
                          "| 当事者 | H | R | C | F | V | U | benefit | explanation |",
                          "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
                for i in o.impacts:
                    lines.append(f"| {i.stakeholder_id} | " + " | ".join(f"{getattr(i, axis):g}" for axis in AXES) + f" | {i.benefit:g} | {cell(i.explanation)} |")
                lines.append("")
        lines += [f"**最終判断: {d.kind.value} / 選択: {d.selected_action.id if d.selected_action else 'なし'}**", ""]
    return "\n".join(lines)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=ROOT / "benchmarks" / "v01")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "audit_v01")
    parser.add_argument("--casebook", type=Path, default=ROOT / "docs" / "audit_casebook.md")
    parser.add_argument("--notes", type=Path, default=ROOT / "docs" / "audit_notes.json")
    args = parser.parse_args()
    report, cases, results = run_audit(args.benchmark)
    notes = json.loads(args.notes.read_text(encoding="utf-8"))
    rendered = casebook(cases, results, notes)
    write_json(args.output / "audit.json", report)
    # Complete raw input and exact Full output are exported alongside the readable casebook.
    raw = {"scenarios": json.loads((args.benchmark / "scenarios.json").read_text(encoding="utf-8")),
           "ground_truth": json.loads((args.benchmark / "ground_truth.json").read_text(encoding="utf-8")),
           "full_decisions": {k: to_dict(v.decision) for k, v in results.items()}, "audit_notes": notes}
    write_json(args.output / "all_cases.json", raw)
    args.casebook.parent.mkdir(parents=True, exist_ok=True)
    args.casebook.write_text(rendered + "\n", encoding="utf-8")
    print(f"Audited {len(cases)} cases / {report['stats']['action_count']} actions / {report['stats']['forecast_outcome_count']} futures.")
    for failure in report["failures"]:
        print(f"{failure['scenario_id']}: {failure['failure']}; triggers={json.dumps(failure['review_triggers'], ensure_ascii=False)}")
    print(f"Casebook: {args.casebook}\nAudit data: {args.output}")


if __name__ == "__main__":
    main()
