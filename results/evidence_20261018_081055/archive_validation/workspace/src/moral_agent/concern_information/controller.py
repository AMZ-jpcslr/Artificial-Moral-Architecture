"""Concern-only intervention switches; no world/evaluator access in this module."""
from dataclasses import dataclass, replace
from ..models import ActionAssessment, DecisionKind, to_dict
from ..moral_evaluation import MoralEvaluator, MoralPolicy
from ..judgment import judge, select
from ..stakeholders import analyze
from ..prediction_validation.providers import make_prediction
from ..affect.appraisal import AffectConfig, AffectState, DeterministicMapping, appraise
from ..affect.agent import control_plan
from .world import CHANNELS, FIELDS


@dataclass(frozen=True)
class Switches:
    state: bool = False
    selection: bool = False
    final: bool = False


def switches(variant):
    return {'off': Switches(), 'uniform': Switches(), 'current': Switches(), 'history': Switches(),
            'state': Switches(True), 'select': Switches(True, True),
            'final': Switches(True, False, True), 'both': Switches(True, True, True)}[variant]


def predictions(frame, evidence, action_id):
    if action_id == 'alternative':
        return make_prediction(frame.situation, 'Fallback feasibility estimate', harm=0., fairness=0.,
            uncertainty=evidence.uncertainty if evidence.alternative else 1., reversibility=.95)
    effective_harm = evidence.harm if evidence.exposed or not evidence.reversible else .02
    return make_prediction(frame.situation, 'Current causal-component estimates', harm=effective_harm,
        rights=evidence.rights, consent=evidence.consent, fairness=0.,
        reversibility=.95 if evidence.reversible else .1, uncertainty=evidence.uncertainty)


class Controller:
    def __init__(self, variant, params=None):
        self.variant, self.switch = variant, switches(variant)
        self.params = params or {'cue_weight': 1., 'error_weight': .5, 'alpha': .5}
        # Disable only Concern. Other affect states, their controls and memory stay.
        self.config = AffectConfig(concern_enabled=self.switch.state)
        self.mapping = DeterministicMapping()
        self.reset()

    def reset(self):
        self.state = AffectState()
        self.errors = dict.fromkeys(CHANNELS, 0.)
        self.seen = 0

    def observe(self, frame, action_id, observed):
        if observed is None:
            return None
        initial = frame.initial
        channels = CHANNELS[:-1] if action_id == 'primary' else ('alternative',)
        before = self.state
        observed_errors = {}
        for channel in channels:
            error = max(abs(float(getattr(initial, f))-float(getattr(observed, f))) for f in FIELDS[channel])
            alpha = self.params['alpha']
            self.errors[channel] = (1-alpha)*self.errors[channel]+alpha*error
            observed_errors[channel] = error
        action = next(a for a in frame.situation.candidates if a.id == action_id)
        # The alternative=False sentinel on primary feedback is never appraised as a failed fallback.
        outcome = predictions(frame, observed, action_id)
        context = replace(frame.context, evidence_reliability=1-max(observed_errors.values()))
        appraisal = appraise(frame.situation, action, outcome, context)
        self.state = self.mapping.update(self.state, appraisal, self.config)
        self.seen += 1
        return {'action_id': action_id, 'observed': to_dict(observed), 'observable_channels': channels,
                'errors': observed_errors, 'ema': dict(self.errors), 'appraisal': to_dict(appraisal),
                'before': to_dict(before), 'after': to_dict(self.state)}

    def prepare(self, frame):
        before = self.state
        appraisal = appraise(frame.situation, frame.situation.candidates[0],
                            predictions(frame, frame.initial, 'primary'), frame.context)
        self.state = self.mapping.update(self.state, appraisal, self.config)
        # Diagnostic plan shows what the unmodified Concern would request.
        requested = control_plan(self.state, self.config)
        return {'before': to_dict(before), 'after': to_dict(self.state), 'appraisal': to_dict(appraisal),
                'requested_plan': to_dict(requested), 'ema': dict(self.errors), 'observations_seen': self.seen,
                'switches': to_dict(self.switch)}

    def choose(self, frame, ordinal, offset=0):
        if self.variant == 'uniform':
            channel = CHANNELS[(ordinal+offset) % len(CHANNELS)]
            return channel, {'reason': 'external uniform rotation', 'scores': None}
        history = self.variant != 'current'
        base = {ch: self.params['cue_weight']*frame.cues[i] +
                (self.params['error_weight']*self.errors[ch] if history else 0.) for i, ch in enumerate(CHANNELS)}
        scores = dict(base)
        active = self.switch.selection and self.state.concern >= self.config.concern_threshold
        if active:
            # EXPLORATORY channel-ranking path. No such ranking exists in v0.2.
            focus = {'harm': 1., 'rights_consent': 0., 'stakeholders': 0., 'reversibility': 1., 'alternative': .5}
            for ch in scores:
                scores[ch] += self.state.concern*focus[ch]
        order = [CHANNELS[(i+offset+ordinal) % len(CHANNELS)] for i in range(len(CHANNELS))]
        channel = max(order, key=lambda ch: scores[ch])
        base_channel = max(order, key=lambda ch: base[ch])
        return channel, {'reason': 'current cues + observed error EMA' + (' + exploratory Concern focus' if active else ''),
                         'scores': scores, 'base_scores': base, 'base_channel': base_channel,
                         'concern_changed_channel': channel != base_channel, 'concern_active': active}

    def decide(self, frame, evidence, final_override=None):
        use_concern = self.switch.final if final_override is None else final_override
        plan = control_plan(self.state, replace(self.config, concern_enabled=use_concern))
        assessments = []
        for action in frame.situation.candidates:
            outcomes = predictions(frame, evidence, action.id)
            evaluation = MoralEvaluator().evaluate(frame.situation, outcomes)
            nonuser = {s.id for s in frame.situation.stakeholders if s.role != 'user'}
            exposed = any(max(i.harm, i.rights, i.consent, i.fairness) > .1 for o in outcomes for i in o.impacts if i.stakeholder_id in nonuser)
            policy = replace(MoralPolicy(), uncertainty_limit=plan.uncertainty_limit,
                review_harm=plan.irreversible_review_harm if evaluation.reversibility < .5 else .5,
                review_rights=plan.third_party_review_rights if exposed else .4)
            assessments.append(ActionAssessment(action, outcomes, analyze(frame.situation, outcomes), evaluation, judge(evaluation, policy)))
        decision = select(tuple(assessments))
        if plan.prefer_reversible:
            allowed = [a for a in assessments if a.verdict == DecisionKind.ALLOW]
            if allowed:
                chosen = min(allowed, key=lambda a: (a.evaluation.harm*(1-a.evaluation.reversibility), -a.action.task_utility, a.action.id))
                if chosen.action != decision.selected_action:
                    decision = replace(decision, selected_action=chosen.action,
                        kind=DecisionKind.ALLOW if chosen.action == decision.proposed_action else DecisionKind.MODIFY)
        return decision
