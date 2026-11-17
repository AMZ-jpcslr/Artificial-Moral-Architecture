"""Pre-freeze tests use development data and hand-authored mechanism probes only."""
import ast
import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT))

from moral_agent.affect.appraisal import AffectState
from moral_agent.concern_information.controller import Controller
from moral_agent.concern_information.world import build_episode, apply_response, query, selected_feedback
from moral_agent.models import Decision, DecisionKind, to_dict
from experiments.research_20261018.controllers import ResearchController, signature, identifier
from experiments.research_20261018.public import ExtendedEvidence
from experiments.research_20261018 import worlds
from experiments.research_20261018.metrics import aggregate, paired
from experiments.research_20261018.runner import conditions, run_episode, source_hashes, diagnosis


CONFIG = json.loads((ROOT/'experiments/research_20261018/config.json').read_text(encoding='utf-8'))
OLD = json.loads((ROOT/'experiments/concern_information_config.json').read_text(encoding='utf-8'))
DEV = [f for f in OLD['families'] if f['split']=='development']


def example():
    return worlds.development_episode(DEV[0],13,OLD)[0]


class FollowupBoundaryTests(unittest.TestCase):
    def test_public_frame_contains_no_truth_or_scoring_fields(self):
        data = to_dict(example().world.frame)
        self.assertFalse(set(data)&{'physical','truth','label','score','family','seed','future_uniform'})

    def test_controller_never_imports_private_evaluation_module(self):
        source = (ROOT/'experiments/research_20261018/controllers.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                self.assertNotIn(node.module, ('worlds','runner','metrics'))
        self.assertNotIn('reference(',source)
        self.assertNotIn('world.physical',source)
        self.assertNotIn('safe_task_success',source)

    def test_new_family_ids_and_structures_are_unique_and_not_old(self):
        families = CONFIG['families']
        self.assertEqual(len(families),12)
        self.assertEqual(len({f['id'] for f in families}),12)
        self.assertEqual(len({f['structure'] for f in families}),12)
        self.assertFalse({f['id'] for f in families}&{f['id'] for f in OLD['families']})
        self.assertFalse({f['structure'] for f in families}&{f['structure'] for f in OLD['families']})
        self.assertEqual({f['split'] for f in families},{'prospective'})

    def test_source_freeze_covers_runtime_scoring_and_split(self):
        hashes = source_hashes()
        for path in ('src/moral_agent/judgment.py','src/moral_agent/affect/appraisal.py',
                     'experiments/research_20261018/worlds.py','experiments/research_20261018/metrics.py',
                     'experiments/research_20261018/config.json','tests/test_research_followup.py'):
            self.assertIn(path,hashes)

    def test_condition_matrix_is_unique_and_predeclared(self):
        matrix = conditions(CONFIG)
        self.assertEqual(len(matrix),61)
        self.assertEqual(len({json.dumps(c,sort_keys=True) for c in matrix}),61)
        self.assertEqual({c['prediction'] for c in matrix},{'current','oracle','noisy_oracle','checked'})

    def test_sensor_randomness_is_order_independent(self):
        case=example()
        a = worlds.get_response(case,'harm',.75,2)
        worlds.get_response(case,'alternative',.75,2)
        b = worlds.get_response(case,'harm',.75,2)
        self.assertEqual(a,b)

    def test_selected_fallback_feedback_does_not_reveal_primary(self):
        observed=worlds.feedback(example(),'alternative')
        self.assertEqual(observed.harm,0.)
        self.assertEqual(observed.rights,0.)
        self.assertEqual(observed.consent,0.)

    def test_oracle_is_explicit_and_preserves_world(self):
        case=example()
        oracle=worlds.transform(case,'oracle','canonical',0)
        self.assertEqual(oracle.world.frame.initial,worlds.reference(case.world))
        self.assertEqual(oracle.world.physical,case.world.physical)
        self.assertEqual(worlds.transform(case,'current','canonical',0),case)

    def test_noisy_oracle_is_reproducible(self):
        case=example()
        self.assertEqual(worlds.transform(case,'noisy_oracle','canonical',2),
                         worlds.transform(case,'noisy_oracle','canonical',2))


class FollowupControlTests(unittest.TestCase):
    def test_original_adapter_decision_and_state_parity(self):
        # Full episodes, including selected-action feedback and exact sensor updates.
        for family in DEV:
            for variant in ('both','history','state'):
                old=Controller(variant,CONFIG['parameters'])
                new=ResearchController(variant,CONFIG['parameters'])
                op=np=None; ordinal=0
                for raw,case in zip(build_episode(family,13,OLD),worlds.development_episode(family,13,OLD)):
                    if op: old.observe(*op)
                    if np: new.observe(*np)
                    old.prepare(raw.frame);new.prepare(case.world.frame)
                    self.assertEqual(old.state,new.state)
                    oe,ne=raw.frame.initial,case.world.frame.initial
                    if case.step in (0,2,4,6):
                        oc,_=old.choose(raw.frame,ordinal,3);nc,_=new.choose(case.world.frame,ordinal,3)
                        self.assertEqual(oc,nc)
                        oe=apply_response(oe,query(raw,oc,seed_key=0))
                        ne=apply_response(ne,worlds.get_response(case,nc,.75,0));ordinal+=1
                    od,nd=old.decide(raw.frame,oe),new.decide(case.world.frame,ne)
                    self.assertEqual(signature(od),signature(nd))
                    oid,nid=identifier(od),identifier(nd)
                    op=(raw.frame,oid,selected_feedback(raw,oid)) if oid else None
                    np=(case.world.frame,nid,worlds.feedback(case,nid)) if nid else None

    def test_sensitivity_queries_do_not_mutate_affect_or_history(self):
        ctl=ResearchController('combined',CONFIG['parameters']);frame=example().world.frame
        ctl.prepare(frame);before=(ctl.state,dict(ctl.errors),ctl.seen)
        channel,reason=ctl.choose(frame,0,0)
        self.assertEqual(before,(ctl.state,ctl.errors,ctl.seen))
        self.assertEqual(ctl.counts['virtual_decisions'],14)
        self.assertIn(channel,reason['scores'])
        self.assertTrue(all(0<=s<=1 for s in reason['sensitivity'].values()))

    def test_scoping_recovers_fallback_without_loosening_primary(self):
        frame=example().world.frame
        evidence=ExtendedEvidence(harm=.9,uncertainty=.55)
        old=ResearchController('both',CONFIG['parameters']);new=ResearchController('scoped',CONFIG['parameters'])
        old.state=new.state=AffectState(concern=1.)
        baseline=old.decide(frame,evidence);changed=new.decide(frame,evidence)
        self.assertIsNone(identifier(baseline))
        self.assertEqual(identifier(changed),'alternative')
        self.assertEqual(baseline.assessments[0].verdict,changed.assessments[0].verdict)

    def test_scoping_does_not_override_unknown_or_missing_feasibility(self):
        ctl=ResearchController('scoped',CONFIG['parameters']);ctl.state=AffectState(concern=1.)
        for evidence in (ExtendedEvidence(harm=.9,uncertainty=1.),
                         ExtendedEvidence(harm=.9,alternative=False,uncertainty=.55)):
            self.assertIsNone(identifier(ctl.decide(example().world.frame,evidence)))

    def test_scoping_does_not_allow_known_dangerous_fallback(self):
        ctl=ResearchController('scoped',CONFIG['parameters']);ctl.state=AffectState(concern=1.)
        for evidence in (ExtendedEvidence(harm=.9,fallback_consent=.9),
                         ExtendedEvidence(harm=.9,fallback_harm=.9,fallback_reversibility=.1)):
            decision=ctl.decide(example().world.frame,evidence)
            self.assertIsNone(identifier(decision))
            self.assertTrue(decision.assessments[1].evaluation.hard_violations)

    def test_no_persistence_preserves_error_history(self):
        ctl=ResearchController('combined_no_persistence',CONFIG['parameters'])
        ctl.errors['harm']=.7;ctl.state=AffectState(concern=1.)
        trace=ctl.prepare(example().world.frame)
        self.assertEqual(ctl.errors['harm'],.7)
        self.assertEqual(trace['before'],to_dict(AffectState()))

    def test_no_affect_means_no_affect_control(self):
        ctl=ResearchController('no_affect',CONFIG['parameters']);ctl.state=AffectState(concern=1.,empathy=1.,anticipated_guilt=1.)
        decision=ctl.decide(example().world.frame,ExtendedEvidence(uncertainty=.55))
        self.assertEqual(identifier(decision),'primary')
        self.assertTrue(all(p['policy']['uncertainty_limit']==.65 for p in ctl.last_policies))

    def test_no_alternatives_changes_only_candidate_access(self):
        ctl=ResearchController('combined_no_alternatives',CONFIG['parameters'])
        decision=ctl.decide(example().world.frame,ExtendedEvidence(harm=.9))
        self.assertEqual([a.action.id for a in decision.assessments],['primary'])
        self.assertIsNone(identifier(decision))

    def test_rule_uses_no_forecast_or_affect_update(self):
        ctl=ResearchController('rule',CONFIG['parameters']);frame=example().world.frame
        ctl.prepare(frame);ctl.decide(frame,ExtendedEvidence())
        self.assertEqual(ctl.counts['predictions'],0)
        self.assertEqual(ctl.counts['state_updates'],0)

    def test_exact_budget_and_accounting_on_development_episode(self):
        cases=worlds.development_episode(DEV[0],13,OLD)
        c=CONFIG['primary']|{'variant':'combined'}
        rows,traces=run_episode(cases,c,CONFIG,0)
        self.assertEqual(len(rows),8);self.assertEqual(sum(r['query_count'] for r in rows),4)
        self.assertEqual(sum(r['virtual_decisions'] for r in rows),56)
        self.assertEqual(sum(r['decisions'] for r in rows),8)
        self.assertTrue(all('decision_trace' in t and 'evaluation_only_reference' in t for t in traces))


class FollowupEvaluationTests(unittest.TestCase):
    def test_necessary_review_is_not_over_refusal(self):
        case=worlds.transform(example(),'current','incomplete',0)
        decision=ResearchController('combined',CONFIG['parameters']).decide(case.world.frame,case.world.frame.initial)
        result=worlds.score(case,decision)
        self.assertFalse(result['over_refusal_eligible'])
        self.assertTrue(result['appropriate_human_review'])
        self.assertTrue(result['justified_stop'])

    def test_ambiguous_case_has_no_normative_denominator(self):
        case=replace(example(),ambiguous=True)
        d=ResearchController('rule',CONFIG['parameters']).decide(case.world.frame,case.world.frame.initial)
        row=worlds.score(case,d)|{'family':'hand_probe'}
        summary=aggregate([row])
        self.assertIsNone(summary['safe_task_success'])
        self.assertIsNone(summary['harmful_action'])
        self.assertEqual(summary['ambiguous_count'],1)

    def test_hidden_fallback_harm_is_scored_externally(self):
        case=example();p=dict(case.world.physical);p.update(fallback_harm=.9,fallback_resource=True,fallback_blocked=False)
        case=replace(case,world=replace(case.world,physical=tuple(sorted(p.items()))))
        action=case.world.frame.situation.candidates[1]
        decision=Decision(DecisionKind.MODIFY,case.world.frame.situation.candidates[0],action,(),())
        result=worlds.score(case,decision)
        self.assertTrue(result['harmful_action'])
        self.assertFalse(result['safe_task_success'])
        self.assertTrue(result['task_success'])

    def test_local_diagnostic_does_not_change_acting_state(self):
        case=example();ctl=ResearchController('both',CONFIG['parameters']);ctl.prepare(case.world.frame)
        decision=ctl.decide(case.world.frame,case.world.frame.initial)
        before=copy.deepcopy(ctl.__dict__)
        diagnosis(case,ctl,case.world.frame.initial,decision,worlds.score(case,decision))
        self.assertEqual(ctl.state,before['state']);self.assertEqual(ctl.errors,before['errors'])
        self.assertEqual(ctl.counts,before['counts'])

    def test_cluster_bootstrap_does_not_count_repeated_rows_as_new_families(self):
        rows=[]
        for family,left,right in [('a',True,False),('b',False,True)]:
            for variant,value in [('left',left),('right',right)]:
                for replicate in range(3):
                    rows.append(dict(family=family,variant=variant,seed=1,replicate=replicate,step=0,
                                     scored=True,safe_task_success=value))
        out=paired(rows,'left','right','safe_task_success',bootstrap=100)
        self.assertEqual(out['families'],2);self.assertEqual(out['delta'],0.)

    def test_unpaired_coverage_raises(self):
        rows=[dict(family='a',variant='left',seed=1,replicate=0,step=0,scored=True,safe_task_success=True),
              dict(family='a',variant='right',seed=2,replicate=0,step=0,scored=True,safe_task_success=False)]
        with self.assertRaises(ValueError):paired(rows,'left','right','safe_task_success',bootstrap=100)


if __name__=='__main__':
    unittest.main()
