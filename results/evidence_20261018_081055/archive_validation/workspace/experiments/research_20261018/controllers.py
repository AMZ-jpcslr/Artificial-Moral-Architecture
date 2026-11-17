"""Two prospective interventions. This module never receives private worlds/labels.

All variants share forecasting, scoring, candidate evidence, and query availability.
Only the declared switches differ. Production classes and files are unchanged.
"""
from dataclasses import replace

from moral_agent.affect.agent import control_plan
from moral_agent.affect.appraisal import AffectConfig, AffectState, appraise
from moral_agent.concern_information.controller import Controller, predictions
from moral_agent.concern_information.world import CHANNELS, FIELDS
from moral_agent.judgment import judge, select
from moral_agent.models import ActionAssessment, Decision, DecisionKind, to_dict
from moral_agent.moral_evaluation import MoralEvaluator, MoralPolicy
from moral_agent.prediction_validation.consistency import ConsistencyChecker
from moral_agent.prediction_validation.providers import make_prediction
from moral_agent.stakeholders import analyze


ANSWERS = {
    'harm': ({'harm': .02}, {'harm': .45}, {'harm': .9}),
    'rights_consent': ({'rights': 0., 'consent': 0.}, {'rights': .9, 'consent': 0.},
                       {'rights': 0., 'consent': .9}, {'rights': .9, 'consent': .9}),
    'stakeholders': ({'exposed': False}, {'exposed': True}),
    'reversibility': ({'reversible': False}, {'reversible': True}),
    'alternative': ({'alternative': False}, {'alternative': True}),
}


def identifier(decision):
    return decision.selected_action.id if decision.selected_action else None


def signature(decision):
    return (decision.kind.value, identifier(decision),
            tuple(sorted(a.action.id for a in decision.assessments if a.verdict == DecisionKind.ALLOW)))


class ResearchController(Controller):
    def __init__(self, variant, params, *, checked=False):
        base = {'rule': 'uniform', 'no_affect': 'history', 'history': 'history',
                'state': 'state', 'both': 'both', 'sensitivity': 'both', 'scoped': 'both'}
        super().__init__(base.get(variant, 'both'), params)
        self.research_variant = variant
        self.sensitive = variant == 'sensitivity' or variant.startswith('combined')
        self.scoped = variant == 'scoped' or variant.startswith('combined')
        self.checked = checked
        self.checker = ConsistencyChecker() if checked else None
        self.config = replace(self.config, **{
            'no_affect': {'enabled': False},
            'combined_no_concern': {'concern_enabled': False},
            'combined_no_empathy': {'empathy_enabled': False},
            'combined_no_guilt': {'guilt_enabled': False},
        }.get(variant, {}))
        self.counts = dict(predictions=0, virtual_decisions=0, decisions=0,
                           consistency_checks=0, stakeholder_checks=0, alternative_candidates=0,
                           state_updates=0)
        self.last_issues = []
        self.last_policies = []

    def forecast(self, frame, evidence, action):
        self.counts['predictions'] += 1
        if action.id == 'alternative':
            outcomes = make_prediction(frame.situation, 'Fallback feasibility and side-effect estimate',
                harm=getattr(evidence, 'fallback_harm', 0.),
                rights=getattr(evidence, 'fallback_rights', 0.),
                consent=getattr(evidence, 'fallback_consent', 0.), fairness=0.,
                reversibility=getattr(evidence, 'fallback_reversibility', .95),
                uncertainty=evidence.uncertainty if evidence.alternative else 1.)
        else:
            outcomes = predictions(frame, evidence, action.id)
        if self.checker:
            self.counts['consistency_checks'] += 1
            outcomes, issues, updates = self.checker.process(frame.situation, action, outcomes)
            self.last_issues.extend({'action': action.id, 'issue': to_dict(i)} for i in issues)
        return outcomes

    def prepare(self, frame):
        if self.research_variant == 'rule':
            return {'before': None, 'after': None, 'appraisal': None, 'ema': None, 'observations_seen': 0}
        # Remove only affect persistence; the independent error-history policy stays.
        if self.research_variant == 'combined_no_persistence':
            self.state = AffectState()
        before = self.state
        action = max(frame.situation.candidates, key=lambda a: (a.task_utility, a.id))
        appraisal = appraise(frame.situation, action, self.forecast(frame, frame.initial, action), frame.context)
        self.state = self.mapping.update(self.state, appraisal, self.config)
        self.counts['state_updates'] += 1
        return {'before': to_dict(before), 'after': to_dict(self.state), 'appraisal': to_dict(appraisal),
                'ema': dict(self.errors), 'observations_seen': self.seen}

    def observe(self, frame, action_id, observed):
        if observed is None:
            return None
        if self.research_variant == 'rule':
            return {'action_id': action_id, 'observed': to_dict(observed), 'state_update': False}
        initial = frame.initial
        channels = CHANNELS[:-1] if action_id == 'primary' else ('alternative',)
        before = self.state
        observed_errors = {}
        for channel in channels:
            fields = FIELDS[channel]
            if action_id == 'alternative':
                fields += tuple(name for name in ('fallback_harm', 'fallback_rights', 'fallback_consent')
                                if hasattr(initial, name) and hasattr(observed, name))
            error = max(abs(float(getattr(initial, f))-float(getattr(observed, f))) for f in fields)
            self.errors[channel] = (1-self.params['alpha'])*self.errors[channel]+self.params['alpha']*error
            observed_errors[channel] = error
        action = next(a for a in frame.situation.candidates if a.id == action_id)
        outcomes = self.forecast(frame, observed, action)
        context = replace(frame.context, evidence_reliability=1-max(observed_errors.values()))
        appraisal = appraise(frame.situation, action, outcomes, context)
        self.state = self.mapping.update(self.state, appraisal, self.config)
        self.counts['state_updates'] += 1
        self.seen += 1
        return {'action_id': action_id, 'observed': to_dict(observed), 'observable_channels': channels,
                'errors': observed_errors, 'ema': dict(self.errors), 'appraisal': to_dict(appraisal),
                'before': to_dict(before), 'after': to_dict(self.state)}

    def choose(self, frame, ordinal, offset=0):
        if not self.sensitive:
            return super().choose(frame, ordinal, offset)
        current = signature(self.decide(frame, frame.initial, virtual=True))
        sensitivity, outcomes = {}, {}
        # A hypothetical decision is a model computation, never an executed action.
        for channel, answers in ANSWERS.items():
            signatures = [signature(self.decide(frame, replace(frame.initial, **answer), virtual=True))
                          for answer in answers]
            sensitivity[channel] = sum(s != current for s in signatures)/len(signatures)
            outcomes[channel] = signatures
        base = {ch: self.params['cue_weight']*frame.cues[i]+self.params['error_weight']*self.errors[ch]
                for i, ch in enumerate(CHANNELS)}
        scores = {ch: base[ch]*(.25+.75*sensitivity[ch]) for ch in CHANNELS}
        order = [CHANNELS[(i+offset+ordinal) % len(CHANNELS)] for i in range(len(CHANNELS))]
        chosen = max(order, key=lambda ch: scores[ch])
        return chosen, {'reason': 'fixed decision-sensitivity weighting of cues and observed errors',
                        'scores': scores, 'base_scores': base, 'sensitivity': sensitivity,
                        'hypothetical_signatures': outcomes, 'privileged_information': False}

    def rule_decide(self, frame, evidence):
        # Direct scalar rules: no forecast generation, state-based control, or
        # hypothetical evaluations. Uses the same public evidence and catalog.
        primary = next(a for a in frame.situation.candidates if a.id == 'primary')
        harm = evidence.harm if evidence.exposed or not evidence.reversible else .02
        def verdict(h, r, c, rev, u):
            if u >= .65:
                return DecisionKind.ASK_HUMAN
            if r >= .8 or c >= .8 or (h >= .8 and rev <= .2):
                return DecisionKind.BLOCK
            if h >= .5 or r >= .4 or c >= .4:
                return DecisionKind.ASK_HUMAN
            return DecisionKind.ALLOW
        values = [(primary, verdict(harm, evidence.rights, evidence.consent,
                                    .95 if evidence.reversible else .1, evidence.uncertainty))]
        for action in frame.situation.candidates:
            if action.id == 'alternative':
                values.append((action, verdict(getattr(evidence, 'fallback_harm', 0.),
                    getattr(evidence, 'fallback_rights', 0.), getattr(evidence, 'fallback_consent', 0.),
                    getattr(evidence, 'fallback_reversibility', .95),
                    evidence.uncertainty if evidence.alternative else 1.)))
        allowed = [a for a, v in values if v == DecisionKind.ALLOW]
        chosen = max(allowed, key=lambda a: (a.task_utility, a.id)) if allowed else None
        kind = (DecisionKind.ALLOW if chosen == primary else DecisionKind.MODIFY) if chosen else (
            DecisionKind.ASK_HUMAN if any(v == DecisionKind.ASK_HUMAN for _, v in values) else DecisionKind.BLOCK)
        return Decision(kind, primary, chosen, (), ('Direct scalar rules on public evidence.',))

    def decide(self, frame, evidence, final_override=None, *, virtual=False):
        self.counts['virtual_decisions' if virtual else 'decisions'] += 1
        self.last_issues, self.last_policies = [], []
        if self.research_variant == 'rule':
            return self.rule_decide(frame, evidence)
        use_concern = self.switch.final if final_override is None else final_override
        use_concern = use_concern and self.config.concern_enabled
        plan = control_plan(self.state, replace(self.config, concern_enabled=use_concern))
        primary = max(frame.situation.candidates, key=lambda a: (a.task_utility, a.id))
        assessments = []
        for action in frame.situation.candidates:
            if action.id != primary.id and self.research_variant == 'combined_no_alternatives':
                continue
            outcomes = self.forecast(frame, evidence, action)
            evaluation = MoralEvaluator().evaluate(frame.situation, outcomes)
            self.counts['stakeholder_checks'] += 1
            if action.id != primary.id:
                self.counts['alternative_candidates'] += 1
            uncertainty_limit = plan.uncertainty_limit
            local_concern = None
            if self.scoped and action.id != primary.id and use_concern:
                own = appraise(frame.situation, action, outcomes, frame.context)
                own_state = self.mapping.update(AffectState(), own, self.config)
                local_concern = own_state.concern
                uncertainty_limit = control_plan(own_state, self.config).uncertainty_limit
            nonuser = {s.id for s in frame.situation.stakeholders if s.role != 'user'}
            exposed = any(max(i.harm, i.rights, i.consent, i.fairness) > .1
                          for o in outcomes for i in o.impacts if i.stakeholder_id in nonuser)
            policy = replace(MoralPolicy(), uncertainty_limit=uncertainty_limit,
                review_harm=plan.irreversible_review_harm if evaluation.reversibility < .5 else .5,
                review_rights=plan.third_party_review_rights if exposed else .4)
            self.last_policies.append({'action': action.id, 'policy': to_dict(policy),
                                       'local_concern': local_concern, 'persistent_concern': self.state.concern})
            assessments.append(ActionAssessment(action, outcomes, analyze(frame.situation, outcomes),
                                                evaluation, judge(evaluation, policy)))
        decision = select(tuple(assessments))
        if plan.prefer_reversible:
            allowed = [a for a in assessments if a.verdict == DecisionKind.ALLOW]
            if allowed:
                chosen = min(allowed, key=lambda a: (a.evaluation.harm*(1-a.evaluation.reversibility),
                                                     -a.action.task_utility, a.action.id))
                if chosen.action != decision.selected_action:
                    decision = replace(decision, selected_action=chosen.action,
                        kind=DecisionKind.ALLOW if chosen.action == decision.proposed_action else DecisionKind.MODIFY)
        return decision
