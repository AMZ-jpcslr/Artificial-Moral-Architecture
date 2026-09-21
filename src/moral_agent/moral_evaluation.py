from dataclasses import dataclass

from .models import FutureOutcome, MoralEvaluation, Situation, unit


@dataclass(frozen=True)
class MoralPolicy:
    rights_limit: float = .8
    consent_limit: float = .8
    severe_harm: float = .8
    irreversible_limit: float = .2
    uncertainty_limit: float = .65
    review_harm: float = .5
    review_rights: float = .4
    review_consent: float = .4
    review_fairness: float = .5

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            unit(value, name)


class MoralEvaluator:
    def __init__(self, policy: MoralPolicy | None = None):
        self.policy = policy or MoralPolicy()

    def evaluate(self, situation: Situation, outcomes: tuple[FutureOutcome, ...]) -> MoralEvaluation:
        # Forecast events may co-occur across horizons: probabilities need not sum to 1.
        plausible = tuple(o for o in outcomes if o.probability > 0)
        impacts = tuple(i for o in plausible for i in o.impacts)
        expected_ids = {s.id for s in situation.stakeholders}
        incomplete = not plausible or any(set(o.affected_stakeholders) != expected_ids for o in plausible)
        uncertainty = max([float(incomplete), *(o.uncertainty for o in plausible), *(i.uncertainty for i in impacts)])
        harm = max([0., *(o.severity for o in plausible), *(i.harm for i in impacts)])
        rights = max((i.rights for i in impacts), default=0.)
        consent = max((i.consent for i in impacts), default=0.)
        fairness = max((i.fairness for i in impacts), default=0.)
        reversibility = min([1., *(o.reversibility for o in plausible), *(i.reversibility for i in impacts)])
        p = self.policy
        violations = []
        if rights >= p.rights_limit:
            violations.append("重大な権利侵害")
        if consent >= p.consent_limit:
            violations.append("重大な同意侵害")
        # Pair harm and irreversibility within one event/impact, not across unrelated events.
        irreversible_harm = any(
            (o.severity >= p.severe_harm and o.reversibility <= p.irreversible_limit)
            or any(i.harm >= p.severe_harm and i.reversibility <= p.irreversible_limit for i in o.impacts)
            for o in plausible
        )
        if irreversible_harm:
            violations.append("重大で不可逆な被害")
        reasoning = ["確率が正の予測に対して各懸念軸の最大値を保持。効用による相殺はしない。"]
        if incomplete:
            reasoning.append("予測またはステークホルダーの評価が不足している。")
        if uncertainty >= p.uncertainty_limit:
            reasoning.append("予測の不確実性が閾値以上のため、人による確認が必要。")
        reasoning.extend(violations)
        return MoralEvaluation(harm, rights, consent, fairness, reversibility, uncertainty, tuple(violations), tuple(reasoning))
