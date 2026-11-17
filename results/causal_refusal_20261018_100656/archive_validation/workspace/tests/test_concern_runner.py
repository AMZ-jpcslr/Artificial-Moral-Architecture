"""Development-only integration, exact usage and frozen execution contracts."""
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from moral_agent.concern_information.world import build_episode
from moral_agent.concern_information.runner import run_episode, execute, freeze, source_hashes, validate, tune


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT/'experiments/concern_information_config.json').read_text())
        self.config['families'] = [f for f in self.config['families'] if f['split']=='development'][:2]
        self.config.update(seeds=[13], budgets=[0, 4], accuracies={'medium': .75}, bootstrap=30)
        self.world = build_episode(self.config['families'][0], 13, self.config)
        self.params = dict(cue_weight=1., error_weight=.5, alpha=.5)

    def test_exact_usage_all_conditions(self):
        for cap in (0,1,2,4):
            for variant in ('off','state','final','select','both','history','uniform','current'):
                s, rows, _ = run_episode(self.world, 'II', 'relevant', variant, cap, .75, self.params)
                self.assertEqual(s['checks'],cap)
                self.assertEqual(s['query_cost'],cap)
                self.assertEqual(sum(r['checks'] for r in rows),cap)
                self.assertTrue(s['actual_budget_achieved'])

    def test_state_only_off_identical_behavior_through_episode(self):
        for exp, off in (('I','off'),('II','history')):
            _, a, _ = run_episode(self.world, exp,'relevant',off,4,.75,self.params)
            _, b, _ = run_episode(self.world, exp,'relevant','state',4,.75,self.params)
            for x,y in zip(a,b):
                for key in ('selected_action','decision','channel','obtained_information','final'):
                    self.assertEqual(x[key],y[key])
                self.assertEqual(x['concern_trace']['after']['empathy'],y['concern_trace']['after']['empathy'])

    def test_reread_irrelevant_no_information_gain(self):
        for mode in ('repeat','irrelevant'):
            _, rows, _ = run_episode(self.world,'I',mode,'off',4,.75,self.params)
            for r in rows:
                self.assertEqual(r['updated_prediction'],r['initial_situation']['initial'])
                self.assertFalse(r['query_improved'])
                self.assertFalse(r['query_worsened'])

    def test_same_external_answers_across_concern_final_conditions(self):
        _, a, _ = run_episode(self.world,'I','relevant','off',4,.75,self.params)
        _, b, _ = run_episode(self.world,'I','relevant','final',4,.75,self.params)
        self.assertEqual([r['obtained_information'] for r in a],[r['obtained_information'] for r in b])

    def test_fixed_source_has_actual_experimental_assignment(self):
        _, rows, _ = run_episode(self.world,'assignment','rights_consent','off',4,.75,self.params)
        self.assertEqual({r['channel'] for r in rows if r['checks']},{'rights_consent'})

    def test_feedback_delay_and_reset(self):
        _, rows, end = run_episode(self.world,'II','relevant','both',4,.75,self.params)
        self.assertIsNone(rows[0]['delivered_feedback'])
        for before,after in zip(rows,rows[1:]):
            delivered = after['delivered_feedback']
            self.assertEqual(delivered['action_id'] if delivered else None,before['selected_action'])
        _, again, end2 = run_episode(self.world,'II','relevant','both',4,.75,self.params)
        self.assertEqual(rows,again)
        self.assertEqual(end,end2)

    def test_budget_availability_failure_not_excluded(self):
        from dataclasses import replace
        broken=(replace(self.world[0], frame=replace(self.world[0].frame,candidates=())),*self.world[1:])
        with self.assertRaises(RuntimeError):
            run_episode(broken,'I','relevant','off',4,.75,self.params)

    def test_tuning_cannot_use_heldout(self):
        cfg=copy.deepcopy(self.config)
        cfg['families'].append({'id':'forbidden','split':'heldout','structure':'must_not_build'})
        self.assertEqual(tune(cfg),tune(self.config))

    def test_export_and_freeze_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'smoke'
            records=execute(self.config,self.params,output,experiments=('I','II','assignment'))
            self.assertTrue(records)
            for name in ('summary.csv','summary.json','paired_ci.csv','episodes.csv','source_error_effects.csv','metadata.json','examples.json','decisions.jsonl.gz'):
                self.assertTrue((output/name).is_file())
            with gzip.open(output/'decisions.jsonl.gz','rt',encoding='utf-8') as log:
                row=json.loads(next(log))
                self.assertIn('local_concern_final_off',row)
                self.assertIn('initial_situation',row)
                self.assertIn('evaluation_only',row)
            with self.assertRaises(FileExistsError):
                execute(self.config,self.params,output)
            lock=Path(tmp)/'locked'
            freeze(self.config,lock)
            frozen=json.loads((lock/'freeze.json').read_text(encoding='utf-8'))
            self.assertEqual(frozen['sources'],source_hashes())
            self.assertIn('src/moral_agent/affect/appraisal.py',frozen['sources'])
            self.assertIn('src/moral_agent/judgment.py',frozen['sources'])

    def test_invalid_config_rejected(self):
        self.config['budgets']=[5]
        with self.assertRaises(ValueError): validate(self.config)


if __name__=='__main__':
    unittest.main()
