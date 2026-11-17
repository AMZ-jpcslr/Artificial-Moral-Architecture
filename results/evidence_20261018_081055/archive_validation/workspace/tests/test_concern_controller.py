"""Concern-specific causal isolation and family-level inference; no heldout data."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from moral_agent.affect.appraisal import AffectState, AppraisalContext
from moral_agent.concern_information.controller import Controller
from moral_agent.concern_information.world import PublicFrame, Evidence, CHANNELS
from moral_agent.concern_information.statistics import summarize, comparisons
from moral_agent.models import Situation, Action, ActionKind, DecisionKind


def frame(evidence=None):
    situation = Situation('Test operation', (
        Action('primary', 'Proposed action', ActionKind.UNKNOWN, .9),
        Action('alternative', 'Fallback', ActionKind.UNKNOWN, .7)))
    return PublicFrame(situation, evidence or Evidence(), (.2, .7, .3, .1, .2),
                       CHANNELS, .25, AppraisalContext())


class ConcernControllerTests(unittest.TestCase):
    def test_off_preserves_other_affects_and_history(self):
        f = frame(Evidence(harm=.9, reversible=False))
        off, state = Controller('off'), Controller('state')
        for c in (off, state):
            c.observe(f, 'primary', Evidence(harm=.02, alternative=False))
            c.prepare(f)
        self.assertEqual(off.errors, state.errors)
        self.assertEqual(off.seen, state.seen)
        self.assertEqual(off.state.concern, 0.)
        self.assertGreater(state.state.concern, 0.)
        for axis in ('empathy', 'anticipated_guilt', 'trust', 'gratitude', 'prosocial_satisfaction'):
            self.assertEqual(getattr(off.state, axis), getattr(state.state, axis))
        self.assertGreater(off.state.empathy, 0.)
        self.assertGreater(off.state.anticipated_guilt, 0.)

    def test_state_only_matches_off_selection_and_decision(self):
        off, state = Controller('off'), Controller('state')
        for f in (frame(Evidence(harm=.9, reversible=False)), frame(Evidence(uncertainty=.55)), frame()):
            for c in (off, state):
                c.prepare(f)
            self.assertEqual(off.choose(f, 0), state.choose(f, 0))
            self.assertEqual(off.decide(f, f.initial), state.decide(f, f.initial))

    def test_final_switch_does_not_change_selection(self):
        f = frame()
        state, final = Controller('state'), Controller('final')
        for c in (state, final):
            c.state = AffectState(concern=1., empathy=.4, anticipated_guilt=.4)
            c.errors['rights_consent'] = .5
        self.assertEqual(state.choose(f, 0), final.choose(f, 0))

    def test_selection_switch_does_not_change_same_evidence_decision(self):
        f = frame(Evidence(uncertainty=.55))
        state, select = Controller('state'), Controller('select')
        for c in (state, select):
            c.state = AffectState(concern=1.)
        self.assertNotEqual(state.choose(f, 0)[0], select.choose(f, 0)[0])
        self.assertEqual(state.decide(f, f.initial), select.decide(f, f.initial))

    def test_error_changes_trust_but_not_concern_with_identical_observation(self):
        a, b = Controller('state'), Controller('state')
        observed = Evidence(harm=.02, alternative=False)
        a.observe(frame(Evidence(harm=.02)), 'primary', observed)
        b.observe(frame(Evidence(harm=.9)), 'primary', observed)
        self.assertEqual(a.state.concern, b.state.concern)
        self.assertEqual(a.state.empathy, b.state.empathy)
        self.assertNotEqual(a.state.trust, b.state.trust)
        self.assertNotEqual(a.errors, b.errors)

    def test_concern_final_threshold_causality_at_uncertainty_point55(self):
        f = frame(Evidence(uncertainty=.55))
        c = Controller('both')
        c.state = AffectState(concern=1.)
        self.assertEqual(c.decide(f, f.initial, final_override=False).kind, DecisionKind.ALLOW)
        self.assertEqual(c.decide(f, f.initial, final_override=True).kind, DecisionKind.ASK_HUMAN)

    def test_reset_clears_all_state_and_errors(self):
        c = Controller('both')
        c.observe(frame(), 'primary', Evidence(harm=.9, reversible=False))
        c.reset()
        self.assertEqual(c.state, AffectState())
        self.assertEqual(c.errors, dict.fromkeys(CHANNELS, 0.))
        self.assertEqual(c.seen, 0)

    def test_primary_feedback_ignores_alternative_sentinel(self):
        a, b = Controller('both'), Controller('both')
        f = frame()
        ra = a.observe(f, 'primary', Evidence(alternative=False))
        rb = b.observe(f, 'primary', Evidence(alternative=True))
        self.assertEqual(a.errors, b.errors)
        self.assertEqual(a.state, b.state)
        self.assertNotIn('alternative', ra['errors'])
        self.assertEqual(ra['appraisal'], rb['appraisal'])

    def test_alternative_feedback_updates_only_alternative_error(self):
        c = Controller('both')
        c.observe(frame(), 'alternative', Evidence(harm=.9, rights=.9, consent=.9, alternative=False))
        self.assertEqual(c.errors['alternative'], .5)
        self.assertTrue(all(c.errors[ch] == 0. for ch in CHANNELS[:-1]))

    def test_default_mapping_and_parameters_not_tuned_by_variant(self):
        f = frame(Evidence(harm=.9, reversible=False))
        a, b = Controller('state'), Controller('both')
        self.assertEqual(a.params, b.params)
        self.assertEqual(a.config, b.config)
        self.assertEqual(a.prepare(f)['after'], b.prepare(f)['after'])

    def test_hard_rights_constraint_and_per_outcome_trace_retained(self):
        f = frame(Evidence(rights=.9))
        for variant in ('off', 'state', 'select', 'final', 'both'):
            c = Controller(variant)
            c.prepare(f)
            decision = c.decide(f, f.initial)
            primary = next(a for a in decision.assessments if a.action.id == 'primary')
            self.assertEqual(primary.verdict, DecisionKind.BLOCK)
            self.assertGreaterEqual(len(primary.outcomes), 2)
            self.assertTrue(all(len(o.impacts) == len(f.situation.stakeholders) for o in primary.outcomes))
            self.assertNotEqual(decision.selected_action.id, 'primary')


class ConcernStatisticsTests(unittest.TestCase):
    def rows(self):
        return [dict(split='development', experiment='II', mode='relevant', accuracy=.8,
                     budget=4, variant=v, family=f, seed=s, safe_task_success=x,
                     checks=4., over_refusal=None)
                for f, effect in [('a', .1), ('b', .3), ('c', -.1)]
                for s in (1, 2) for v, x in [('history', .4), ('select', .4+effect)]]

    def effect(self, rows):
        return next(r for r in comparisons(rows, 100)
                    if r['left_variant'] == 'select' and r['right_variant'] == 'history'
                    and r['metric'] == 'safe_task_success')

    def test_duplicate_seed_replicates_do_not_inflate_clusters_or_ci(self):
        rows = self.rows()
        a = self.effect(rows)
        b = self.effect(rows + [dict(r, seed=r['seed']+10) for r in rows])
        for key in ('difference', 'ci_low', 'ci_high', 'clusters', 'family_effects'):
            self.assertEqual(a[key], b[key])
        self.assertEqual(a['clusters'], 3)

    def test_leave_one_family_out_reports_every_omission(self):
        r = self.effect(self.rows())
        self.assertEqual({x['omitted_family'] for x in r['leave_one_family_out']}, {'a', 'b', 'c'})
        self.assertAlmostEqual(r['leave_one_family_out_min'], 0.)
        self.assertAlmostEqual(r['leave_one_family_out_max'], .2)

    def test_missing_pairs_are_reported_and_not_imputed(self):
        rows = self.rows()
        rows = [r for r in rows if not (r['family']=='a' and r['seed']==1 and r['variant']=='history')]
        r = self.effect(rows)
        self.assertEqual(r['unmatched_left'], 1)
        self.assertEqual(r['paired_episodes'], 5)

    def test_information_and_assignment_mode_comparisons(self):
        rows = []
        for experiment in ('I', 'assignment'):
            for mode in ('relevant', 'repeat', 'irrelevant', 'none'):
                for f in ('a', 'b'):
                    rows.append(dict(split='development', experiment=experiment, mode=mode,
                                     accuracy=.8, budget=0 if mode=='none' else 4,
                                     variant='off', family=f, seed=1, safe_task_success=.5))
        out = comparisons(rows, 20)
        pairs = {(r['experiment'], r['left_mode'], r['right_mode']) for r in out}
        self.assertIn(('I', 'relevant', 'irrelevant'), pairs)
        self.assertIn(('I', 'relevant', 'repeat'), pairs)
        self.assertIn(('I', 'relevant', 'none'), pairs)
        self.assertIn(('assignment', 'relevant', 'none'), pairs)

    def test_undefined_denominators_and_splits_stay_separate(self):
        rows = self.rows()
        out = summarize(rows + [dict(r, split='separate') for r in rows])
        self.assertEqual(len(out), 4)
        self.assertTrue(all(r['over_refusal'] is None for r in out))
        self.assertTrue(all(r['over_refusal_defined_episodes']==0 for r in out))


if __name__ == '__main__':
    unittest.main()
