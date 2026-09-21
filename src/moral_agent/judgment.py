from .models import ActionAssessment, Decision, DecisionKind, MoralEvaluation
from .moral_evaluation import MoralPolicy


def judge(evaluation: MoralEvaluation, policy: MoralPolicy) -> DecisionKind:
    # Uncertain forecasts are escalated, including uncertain severe harms.
    # This never grants permission, nor bypasses the execution gate.
    if evaluation.uncertainty >= policy.uncertainty_limit:
        return DecisionKind.ASK_HUMAN
    if evaluation.hard_violations:
        return DecisionKind.BLOCK
    if (evaluation.harm >= policy.review_harm or evaluation.rights >= policy.review_rights
            or evaluation.consent >= policy.review_consent or evaluation.fairness >= policy.review_fairness):
        return DecisionKind.ASK_HUMAN
    return DecisionKind.ALLOW


def select(assessments: tuple[ActionAssessment, ...]) -> Decision:
    originals = [a for a in assessments if a.alternative_to is None]
    if not originals:
        return Decision(DecisionKind.ASK_HUMAN, None, None, assessments, ("候補行動がないため、人による入力が必要。",))
    proposed = sorted(originals, key=lambda a: (-a.action.task_utility, a.action.id))[0]
    feasible = [a for a in assessments if a.verdict == DecisionKind.ALLOW]
    if feasible:
        chosen = sorted(feasible, key=lambda a: (-a.action.task_utility, a.action.id))[0]
        kind = DecisionKind.ALLOW if chosen.action.id == proposed.action.id else DecisionKind.MODIFY
        return Decision(kind, proposed.action, chosen.action, assessments, (
            "道徳制約と不確実性の確認を通過した候補の中で、タスク効用が最大の行動を選択。",
            f"当初の候補: {proposed.action.id} → 選択: {chosen.action.id}",
        ))
    kind = DecisionKind.ASK_HUMAN if any(a.verdict == DecisionKind.ASK_HUMAN for a in assessments) else DecisionKind.BLOCK
    return Decision(kind, proposed.action, None, assessments, ("実行可能と評価された候補がない。",))
