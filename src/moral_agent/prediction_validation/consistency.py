"""Text/evidence consistency checks, independent of reference annotations."""
from dataclasses import dataclass, replace
from enum import Enum

from .providers import factual_context


class Response(str, Enum):
    REEVALUATE = "REEVALUATE"
    INCREASE_UNCERTAINTY = "INCREASE_UNCERTAINTY"
    ASK_HUMAN = "ASK_HUMAN"
    REGENERATE_PREDICTION = "REGENERATE_PREDICTION"
    CORRECT_STRUCTURED_EVALUATION = "CORRECT_STRUCTURED_EVALUATION"


@dataclass(frozen=True)
class ConsistencyIssue:
    issue_type: str
    severity: str
    source_field: str
    target_field: str
    explanation: str
    suggested_action: Response
    outcome_index: int
    minimum: float | None = None
    maximum: float | None = None


def positive(text, phrases):
    # Limited literal negation, deliberately not advertised as semantic parsing.
    text = text.replace("再識別できない", "").replace("不公平ではない", "").replace("不可逆ではない", "")
    return any(p in text for p in phrases)


class ConsistencyChecker:
    def inspect(self, situation, action, outcomes):
        issues = []
        context = factual_context(situation.context)
        action_text = action.description
        expected = {s.id for s in situation.stakeholders}
        if not outcomes:
            return (ConsistencyIssue("missing_prediction", "high", "situation", "uncertainty",
                                     "No future evidence was supplied.", Response.ASK_HUMAN, -1),)
        for n, o in enumerate(outcomes):
            text = factual_context(o.description) + " " + action_text
            def add(kind, source, target, message, minimum=None, maximum=None, response=Response.CORRECT_STRUCTURED_EVALUATION):
                issues.append(ConsistencyIssue(kind, "high", source, target, message, response, n, minimum, maximum))
            axes = {axis: max(getattr(i, axis) for i in o.impacts) for axis in ("harm", "rights", "consent", "fairness", "uncertainty")}
            # Context applies only when the action carries the relevant risk; a mitigating
            # alternative does not inherit the initial action's entire context risk.
            reidentify = positive(text, ("再識別できる", "re-identification is possible")) or (
                positive(context, ("患者を推測できる", "個人を再識別")) and "そのまま公開" in action_text)
            ignore_delete = positive(text, ("削除要求を無視", "削除要求を伝播しない"))
            rights = reidentify or ignore_delete or positive(text, ("権利を侵害", "アクセス権のない", "本人の機密を業者"))
            consent = ignore_delete or positive(text, ("同意なく", "撤回済み", "配信停止者にも"))
            harm = positive(text, ("不可逆な損害", "重大な被害が発生", "身体に損害", "安全ロックを外"))
            fairness = positive(text, ("無関係な属性で", "不当に排除", "不公平が生じる"))
            for axis, flag in (("rights", rights), ("consent", consent), ("harm", harm), ("fairness", fairness)):
                if flag and axes[axis] < .8:
                    add("text_score_contradiction", "situation/action/future.description", axis,
                        f"Explicit {axis} concern is absent or understated in impacts.", minimum=.8)
            if ("故障" in context or "計器が壊れ" in context) and positive(action_text, ("表示を信じ", "運転を続", "稼働し続")):
                if max(o.uncertainty, axes["uncertainty"]) < .75:
                    add("unreliable_measurement", "situation.context", "uncertainty",
                        "Continued operation relies on a faulty instrument; its low risk estimate is unsupported.",
                        minimum=.75, response=Response.INCREASE_UNCERTAINTY)
            if positive(text, ("不可逆な", "永久に失う", "回収不能", "永久消去")) and o.reversibility > .2:
                add("reversibility_contradiction", "future.description/action", "reversibility",
                    "Irreversible outcome is marked reversible.", maximum=.2)
            if set(o.affected_stakeholders) != expected:
                add("stakeholder_gap", "situation.stakeholders", "uncertainty",
                    "A registered perspective is missing; this does not discover unregistered people.",
                    minimum=1., response=Response.ASK_HUMAN)
            if axes["harm"] > o.severity:
                add("impact_aggregate_mismatch", "impacts.harm", "severity",
                    "Outcome severity understates stakeholder impact.", minimum=axes["harm"])
            if axes["uncertainty"] > o.uncertainty:
                add("uncertainty_aggregate_mismatch", "impacts.uncertainty", "uncertainty",
                    "Outcome uncertainty understates stakeholder uncertainty.", minimum=axes["uncertainty"])
            if positive(context, ("未確認", "確認できない", "記録に矛盾")) and "確認せず" in action_text and max(o.uncertainty, axes["uncertainty"]) < .75:
                add("unsupported_certainty", "situation.context", "uncertainty", "Unverified evidence treated as certain.",
                    minimum=.75, response=Response.INCREASE_UNCERTAINTY)
            if positive(context, ("検証済み", "合意した", "透明に合意")) and (
                max(axes["harm"], axes["fairness"], axes["rights"]) >= .5 or axes["uncertainty"] >= .65):
                add("supporting_evidence_conflict", "situation.context", "uncertainty",
                    "Verified/agreed facts deserve reassessment, but do not prove absence of side effects.",
                    minimum=.75, response=Response.REEVALUATE)
        return tuple(issues)

    def process(self, situation, action, outcomes, mode="correct", predictor=None):
        if mode not in ("correct", "review", "regenerate"):
            raise ValueError("unknown checker mode")
        original = tuple(outcomes)
        issues = self.inspect(situation, action, original)
        if not issues:
            return original, issues, ()
        updates = []
        current = list(original)
        if mode == "regenerate":
            if predictor is None:
                raise ValueError("regeneration requires a predictor")
            current = list(predictor.predict(situation, action))  # bounded: at most one retry
            updates.append({"action": Response.REGENERATE_PREDICTION.value, "attempt": 1})
            issues_after = self.inspect(situation, action, tuple(current))
            if not issues_after:
                return tuple(current), issues, tuple(updates)
            # Regeneration is not an escape from unresolved contradictions.
            issues = issues + issues_after
            mode = "review"
        for issue in issues:
            if issue.outcome_index < 0 or issue.outcome_index >= len(current):
                continue  # original evaluator escalates an empty prediction
            o = current[issue.outcome_index]
            field = issue.target_field
            if mode == "review" or issue.suggested_action in (Response.ASK_HUMAN, Response.REEVALUATE):
                field, minimum, maximum = "uncertainty", 1., None
            else:
                minimum, maximum = issue.minimum, issue.maximum
            def revised(value):
                return min(value, maximum) if maximum is not None else max(value, minimum)
            aggregate = "severity" if field == "harm" else field
            impacts = o.impacts
            if field in ("harm", "rights", "consent", "fairness", "reversibility", "uncertainty"):
                # No evidence identifies a narrower affected group reliably: preserve
                # conservative all-perspective correction and expose it in the trace.
                impacts = tuple(replace(i, **{field: revised(getattr(i, field))}) for i in impacts)
            changes = {aggregate: revised(getattr(o, aggregate))} if aggregate in ("severity", "uncertainty", "reversibility") else {}
            current[issue.outcome_index] = replace(o, impacts=impacts, **changes)
            updates.append({"action": issue.suggested_action.value if mode != "review" else Response.ASK_HUMAN.value,
                            "outcome_index": issue.outcome_index, "field": field,
                            "minimum": minimum, "maximum": maximum})
        return tuple(current), issues, tuple(updates)
