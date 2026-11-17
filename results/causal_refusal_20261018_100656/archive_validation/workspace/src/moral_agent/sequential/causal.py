"""Probe the UNCHANGED full AffectAgent before the isolated allocation experiment."""
from ..affect.agent import AffectAgent
from ..affect.appraisal import AffectConfig, AppraisalContext
from ..models import Action, ActionKind, Situation, to_dict
from .environment import forecast, QueryBudget


class NoAlternatives:
    def alternatives(self, situation, action):
        return ()


class ProbePredictor:
    def __init__(self, initial, extra):
        self.initial, self.extra = initial, extra
        self.calls = 0
        self.budget = QueryBudget(1)

    def predict(self, situation, action):
        self.calls += 1
        return self.initial if self.calls == 1 else self.budget.query(0, self.extra)


def causal_probes():
    rows = []
    action = Action('primary', 'Perform an operation', ActionKind.UNKNOWN, .95)
    situation = Situation('Complete the operation', (action,), context='Controlled history intervention')
    for target in ('hidden_harm', 'safe_uncertain'):
        initial = forecast(situation, .02, .95, .15 if target == 'hidden_harm' else .55, 'Current estimate')
        new = forecast(situation, .9 if target == 'hidden_harm' else .02,
                       .1 if target == 'hidden_harm' else .95, .15, 'Follow-up measurement')
        for information in ('new', 'repeat'):
            for history in ('accurate_safe', 'error_only', 'missed_harm'):
                # Same observed outcome in first two histories; only reliability differs.
                observed = forecast(situation, .9 if history == 'missed_harm' else 0.,
                                    .1 if history == 'missed_harm' else 1., 0., 'Previously observed chosen action')
                previous_prediction = forecast(situation, .9 if history == 'error_only' else 0.,
                    .1 if history == 'error_only' else 1., .15, 'Prediction made before the past chosen action')
                observed_error = abs(previous_prediction[0].severity-observed[0].severity)
                for method in ('affect', 'affect_reset', 'affect_only'):
                    cfg = AffectConfig(persistence=method != 'affect_reset', behavior_enabled=method != 'affect_only')
                    provider = ProbePredictor(initial, new if information == 'new' else initial)
                    agent = AffectAgent(provider, NoAlternatives(), cfg)
                    agent.reset_episode()
                    history_trace = []
                    # Identical remaining budget; observations precede this probe decision.
                    for _ in range(2):
                        history_trace.append({'previous_prediction': to_dict(previous_prediction),
                            'observed_error': observed_error,
                            'update': to_dict(agent.observe(situation, action, observed,
                                AppraisalContext(evidence_reliability=1-observed_error)))})
                    run = agent.step(situation)
                    rows.append({'target': target, 'information': information, 'history': history,
                        'method': method, 'remaining_before': 1, 'actual_checks': 1-provider.budget.remaining,
                        'selected_action': run.decision.selected_action.id if run.decision.selected_action else None,
                        'decision': run.decision.kind.value, 'history_trace': to_dict(history_trace),
                        'trace': to_dict(run),
                        'interpretation': 'error_only holds observed outcomes fixed; missed_harm also changes harm experience'})
    return rows
