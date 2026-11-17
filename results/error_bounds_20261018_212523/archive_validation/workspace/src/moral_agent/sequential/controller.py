"""Allocation only: all conditions share appraisal and the unchanged decision policy.

No family id, seed, hidden regime, labels or unselected outcomes enter this API.
"""
from dataclasses import replace

from ..affect.appraisal import AffectConfig, AffectState, DeterministicMapping, appraise
from ..affect.agent import control_plan
from ..moral_evaluation import MoralEvaluator, MoralPolicy
from ..models import ActionAssessment, to_dict
from ..stakeholders import analyze
from ..judgment import judge, select

METHODS = ('no_check', 'uniform', 'current', 'history', 'affect', 'affect_reset', 'affect_only', 'history_reset')


def current_score(a):
    """Identical full set of relevant current features is available to B and C."""
    return max(a.probability_weighted_harm, a.uncertainty, a.norm_violation,
               a.irreversible_risk, a.stakeholder_coverage_gap,
               a.stakeholder_vulnerability*a.third_party_exposure)


class Controller:
    def __init__(self, method, parameters=None):
        if method not in METHODS:
            raise ValueError('unknown method')
        self.method = method
        self.parameters = parameters or {'threshold': .3, 'alpha': .5, 'weight': 1.}
        self.config = AffectConfig(persistence=method != 'affect_reset',
                                   behavior_enabled=method != 'affect_only')
        self.mapping = DeterministicMapping()
        self.reset()

    def reset(self):
        self.state, self.ema = AffectState(), 0.
        self.observations = 0

    def observe(self, observation, now):
        if observation.available_step > now:
            raise ValueError('feedback not yet observable')
        evaluator = MoralEvaluator()
        error = abs(evaluator.evaluate(observation.situation, observation.forecast).harm -
                    evaluator.evaluate(observation.situation, observation.observed).harm)
        alpha = self.parameters.get('alpha', .5)
        before_ema, before = self.ema, self.state
        self.ema = (1-alpha)*self.ema+alpha*error
        self.observations += 1
        context = replace(observation.context, evidence_reliability=1-error)
        a = appraise(observation.situation, observation.action, observation.observed, context)
        if self.method.startswith('affect'):
            self.state = self.mapping.update(self.state, a, self.config)
        return {'observation': to_dict(observation), 'observed_error': error,
                'ema_before': before_ema, 'ema_after': self.ema,
                'affect_before': to_dict(before), 'affect_after': to_dict(self.state),
                'observed_appraisal': to_dict(a)}

    def allocate(self, current, step, remaining, cap, steps):
        if self.method == 'history_reset':
            self.ema = 0.
        primary = current.situation.candidates[0]
        a = appraise(current.situation, primary, dict(current.predictions)[primary.id], current.context)
        before = self.state
        if self.method.startswith('affect'):
            self.state = self.mapping.update(before, a, self.config)
        plan = control_plan(self.state, self.config)
        score = current_score(a)
        # All possible initial forecasts here are estimates, not certain evidence.
        eligible = a.uncertainty > 0 or a.stakeholder_coverage_gap > 0
        if self.method == 'uniform':
            requested = step in {j*steps//cap for j in range(cap)} if cap else False
        elif self.method in ('current', 'history', 'history_reset'):
            score += self.parameters.get('weight', 1.)*self.ema if self.method.startswith('history') else 0.
            requested = score >= self.parameters['threshold']
        elif self.method in ('affect', 'affect_reset'):
            requested = bool(plan.additional_prediction_rounds or plan.stakeholder_review or plan.causal_review)
        else:
            requested = False
        return bool(requested and eligible and remaining > 0), {
            'appraisal': to_dict(a), 'affect_before': to_dict(before), 'affect_after': to_dict(self.state),
            'control_plan': to_dict(plan), 'ema': self.ema, 'observations_seen': self.observations,
            'current_score': current_score(a), 'allocation_score': score, 'eligible': eligible,
            'requested': bool(requested), 'remaining_before': remaining,
        }


def decide(current, diagnostic=None):
    """Follow-up estimates supersede the same measured proposition, for ALL methods.

    The runner keeps both estimates. This controlled measurement adapter does not
    change v0.2's conservative evidence accumulation or any moral thresholds.
    """
    assessments = []
    for action in current.situation.candidates:
        outcomes = diagnostic if diagnostic is not None and action.id == 'primary' else dict(current.predictions)[action.id]
        evaluation = MoralEvaluator().evaluate(current.situation, outcomes)
        assessments.append(ActionAssessment(action, outcomes, analyze(current.situation, outcomes),
                                           evaluation, judge(evaluation, MoralPolicy())))
    return select(tuple(assessments))
