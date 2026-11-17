"""Evaluation adapters; production MoralAgent and its defaults remain unchanged."""

from dataclasses import dataclass, field, replace

from ..agent import MoralAgent
from ..judgment import judge
from ..models import ActionAssessment, Decision, DecisionKind
from ..moral_evaluation import MoralEvaluator
from ..stakeholders import analyze
from .benchmark import ScenarioInput

VARIANTS = (
    "utility_only", "rule_only", "full_v01", "no_future", "no_stakeholder",
    "no_counterfactual", "no_uncertainty", "rule_with_alternatives", "native_v01",
)


@dataclass
class Usage:
    forecast_calls: int = 0
    alternative_calls: int = 0
    stakeholder_analysis_calls: int = 0
    uncertainty_checks: int = 0


@dataclass(frozen=True)
class VariantResult:
    decision: Decision
    usage: Usage
    trace: tuple[dict, ...] = field(default_factory=tuple)


class RecordedForesight:
    def __init__(self, inputs: ScenarioInput, usage: Usage):
        self.inputs, self.usage = inputs, usage

    def predict(self, situation, action):
        self.usage.forecast_calls += 1
        return self.inputs.evidence[action.id].forecasts


class RecordedAlternatives:
    def __init__(self, inputs: ScenarioInput, usage: Usage):
        self.inputs, self.usage = inputs, usage

    def alternatives(self, situation, action):
        self.usage.alternative_calls += 1
        return tuple(self.inputs.evidence[a].action for a in self.inputs.alternatives.get(action.id, ()))


class NoAlternatives:
    def alternatives(self, situation, action):
        return ()


class IgnoreUncertainty(MoralEvaluator):
    def evaluate(self, situation, outcomes):
        evaluation = super().evaluate(situation, outcomes)
        # Keep all other thresholds, including non-uncertainty human-review rules.
        return replace(evaluation, uncertainty=0., reasoning=("Ablation: uncertainty ignored.",))


class InstrumentedAgent(MoralAgent):
    def __init__(self, inputs, variant, usage, **kwargs):
        super().__init__(**kwargs)
        self.inputs, self.variant, self.usage = inputs, variant, usage

    def assess(self, situation, action, alternative_to=None):
        if self.variant == "no_future":
            # Observe current evidence directly. Never call a forecasting backend.
            outcomes = (self.inputs.evidence[action.id].observation,)
        else:
            outcomes = tuple(self.foresight.predict(situation, action))
        if self.variant == "no_stakeholder":
            # User-only perspective; discard global aggregates to avoid leaking third-party risks.
            users = tuple(s for s in situation.stakeholders if s.role == "user")
            user_ids = {s.id for s in users}
            situation = replace(situation, stakeholders=users)
            projected = []
            for outcome in outcomes:
                impacts = tuple(i for i in outcome.impacts if i.stakeholder_id in user_ids)
                projected.append(replace(outcome, impacts=impacts, affected_stakeholders=tuple(i.stakeholder_id for i in impacts),
                                         severity=max(i.harm for i in impacts), reversibility=min(i.reversibility for i in impacts),
                                         uncertainty=max(i.uncertainty for i in impacts)))
            outcomes = tuple(projected)
            impacts_by_id = {s.id: tuple(i for o in outcomes for i in o.impacts if i.stakeholder_id == s.id) for s in users}
        else:
            self.usage.stakeholder_analysis_calls += 1
            impacts_by_id = analyze(situation, outcomes)
        evaluation = self.evaluator.evaluate(situation, outcomes)
        if self.variant != "no_uncertainty":
            self.usage.uncertainty_checks += 1
        return ActionAssessment(action, outcomes, impacts_by_id, evaluation, judge(evaluation, self.evaluator.policy), alternative_to)


def rule_verdict(tags: tuple[str, ...]) -> DecisionKind:
    """Only explicit current-action facts. No forecasts, impact scores, or labels."""
    if set(tags) & {"unauthorized_access", "no_consent", "deception", "discrimination", "safety_bypass"}:
        return DecisionKind.BLOCK
    if set(tags) & {"destructive", "authority_unclear"}:
        return DecisionKind.ASK_HUMAN
    return DecisionKind.ALLOW


def _baseline(inputs, variant, usage):
    initial = sorted(inputs.situation.candidates, key=lambda a: (-a.task_utility, a.id))
    proposed = initial[0]
    candidates = list(initial)
    if variant == "rule_with_alternatives":
        backend = RecordedAlternatives(inputs, usage)
        for action in initial:
            candidates.extend(backend.alternatives(inputs.situation, action))
    verdicts = [(a, DecisionKind.ALLOW if variant == "utility_only" else rule_verdict(inputs.evidence[a.id].rule_tags)) for a in candidates]
    feasible = sorted((a for a, v in verdicts if v == DecisionKind.ALLOW), key=lambda a: (-a.task_utility, a.id))
    selected = feasible[0] if feasible else None
    if selected:
        kind = DecisionKind.ALLOW if selected == proposed else DecisionKind.MODIFY
    else:
        kind = DecisionKind.ASK_HUMAN if any(v == DecisionKind.ASK_HUMAN for _, v in verdicts) else DecisionKind.BLOCK
    explanation = "Utility only; no moral assessment." if variant == "utility_only" else "Explicit action tags only; no future simulation or stakeholder reasoning."
    trace = tuple({"action_id": a.id, "verdict": v.value, "rule_tags": list(inputs.evidence[a.id].rule_tags) if variant != "utility_only" else []} for a, v in verdicts)
    return VariantResult(Decision(kind, proposed, selected, (), (explanation,)), usage, trace)


def run_variant(inputs: ScenarioInput, variant: str) -> VariantResult:
    """Intentionally accepts no GroundTruth. Decisions only; never executes actions."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown agent variant: {variant}")
    usage = Usage()
    if variant in ("utility_only", "rule_only", "rule_with_alternatives"):
        return _baseline(inputs, variant, usage)
    if variant == "native_v01":
        # Exactly the originally shipped backend and counterfactual generator.
        agent = MoralAgent()
        class CountForesight:
            def __init__(self, backend):
                self.backend = backend
            def predict(self, situation, action):
                usage.forecast_calls += 1
                return self.backend.predict(situation, action)
        class CountAlternatives:
            def __init__(self, backend):
                self.backend = backend
            def alternatives(self, situation, action):
                usage.alternative_calls += 1
                return self.backend.alternatives(situation, action)
        agent.foresight = CountForesight(agent.foresight)
        agent.counterfactual = CountAlternatives(agent.counterfactual)
        decision = agent.decide(inputs.situation)
        usage.stakeholder_analysis_calls = usage.uncertainty_checks = len(decision.assessments)
    else:
        agent = InstrumentedAgent(
            inputs, variant, usage, foresight=RecordedForesight(inputs, usage),
            counterfactual=NoAlternatives() if variant == "no_counterfactual" else RecordedAlternatives(inputs, usage),
            evaluator=IgnoreUncertainty() if variant == "no_uncertainty" else MoralEvaluator(),
        )
        decision = agent.decide(inputs.situation)
    trace = tuple({
        "action_id": a.action.id, "alternative_to": a.alternative_to, "verdict": a.verdict.value,
        "evaluation": a.evaluation, "outcomes": a.outcomes,
    } for a in decision.assessments)
    return VariantResult(decision, usage, trace)
