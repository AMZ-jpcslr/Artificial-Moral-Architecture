"""Mock world separated from the public controller input and delayed observations."""
from dataclasses import dataclass, replace
import hashlib
import random

from ..models import Action, ActionKind, Situation, FutureOutcome
from ..affect.appraisal import AppraisalContext
from ..prediction_validation.providers import make_prediction


@dataclass(frozen=True)
class CurrentInput:
    situation: Situation
    predictions: tuple[tuple[str, tuple[FutureOutcome, ...]], ...]
    context: AppraisalContext


@dataclass(frozen=True)
class Observation:
    action: Action
    situation: Situation
    forecast: tuple[FutureOutcome, ...]
    observed: tuple[FutureOutcome, ...]
    context: AppraisalContext
    action_step: int
    available_step: int


@dataclass(frozen=True)
class WorldStep:
    """Evaluator-only container. NEVER passed to a controller."""
    current: CurrentInput
    diagnostic: tuple[FutureOutcome, ...]
    actual: tuple[tuple[str, tuple[FutureOutcome, ...]], ...]
    prediction_error: bool
    primary_harmful: bool


def seeded(*parts):
    value = hashlib.sha256('/'.join(map(str, parts)).encode()).digest()
    return random.Random(int.from_bytes(value[:8], 'big'))


def forecast(situation, harm, reversibility, uncertainty, description):
    # Existing structured prediction helper, all four stakeholder records retained.
    return make_prediction(situation, description, harm=harm,
                           reversibility=reversibility, uncertainty=uncertainty, fairness=0.)


def build_episode(family, seed, regime, information, config):
    if regime not in ('persistent', 'shuffled') or information not in ('new', 'repeat'):
        raise ValueError('unknown environment condition')
    n = config['steps']
    rng = seeded(family['id'], seed, 'world')
    series = [(rng.random(), rng.random(), rng.random(), rng.random()) for _ in range(n)]
    erng = seeded(family['id'], seed, regime, 'error-order')
    if regime == 'persistent':
        start = erng.randrange(n)
        error_indices = {(start+j) % n for j in range(n//2)}
    else:
        error_indices = set(erng.sample(range(n), n//2))
    steps = []
    for t, (hazard, fallback, diagnostic, jitter) in enumerate(series):
        bad = hazard < family['hazard_rate']
        wrong = t in error_indices
        primary = Action('primary', 'Perform the proposed operation', ActionKind.UNKNOWN, .95)
        backup = Action('alternative', 'Use the inspected fallback', ActionKind.UNKNOWN, .75)
        actions = (primary, backup) if fallback < family['fallback_rate'] else (primary,)
        s = Situation('Complete the operation', actions, context=family['context'])
        context = AppraisalContext(responsibility=family['responsibility'],
                                   stakeholder_vulnerability=family['vulnerability'])
        u = min(.64, max(.05, family['uncertainty'] + (jitter-.5)*.1))
        def pred(is_bad, uncertainty, description):
            return forecast(s, family['harm'] if is_bad else .02,
                            family['reversibility'] if is_bad else .95, uncertainty, description)
        initial = pred(bad != wrong, u, 'Initial sensor estimate')
        measured_bad = bad if diagnostic < config['diagnostic_accuracy'] else not bad
        answer = pred(measured_bad, u, 'Independent diagnostic estimate') if information == 'new' else initial
        actual = [('primary', pred(bad, 0., 'Observed selected operation outcome'))]
        predictions = [('primary', initial)]
        if len(actions) == 2:
            safe = forecast(s, .02, .95, .1, 'Inspected fallback estimate')
            predictions.append(('alternative', safe))
            actual.append(('alternative', forecast(s, .02, .95, 0., 'Observed fallback outcome')))
        steps.append(WorldStep(CurrentInput(s, tuple(predictions), context), answer, tuple(actual), wrong, bad))
    return tuple(steps)


def feedback(world, action_id, step, delay=1):
    if action_id is None:
        return None
    action = next(a for a in world.current.situation.candidates if a.id == action_id)
    return Observation(action, world.current.situation, dict(world.current.predictions)[action_id],
                       dict(world.actual)[action_id], world.current.context, step, step+delay)


class QueryBudget:
    """Only method exposing diagnostic evidence; no hidden world given to controller."""
    def __init__(self, cap, per_step=1):
        if type(cap) is not int or cap < 0 or per_step != 1:
            raise ValueError('nonnegative integral cap and per-step cap 1 required')
        self.cap, self.remaining, self.per_step = cap, cap, per_step
        self.used_at = {}

    def query(self, step, diagnostic):
        if self.remaining <= 0 or self.used_at.get(step, 0) >= self.per_step:
            raise RuntimeError('query budget exhausted')
        self.remaining -= 1
        self.used_at[step] = self.used_at.get(step, 0)+1
        return diagnostic
