"""Bounded affect meta-control around the unchanged v0.1 decision engine."""
from dataclasses import dataclass, replace

from ..agent import MoralAgent
from ..judgment import judge, select
from ..models import ActionAssessment, Decision, DecisionKind
from ..moral_evaluation import MoralEvaluator, MoralPolicy
from ..stakeholders import analyze
from ..prediction_validation.consistency import ConsistencyChecker
from ..prediction_validation.providers import HeuristicPredictor, factual_context
from .appraisal import AffectConfig, AffectState, AppraisalResult, DeterministicMapping, appraise
from .interfaces import ReasoningRequest, RefinementProvider


@dataclass(frozen=True)
class ControlPlan:
    additional_prediction_rounds: int = 0
    stakeholder_review: bool = False
    causal_review: bool = False
    additional_alternative_rounds: int = 0
    uncertainty_limit: float = .65
    irreversible_review_harm: float = .5
    third_party_review_rights: float = .4
    prefer_reversible: bool = False


def control_plan(state, config, always=False):
    if always:
        # Unemotional fixed-compute comparator: same bounded operations, thresholds
        # at maximum full-state intensity, no persistent affect.
        state = AffectState(concern=1., empathy=1., anticipated_guilt=1.)
    elif not config.enabled or not config.behavior_enabled:
        return ControlPlan()
    concern = (always or config.concern_enabled) and state.concern >= config.concern_threshold
    empathy = (always or config.empathy_enabled) and state.empathy >= config.empathy_threshold
    guilt = (always or config.guilt_enabled) and state.anticipated_guilt >= config.guilt_threshold
    return ControlPlan(int(concern), empathy, guilt, int(concern or guilt),
        .65-.2*state.concern if concern else .65,
        .5-.2*state.anticipated_guilt if guilt else .5,
        .4-.1*state.empathy if empathy else .4, guilt)


class CapturePredictor:
    def __init__(self, provider, checker=None):
        self.provider, self.checker = provider, checker
        self.calls = 0
        self.records = []

    def predict(self, situation, action, reasoning_request=None):
        self.calls += 1
        request = replace(situation, candidates=(action,), context=factual_context(situation.context))
        supports_focus = reasoning_request is not None and isinstance(self.provider, RefinementProvider)
        raw = tuple(self.provider.refine(request, action, reasoning_request) if supports_focus else self.provider.predict(request, action))
        effective, issues, updates = self.checker.process(request, action, raw) if self.checker else (raw, (), ())
        self.records.append({"provider": type(self.provider).__name__, "reasoning_request": reasoning_request, "provider_supports_focus": supports_focus, "action_id": action.id, "raw": raw, "effective": effective, "issues": issues, "updates": updates})
        return effective


class CountAlternatives:
    def __init__(self, provider):
        self.provider, self.calls = provider, 0

    def alternatives(self, situation, action):
        self.calls += 1
        return tuple(self.provider.alternatives(situation, action))


@dataclass(frozen=True)
class AffectRun:
    decision: Decision
    baseline: Decision
    appraisal: AppraisalResult | None
    affect_before: AffectState
    affect_after: AffectState
    plan: ControlPlan
    interventions: tuple[dict, ...]
    costs: dict
    prediction_trace: tuple[dict, ...]


class AffectAgent:
    """State lives inside one explicit episode. reset_episode clears it completely.

    There is one appraisal/update per step, on the initially proposed action.
    Extra evidence cannot weaken earlier adverse evidence; only missing registered
    perspectives can be filled by an independent provider, with provenance kept.
    """
    def __init__(self, predictor, alternatives, config=None, *, checker=None, mapping=None,
                 supplemental_predictor=None, always_deliberate=False, evidence_gate=False):
        self.predictor, self.alternatives = predictor, alternatives
        self.config = config or AffectConfig()
        self.checker, self.mapping = checker, mapping or DeterministicMapping()
        self.supplemental_predictor = supplemental_predictor or HeuristicPredictor()
        self.always_deliberate = always_deliberate
        self.evidence_gate = evidence_gate
        self.state = AffectState()

    def reset_episode(self):
        self.state = AffectState()

    def observe(self, situation, action, observed_outcomes, context=None):
        """Caller-supplied outcome evidence; never fabricate a successful execution."""
        appraisal = appraise(situation, action, tuple(observed_outcomes), context)
        before = self.state
        self.state = self.mapping.update(before, appraisal, self.config)
        return {"affect_before": before, "appraisal": appraisal, "affect_after": self.state,
                "source": "caller_supplied_outcome_not_an_execution_receipt"}

    def step(self, situation, context=None):
        captured = CapturePredictor(self.predictor, self.checker)
        alternatives = CountAlternatives(self.alternatives)
        baseline = MoralAgent(foresight=captured, counterfactual=alternatives).decide(situation)
        initial_calls, initial_searches = captured.calls, alternatives.calls
        before = self.state if self.config.persistence else AffectState()
        proposed = next((a for a in baseline.assessments if baseline.proposed_action and a.action.id == baseline.proposed_action.id), None)
        appraisal = appraise(situation, proposed.action, proposed.outcomes, context) if proposed and self.config.enabled else None
        after = self.mapping.update(before, appraisal, self.config) if appraisal else AffectState()
        self.state = after
        plan = control_plan(after, self.config, self.always_deliberate)
        if self.evidence_gate:
            expected = {s.id for s in situation.stakeholders}
            missing = any(not a.outcomes or any(set(o.affected_stakeholders) != expected for o in a.outcomes) for a in baseline.assessments)
            plan = ControlPlan(stakeholder_review=missing)
        interventions = []
        costs = {"initial_predictions": initial_calls, "additional_predictions": 0,
                 "initial_alternative_searches": initial_searches, "additional_alternative_searches": 0,
                 "initial_stakeholder_checks": len(baseline.assessments), "additional_stakeholder_checks": 0,
                 "causal_checks": 0, "generated_alternatives": sum(a.alternative_to is not None for a in baseline.assessments),
                 "additional_generated_alternatives": 0, "duplicate_alternatives": 0}
        if plan == ControlPlan():
            return AffectRun(baseline, baseline, appraisal, before, after, plan, (), costs, tuple(captured.records))
        assessments = list(baseline.assessments)
        by_id = {a.action.id: a for a in assessments}
        extra_checks = ConsistencyChecker()
        # One extra search pass. Existing catalog may be exhausted; count duplicate
        # proposals separately rather than claiming them as newly generated options.
        for _ in range(plan.additional_alternative_rounds):
            for action in situation.candidates:
                for alternative in alternatives.alternatives(situation, action):
                    if alternative.id in by_id:
                        if by_id[alternative.id].action != alternative:
                            raise ValueError("alternative id collision with different action")
                        costs["duplicate_alternatives"] += 1
                        continue
                    outcomes = captured.predict(situation, alternative)
                    evaluation = MoralEvaluator().evaluate(situation, outcomes)
                    assessment = ActionAssessment(alternative, outcomes, analyze(situation, outcomes), evaluation,
                                                  judge(evaluation, MoralPolicy()), action.id)
                    assessments.append(assessment)
                    by_id[alternative.id] = assessment
                    costs["additional_generated_alternatives"] += 1
            interventions.append({"type": "alternative_search", "reason": "concern_or_anticipated_guilt", "rounds": 1})
        final = []
        for assessment in assessments:
            action = assessment.action
            outcomes = assessment.outcomes
            for _ in range(plan.additional_prediction_rounds):
                additional = captured.predict(situation, action, ReasoningRequest("adverse_outcomes"))
                # Reinspection may uncover adverse text, but does not access an Oracle
                # or invent a more severe outcome merely because concern is high.
                complete = all(set(o.affected_stakeholders) == {s.id for s in situation.stakeholders} for o in additional)
                corrected, issues, _ = extra_checks.process(situation, action, additional) if complete else (additional, (), ())
                outcomes += corrected
                interventions.append({"type": "additional_prediction", "action_id": action.id,
                                      "reason": "concern", "issues": issues, "additional_outcomes": corrected,
                                      "new_evidence": corrected != assessment.outcomes})
            if plan.stakeholder_review:
                costs["additional_stakeholder_checks"] += 1
                expected = {s.id for s in situation.stakeholders}
                missing = set().union(*(expected-set(o.affected_stakeholders) for o in outcomes)) if outcomes else expected
                if missing and outcomes:
                    # This secondary provider is NEVER Oracle; holes get explicit
                    # uncertainty when the independent predictor cannot infer them.
                    supplemental = CapturePredictor(self.supplemental_predictor)
                    extras = supplemental.predict(situation, action, ReasoningRequest("missing_perspectives", stakeholder_ids=tuple(sorted(missing))))
                    captured.calls += supplemental.calls
                    captured.records.extend(supplemental.records)
                    filled = []
                    for o in outcomes:
                        impacts = list(o.impacts)
                        for sid in sorted(expected-set(o.affected_stakeholders)):
                            evidence = [i for e in extras if e.probability > 0 for i in e.impacts if i.stakeholder_id == sid]
                            if not evidence:
                                continue
                            example = evidence[0]
                            impacts.append(replace(example, **{k: max(getattr(i, k) for i in evidence) for k in ("harm", "rights", "consent", "fairness", "uncertainty")},
                                reversibility=min(i.reversibility for i in evidence),
                                explanation="Supplemental perspective: " + example.explanation))
                        filled.append(replace(o, impacts=tuple(impacts), affected_stakeholders=tuple(i.stakeholder_id for i in impacts),
                                              severity=max(o.severity, *(i.harm for i in impacts)),
                                              uncertainty=max(o.uncertainty, *(i.uncertainty for i in impacts))))
                    outcomes = tuple(filled)
                outcomes, issues, _ = extra_checks.process(situation, action, outcomes)
                interventions.append({"type": "stakeholder_review", "action_id": action.id, "reason": "missing_evidence_rule" if self.evidence_gate else "empathy",
                                      "missing_registered_ids": sorted(missing), "issues": issues})
            if plan.causal_review:
                costs["causal_checks"] += 1
                outcomes, issues, _ = extra_checks.process(situation, action, outcomes)
                interventions.append({"type": "causal_review", "action_id": action.id,
                                      "reason": "anticipated_guilt", "issues": issues})
            evaluation = MoralEvaluator().evaluate(situation, outcomes)
            nonuser = {s.id for s in situation.stakeholders if s.role != "user"}
            exposed = any(max(i.harm, i.rights, i.consent, i.fairness) > .1 for o in outcomes for i in o.impacts if i.stakeholder_id in nonuser)
            policy = replace(MoralPolicy(), uncertainty_limit=plan.uncertainty_limit,
                review_harm=plan.irreversible_review_harm if evaluation.reversibility < .5 else .5,
                review_rights=plan.third_party_review_rights if exposed else .4)
            verdict = judge(evaluation, policy)
            if policy != MoralPolicy():
                interventions.append({"type": "stricter_review_policy", "action_id": action.id,
                                      "policy": policy, "reason": "affect_modulates_review_not_hard_constraint_override"})
            final.append(ActionAssessment(action, outcomes, analyze(situation, outcomes), evaluation, verdict, assessment.alternative_to))
        decision = select(tuple(final))
        if plan.prefer_reversible:
            allowed = [a for a in final if a.verdict == DecisionKind.ALLOW]
            if allowed:
                chosen = min(allowed, key=lambda a: (a.evaluation.harm*(1-a.evaluation.reversibility), -a.action.task_utility, a.action.id))
                if chosen.action != decision.selected_action:
                    kind = DecisionKind.ALLOW if chosen.action == decision.proposed_action else DecisionKind.MODIFY
                    decision = replace(decision, kind=kind, selected_action=chosen.action,
                                       explanation=decision.explanation + ("Anticipated-guilt meta-control prefers lower irreversible risk among ALLOW candidates.",))
                    interventions.append({"type": "reversible_preference", "action_id": chosen.action.id, "reason": "anticipated_guilt"})
        costs["additional_predictions"] = captured.calls-initial_calls
        costs["additional_alternative_searches"] = alternatives.calls-initial_searches
        costs["generated_alternatives"] += costs["additional_generated_alternatives"]
        return AffectRun(decision, baseline, appraisal, before, after, plan, tuple(interventions), costs, tuple(captured.records))
