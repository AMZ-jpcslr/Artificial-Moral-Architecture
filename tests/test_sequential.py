"""Information boundaries, temporal credit, budgets, controls and grouped inference."""
from dataclasses import fields, replace
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from moral_agent.affect.appraisal import AffectState
from moral_agent.models import to_dict
from moral_agent.sequential.environment import CurrentInput, build_episode, feedback, QueryBudget
from moral_agent.sequential.controller import Controller, decide, METHODS
from moral_agent.sequential.causal import causal_probes
from moral_agent.sequential.runner import (validate, run_episode, environments, tune,
    cluster_ci, grouped_summary, run, audit_existing)


class SequentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT/'experiments/v02x_config.json').read_text(encoding='utf-8'))
        cls.family = cls.config['families'][0]
        cls.worlds = build_episode(cls.family, 11, 'persistent', 'new', cls.config)

    def test_public_input_has_no_labels_seed_or_hidden_state(self):
        self.assertEqual({f.name for f in fields(CurrentInput)}, {'situation', 'predictions', 'context'})
        keys = json.dumps(to_dict(self.worlds[0].current))
        for field in ('primary_harmful', 'prediction_error', 'diagnostic_accuracy', 'available_step', 'seed'):
            self.assertNotIn(field, keys)

    def test_current_input_equal_across_information_conditions(self):
        repeat = build_episode(self.family, 11, 'persistent', 'repeat', self.config)
        self.assertEqual([w.current for w in self.worlds], [w.current for w in repeat])

    def test_query_answers_not_method_dependent(self):
        self.assertEqual(self.worlds, build_episode(self.family, 11, 'persistent', 'new', self.config))
        for method in METHODS:
            _, rows, _ = run_episode(self.worlds, method, 4)
            for w, row in zip(self.worlds, rows):
                self.assertEqual(row['diagnostic_received'], to_dict(w.diagnostic) if row['checks'] else None)

    def test_repeat_diagnostic_is_exact_initial_prediction(self):
        for w in build_episode(self.family, 11, 'persistent', 'repeat', self.config):
            self.assertEqual(w.diagnostic, dict(w.current.predictions)['primary'])
            self.assertEqual(decide(w.current), decide(w.current, w.diagnostic))

    def test_hidden_truth_does_not_change_current_allocation(self):
        world = self.worlds[0]
        changed = replace(world, primary_harmful=not world.primary_harmful, prediction_error=not world.prediction_error,
                          actual=tuple(reversed(world.actual)))
        for method in METHODS:
            a, b = Controller(method), Controller(method)
            self.assertEqual(a.allocate(world.current, 0, 4, 4, 8), b.allocate(changed.current, 0, 4, 4, 8))

    def test_future_world_change_cannot_change_earlier_decisions(self):
        changed = self.worlds[:4] + tuple(replace(w, diagnostic=self.worlds[0].diagnostic) for w in self.worlds[4:])
        for method in METHODS:
            _, a, _ = run_episode(self.worlds, method, 4)
            _, b, _ = run_episode(changed, method, 4)
            self.assertEqual(a[:4], b[:4])

    def test_feedback_only_selected_action(self):
        world = next(w for w in self.worlds if len(w.current.situation.candidates) > 1)
        obs = feedback(world, 'alternative', 2)
        self.assertEqual(obs.action.id, 'alternative')
        self.assertEqual(obs.observed, dict(world.actual)['alternative'])
        self.assertNotIn('primary', [obs.action.id])
        self.assertIsNone(feedback(world, None, 2))

    def test_feedback_arrival_time_enforced(self):
        obs = feedback(self.worlds[0], 'primary', 2)
        c = Controller('history')
        with self.assertRaises(ValueError):
            c.observe(obs, 2)
        c.observe(obs, 3)
        self.assertEqual(c.observations, 1)

    def test_feedback_delivered_before_next_decision_all_methods(self):
        for method in METHODS:
            _, rows, last = run_episode(self.worlds, method, 4)
            self.assertIsNone(rows[0]['delivered_feedback'])
            for previous, current in zip(rows, rows[1:]):
                observation = current['delivered_feedback']
                if previous['selected_action'] is None:
                    self.assertIsNone(observation)
                else:
                    self.assertEqual(observation['observation']['action']['id'], previous['selected_action'])
                    self.assertEqual(observation['observation']['available_step'], current['step'])

    def test_query_budget_and_step_cap_enforced(self):
        budget = QueryBudget(2)
        budget.query(0, ())
        with self.assertRaises(RuntimeError):
            budget.query(0, ())
        budget.query(1, ())
        with self.assertRaises(RuntimeError):
            budget.query(2, ())
        for method in METHODS:
            for cap in (0, 2, 4):
                s, rows, _ = run_episode(self.worlds, method, cap)
                self.assertLessEqual(s['checks'], cap)
                self.assertEqual(s['checks']+s['unused_budget'], cap)
                self.assertTrue(all(r['checks'] <= 1 for r in rows))

    def test_zero_budget_matches_no_check_all_methods(self):
        _, base, _ = run_episode(self.worlds, 'no_check', 0)
        for method in METHODS:
            _, rows, _ = run_episode(self.worlds, method, 0)
            self.assertEqual([r['selected_action'] for r in rows], [r['selected_action'] for r in base])

    def test_episode_reset_and_reproducibility(self):
        for method in METHODS:
            a, rows_a, end_a = run_episode(self.worlds, method, 4)
            b, rows_b, end_b = run_episode(self.worlds, method, 4)
            self.assertEqual(rows_a, rows_b)
            a.pop('runtime_seconds'); b.pop('runtime_seconds')
            self.assertEqual(a, b)
            self.assertEqual(end_a, end_b)
        c = Controller('affect')
        c.observe(feedback(self.worlds[0], 'primary', 0), 1)
        c.reset()
        self.assertEqual((c.state, c.ema, c.observations), (AffectState(), 0., 0))

    def test_state_only_generates_state_but_no_intervention(self):
        a, rows, _ = run_episode(self.worlds, 'affect_only', 4)
        _, baseline, _ = run_episode(self.worlds, 'no_check', 4)
        self.assertEqual(a['checks'], 0)
        self.assertEqual([r['decision'] for r in rows], [r['decision'] for r in baseline])
        self.assertTrue(any(r['allocation']['affect_after']['concern'] > 0 for r in rows))

    def test_history_ema_uses_observed_prediction_error(self):
        c = Controller('history', {'alpha': .5, 'weight': 1., 'threshold': .3})
        obs = feedback(self.worlds[0], 'primary', 0)
        record = c.observe(obs, 1)
        self.assertAlmostEqual(c.ema, .5*record['observed_error'])
        c.observe(obs, 2)
        self.assertAlmostEqual(c.ema, .75*record['observed_error'])

    def test_history_reset_holds_parameters_fixed(self):
        params = {'alpha': .8, 'weight': 2., 'threshold': .5}
        c = Controller('history_reset', params)
        c.ema = 1.
        _, trace = c.allocate(self.worlds[0].current, 2, 4, 4, 8)
        self.assertEqual(trace['ema'], 0.)
        self.assertEqual(c.parameters, params)

    def test_regimes_equal_error_frequency_and_truth(self):
        shuffled = build_episode(self.family, 11, 'shuffled', 'new', self.config)
        self.assertEqual(sum(w.prediction_error for w in self.worlds), 4)
        self.assertEqual(sum(w.prediction_error for w in shuffled), 4)
        self.assertEqual([w.actual for w in self.worlds], [w.actual for w in shuffled])
        self.assertEqual([w.diagnostic for w in self.worlds], [w.diagnostic for w in shuffled])

    def test_causal_error_only_changes_trust_not_active_states(self):
        rows = causal_probes()
        for target in ('hidden_harm', 'safe_uncertain'):
            matches = {r['history']: r for r in rows if r['target'] == target and r['information'] == 'repeat' and r['method'] == 'affect'}
            a, b = matches['accurate_safe'], matches['error_only']
            for axis in ('concern', 'empathy', 'anticipated_guilt'):
                self.assertEqual(a['trace']['affect_after'][axis], b['trace']['affect_after'][axis])
            self.assertNotEqual(a['trace']['affect_after']['trust'], b['trace']['affect_after']['trust'])
            self.assertEqual((a['actual_checks'], a['decision']), (b['actual_checks'], b['decision']))

    def test_causal_observed_harm_changes_control_and_reset_removes_it(self):
        matches = {(r['history'], r['method']): r for r in causal_probes()
                   if r['target'] == 'hidden_harm' and r['information'] == 'new'}
        low = matches['accurate_safe', 'affect']
        high = matches['missed_harm', 'affect']
        self.assertGreater(high['actual_checks'], low['actual_checks'])
        self.assertNotEqual(high['decision'], low['decision'])
        self.assertEqual(matches['missed_harm', 'affect_reset']['actual_checks'], low['actual_checks'])
        self.assertEqual(matches['missed_harm', 'affect_only']['actual_checks'], 0)

    def test_grouped_ci_not_inflated_by_duplicate_seeds(self):
        a = cluster_ci({'a': [0., .2], 'b': [.2, .4]}, 100, 17)
        b = cluster_ci({'a': [0., .2]*10, 'b': [.2, .4]*10}, 100, 17)
        self.assertEqual(a, b)
        self.assertEqual(a['clusters'], 2)
        self.assertAlmostEqual(a['difference'], .2)
        self.assertIsNone(cluster_ci({'one': [.1]}, 100, 17)['ci_low'])

    def test_episode_metrics_and_overrefusal_denominator(self):
        summary, rows, _ = run_episode(self.worlds, 'no_check', 0)
        self.assertEqual(summary['safe_task_success'], sum(r['safe_task_success'] for r in rows)/8)
        n = sum(r['safe_available'] for r in rows)
        self.assertEqual(summary['over_refusal'], sum(r['over_refusal'] for r in rows)/n if n else None)

    def test_split_validation_and_tuning_ignores_heldout(self):
        config = self.tiny_config()
        original = tune(config)
        changed = copy.deepcopy(config)
        for f in changed['families']:
            if f['split'] == 'heldout':
                f['hazard_rate'] = 1-f['hazard_rate']
        self.assertEqual(tune(changed), original)
        changed['families'][1]['id'] = changed['families'][0]['id']
        with self.assertRaises(ValueError):
            validate(changed)

    def tiny_config(self):
        config = copy.deepcopy(self.config)
        config.update(seeds=[11], budgets=[0, 2], bootstrap_samples=20,
                      current_thresholds=[.3], history_alphas=[.5], history_weights=[1.])
        config['families'] = [config['families'][0], *config['families'][4:6]]
        return config

    def test_existing_recovery_audit(self):
        self.assertTrue(audit_existing(ROOT)['identical_13'])

    def test_runner_outputs_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'run'
            summary, pairs = run(self.tiny_config(), output)
            for name in ('config.json', 'metadata.json', 'existing_audit.json', 'causal_probes.json',
                         'frozen_parameters.json', 'development_tuning.json', 'episodes.csv', 'summary.csv',
                         'paired_ci.csv', 'summary.json', 'decisions.jsonl.gz', 'console.txt'):
                self.assertTrue((output/name).is_file())
            with gzip.open(output/'decisions.jsonl.gz', 'rt', encoding='utf-8') as stream:
                rows = [json.loads(line) for line in stream]
            self.assertTrue(any('delivered_feedback' in r for r in rows))
            self.assertEqual(len(summary), 2*2*2*len(METHODS))
            self.assertTrue(all(p['clusters'] <= 2 for p in pairs))
            self.assertTrue(json.loads((output/'metadata.json').read_text())['preserved_unchanged'])
            with self.assertRaises(FileExistsError):
                run(self.tiny_config(), output)


if __name__ == '__main__':
    unittest.main()
