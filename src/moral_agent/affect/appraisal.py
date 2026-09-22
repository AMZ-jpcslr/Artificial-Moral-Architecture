"""Explicit, replaceable appraisal and affect mapping; no labels or scenario IDs."""
from dataclasses import dataclass, fields
from typing import Protocol

from ..models import unit
from ..moral_evaluation import MoralEvaluator


def clip(value):
    return max(0., min(1., value))


@dataclass(frozen=True)
class AppraisalContext:
    responsibility: float = 1.  # prospective ownership of the proposed action, not blame
    controllability: float = .8
    stakeholder_vulnerability: float = .5  # unknown/default, NOT inferred from protected traits
    confirmed_social_benefit: float = 0.
    received_help: float = 0.
    evidence_reliability: float = .5

    def __post_init__(self):
        for field in fields(self):
            unit(getattr(self, field.name), field.name)


@dataclass(frozen=True)
class AppraisalResult:
    severity: float
    harm_probability: float
    probability_weighted_harm: float
    irreversible_risk: float
    reversibility: float
    responsibility: float
    controllability: float
    stakeholder_vulnerability: float
    third_party_exposure: float
    stakeholder_coverage_gap: float
    rights_violation: float
    consent_violation: float
    fairness_concern: float
    uncertainty: float
    norm_violation: float
    goal_relevance: float
    positive_social_value: float
    received_help: float
    evidence_reliability: float
    explanation: tuple[str, ...]

    def __post_init__(self):
        for field in fields(self):
            if field.name != "explanation":
                unit(getattr(self, field.name), field.name)


def appraise(situation, action, outcomes, context=None):
    c = context or AppraisalContext()
    evaluation = MoralEvaluator().evaluate(situation, outcomes)
    plausible = [o for o in outcomes if o.probability > 0]
    nonuser = {s.id for s in situation.stakeholders if s.role != "user"}
    magnitude = lambda o: max(o.severity, *(i.harm for i in o.impacts))
    # Max joint event risk, NOT product of maxima from unrelated outcomes.
    weighted = max((o.probability * magnitude(o) for o in plausible), default=0.)
    probability = max((o.probability for o in plausible if magnitude(o) > 0), default=0.)
    exposure = max((max(i.harm, i.rights, i.consent, i.fairness) for o in plausible
                    for i in o.impacts if i.stakeholder_id in nonuser), default=0.)
    irreversible = max((o.probability * max(o.severity*(1-o.reversibility), *(i.harm*(1-i.reversibility) for i in o.impacts)) for o in plausible), default=0.)
    return AppraisalResult(evaluation.harm, probability, weighted, irreversible, evaluation.reversibility,
        c.responsibility, c.controllability, c.stakeholder_vulnerability, exposure,
        max((len(nonuser-set(o.affected_stakeholders))/len(nonuser) for o in plausible), default=1.) if nonuser else 0.,
        evaluation.rights, evaluation.consent, evaluation.fairness, evaluation.uncertainty,
        max(evaluation.rights, evaluation.consent, evaluation.fairness), action.task_utility,
        c.confirmed_social_benefit, c.received_help, c.evidence_reliability,
        ("Prospective appraisal of the proposed action, once per decision (not per candidate).",
         "Severity/probability/uncertainty derive from predictions; responsibility/control/vulnerability are explicit assumptions.",
         "Positive states require caller-supplied observed benefit/help; predicted benefit alone is insufficient."))


@dataclass(frozen=True)
class AffectState:
    concern: float = 0.
    empathy: float = 0.
    anticipated_guilt: float = 0.
    gratitude: float = 0.
    trust: float = .5
    prosocial_satisfaction: float = 0.

    def __post_init__(self):
        for field in fields(self):
            unit(getattr(self, field.name), field.name)


@dataclass(frozen=True)
class AffectConfig:
    decay: float = .8
    gain: float = 1.
    concern_threshold: float = .35
    empathy_threshold: float = .25
    guilt_threshold: float = .35
    enabled: bool = True
    behavior_enabled: bool = True
    persistence: bool = True
    concern_enabled: bool = True
    empathy_enabled: bool = True
    guilt_enabled: bool = True
    concern_harm_weight: float = .4
    concern_uncertainty_weight: float = .45
    concern_norm_weight: float = .2
    concern_irreversibility_weight: float = .15
    empathy_exposure_weight: float = .8
    guilt_weight: float = .9

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name.endswith("enabled") or field.name == "persistence":
                if type(value) is not bool:
                    raise ValueError(f"{field.name} must be bool")
            elif field.name == "gain":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 3:
                    raise ValueError("gain must be finite and in [0,3]")
            else:
                unit(value, field.name)


class AffectMapping(Protocol):
    def update(self, before: AffectState, appraisal: AppraisalResult, config: AffectConfig) -> AffectState: ...


class DeterministicMapping:
    def update(self, before, a, c):
        if not c.enabled:
            return AffectState()
        before = before if c.persistence else AffectState()
        stimuli = {
            "concern": c.concern_harm_weight*a.probability_weighted_harm + c.concern_uncertainty_weight*a.uncertainty
                       + c.concern_norm_weight*a.norm_violation + c.concern_irreversibility_weight*a.irreversible_risk,
            "empathy": c.empathy_exposure_weight * a.stakeholder_vulnerability * max(a.third_party_exposure, a.stakeholder_coverage_gap) * (.5+.5*a.goal_relevance),
            "anticipated_guilt": c.guilt_weight*a.responsibility*a.controllability*a.irreversible_risk,
            "gratitude": .4*a.received_help,
            "trust": .15*(a.evidence_reliability-.5),
            "prosocial_satisfaction": .4*a.positive_social_value,
        }
        baseline = AffectState()
        values = {name: clip(getattr(baseline, name) + c.decay*(getattr(before, name)-getattr(baseline, name)) + c.gain*stimulus)
                  for name, stimulus in stimuli.items()}
        for name, enabled in (("concern", c.concern_enabled), ("empathy", c.empathy_enabled), ("anticipated_guilt", c.guilt_enabled)):
            if not enabled:
                values[name] = 0.
        return AffectState(**values)
