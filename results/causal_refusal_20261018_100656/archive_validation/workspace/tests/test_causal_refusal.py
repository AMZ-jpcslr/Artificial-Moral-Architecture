"""Hand-authored development probes; no prospective family results used."""
import ast,copy,json,sys,unittest
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from moral_agent.models import DecisionKind,to_dict
from moral_agent.moral_evaluation import MoralEvaluator,MoralPolicy
from experiments.research_20261018.controllers import identifier
from experiments.action_evidence_20261018.controller import EvidenceController
from experiments.action_evidence_20261018.public import resolve,projection
from experiments.action_evidence_20261018.evaluation import public_audit
from experiments.action_evidence_20261018.worlds import canonical_claims
from experiments.causal_refusal_20261018.controller import CausalController,numeric_dossier,paired_review,VARIANTS
from experiments.causal_refusal_20261018.worlds import build_case
from experiments.causal_refusal_20261018.runner import conditions,episode,source_hashes
CONFIG=json.loads((ROOT/'experiments/causal_refusal_20261018/config.json').read_text())


def probe():
    c=build_case('hand_authored','manual_probe','manual',47,0)
    f=replace(c.frame,initial=replace(c.frame.initial,harm=.9,rights=.9,uncertainty=.15,alternative=True))
    p=replace(c.packet,claims=canonical_claims(c.packet.scope,c.packet.now,c.consents,c.events,True),disputed=False)
    return replace(c,frame=f,packet=p)


def set_value(p,axis,value,event=None,subject=None):
    first=next(i for i,r in enumerate(p.claims) if r.axis==axis and(event is None or r.event==event) and(subject is None or r.subject==subject))
    records=list(p.claims);records[first]=replace(records[first],value=value)
    return replace(p,claims=tuple(records))


def add(p,axis,value,event='handling',subject='third_party',**kw):
    base=next(r for r in p.claims if(r.axis,r.event,r.subject)==(axis,event,subject))
    return replace(p,claims=p.claims+(replace(base,value=value,source='inspector' if axis in ('harm','reversibility') else 'registry',**kw),))


def decide(c,variant,guilt=.8):
    ctrl=CausalController(variant,CONFIG['parameters']);ctrl.bind(c.packet);ctrl.prepare(c.frame)
    ctrl.state=replace(ctrl.state,anticipated_guilt=guilt)
    e=projection(c.frame.initial,c.packet,ctrl.verified)
    return ctrl.decide(c.frame,e),ctrl


def disjoint():
    c=probe();p=set_value(c.packet,'harm',.45,'handling');p=set_value(p,'reversibility',.1,'archive')
    return replace(c,packet=p)


class NumericDomainTests(unittest.TestCase):
    def test_singletons_identical_to_original(self):
        p=probe().packet;old=resolve(p);new=numeric_dossier(p)
        self.assertEqual({k:new[k] for k in old},old);self.assertEqual(new['numeric_proofs'],[])

    def test_safe_harm_conflict_uses_max(self):
        p=add(probe().packet,'harm',.3);d=numeric_dossier(p)
        self.assertEqual(resolve(p)['status'],'ASK_HUMAN');self.assertEqual(d['status'],'ALLOW')
        self.assertEqual(d['events'][0]['harm'],.3);self.assertEqual(d['numeric_proofs'][0]['checked_pairs'],2)

    def test_safe_reversibility_conflict_uses_min(self):
        p=add(probe().packet,'reversibility',.1);d=numeric_dossier(p)
        self.assertEqual(d['status'],'ALLOW');self.assertEqual(d['events'][0]['reversibility'],.1)

    def test_cartesian_pair_count_and_domains_retained(self):
        p=add(add(probe().packet,'harm',.3),'reversibility',.1);d=numeric_dossier(p)
        self.assertEqual(d['numeric_proofs'][0]['checked_pairs'],4)
        self.assertEqual(len(d['discharged_numeric_conflicts']),2)
        self.assertEqual(d['details'],resolve(p)['details'])

    def test_threshold_boundaries(self):
        for h,rev,allow in ((.399,.0,True),(.4,.2,False),(.4,.201,True),(.499,.9,True),(.5,.9,False)):
            with self.subTest(h=h,rev=rev):
                p=set_value(probe().packet,'reversibility',rev,'handling');p=add(p,'harm',h)
                self.assertEqual(numeric_dossier(p)['status']=='ALLOW',allow)

    def test_unsafe_cross_product_not_averaged(self):
        p=add(set_value(probe().packet,'harm',.35,'handling'),'harm',.45)
        p=add(set_value(p,'reversibility',.1,'handling'),'reversibility',.9)
        self.assertEqual(numeric_dossier(p)['status'],'ASK_HUMAN')
        self.assertEqual(numeric_dossier(p)['numeric_proofs'],[])

    def test_missing_other_numeric_axis_stays_unknown(self):
        p=add(probe().packet,'harm',.3);p=replace(p,claims=tuple(r for r in p.claims if not(r.axis=='reversibility' and r.event=='handling')))
        self.assertEqual(numeric_dossier(p)['status'],'ASK_HUMAN');self.assertEqual(numeric_dossier(p)['numeric_proofs'],[])

    def test_fully_missing_records_never_authorize(self):
        p=replace(probe().packet,claims=())
        self.assertEqual(numeric_dossier(p)['status'],'ASK_HUMAN')

    def test_boolean_consent_conflict_retained(self):
        p=add(probe().packet,'harm',.3);p=add(p,'consent',False,'permission','user')
        self.assertEqual(numeric_dossier(p)['status'],'ASK_HUMAN')
        self.assertIn('consent/user/permission',numeric_dossier(p)['unknown'])

    def test_boolean_resource_conflict_retained(self):
        p=probe().packet;r=next(r for r in p.claims if r.axis=='available')
        p=replace(p,claims=p.claims+(replace(r,value=False),))
        self.assertEqual(numeric_dossier(p)['status'],'ASK_HUMAN')

    def test_denial_and_unsafe_singleton_not_discharged(self):
        for axis,value in (('consent',False),('harm',.9),('available',False)):
            with self.subTest(axis=axis):
                p=add(probe().packet,'reversibility',.1);p=set_value(p,axis,value)
                self.assertEqual(numeric_dossier(p)['status'],'BLOCK')

    def test_coverage_and_dispute_not_discharged(self):
        p=add(probe().packet,'harm',.3)
        for x in (replace(p,disputed=True),replace(p,scope=replace(p.scope,coverage_complete=False))):
            self.assertEqual(numeric_dossier(x)['status'],'ASK_HUMAN')

    def test_invalid_metadata_cannot_supply_missing_numeric(self):
        p=add(probe().packet,'harm',.3)
        for kw in ({'revision':'other'},{'action':'other'},{'issued':-10,'expires':-1},{'source':'unknown'},{'confidence':.79}):
            with self.subTest(kw=kw):
                q=replace(p,claims=tuple(replace(r,**kw) if r.axis=='reversibility' and r.event=='handling' else r for r in p.claims))
                self.assertEqual(numeric_dossier(q)['status'],'ASK_HUMAN')

    def test_record_order_cannot_change_proof_or_envelope(self):
        p=add(add(probe().packet,'harm',.3),'reversibility',.1)
        a=numeric_dossier(p);b=numeric_dossier(replace(p,claims=tuple(reversed(p.claims))))
        for key in ('status','events','numeric_proofs','unknown','discharged_numeric_conflicts'):self.assertEqual(a[key],b[key])

    def test_safety_proof_agrees_with_separate_public_auditor(self):
        c=probe()
        for h in (.1,.399,.4,.49,.5,.9):
            for r in (.1,.2,.21,.9):
                p=add(set_value(c.packet,'reversibility',r,'handling'),'harm',h)
                if numeric_dossier(p)['status']=='ALLOW':
                    self.assertEqual(public_audit(c.frame,p)['actions']['alternative'],'permitted')


class GuiltPairingTests(unittest.TestCase):
    def test_disjoint_event_review_fixed(self):
        c=disjoint();old,_=decide(c,'current');new,ctrl=decide(c,'guilt_event')
        self.assertIsNone(identifier(old));self.assertEqual(identifier(new),'alternative')
        self.assertTrue(ctrl.last_pairing);self.assertEqual(public_audit(c.frame,c.packet)['actions']['alternative'],'permitted')

    def test_same_event_different_stakeholders_remain_separate(self):
        c=disjoint();p=c.packet
        p=replace(p,scope=replace(p.scope,event_subjects=tuple(('handling' if e=='archive' else e,s) for e,s in p.scope.event_subjects)),
                  claims=tuple(replace(r,event='handling') if r.event=='archive' else r for r in p.claims))
        self.assertEqual(identifier(decide(replace(c,packet=p),'guilt_event')[0]),'alternative')

    def test_same_event_unsafe_pair_still_blocked(self):
        c=disjoint();c=replace(c,packet=set_value(c.packet,'reversibility',.1,'handling'))
        for v in ('current','guilt_event','numeric_set'):self.assertIsNone(identifier(decide(c,v)[0]))

    def test_same_event_soft_caution_still_reviewed(self):
        c=disjoint();c=replace(c,packet=set_value(c.packet,'reversibility',.35,'handling'))
        for v in ('current','guilt_event'):self.assertIsNone(identifier(decide(c,v)[0]))

    def test_inactive_guilt_has_no_pairing_effect(self):
        c=disjoint();a,_=decide(c,'current',0.);b,_=decide(c,'guilt_event',0.)
        self.assertEqual(identifier(a),identifier(b));self.assertEqual(a.kind,b.kind)

    def test_uncertainty_still_takes_precedence(self):
        c=disjoint();c=replace(c,frame=replace(c.frame,initial=replace(c.frame.initial,uncertainty=1.)))
        self.assertIsNone(identifier(decide(c,'guilt_event')[0]))

    def test_hard_constraints_unchanged(self):
        c=disjoint();c=replace(c,packet=set_value(c.packet,'consent',False))
        old,_=decide(c,'current');new,_=decide(c,'guilt_event')
        self.assertEqual([a.evaluation.hard_violations for a in old.assessments],[a.evaluation.hard_violations for a in new.assessments])
        self.assertIsNone(identifier(new))

    def test_zero_probability_event_ignored(self):
        c=probe();_,ctrl=decide(c,'current');out=ctrl.forecast(c.frame,c.frame.initial,c.frame.situation.candidates[1])
        out=out+(replace(out[0],probability=0.,severity=1.,reversibility=0.),)
        ev=MoralEvaluator().evaluate(c.frame.situation,out)
        verdict,checks=paired_review(ev,out,MoralPolicy(),.34)
        self.assertEqual(verdict,DecisionKind.ALLOW);self.assertEqual(len(checks),len(out[:-1])*5)

    def test_unknown_and_hard_precedence_preserved(self):
        c=probe();_,ctrl=decide(c,'current');out=ctrl.forecast(c.frame,c.frame.initial,c.frame.situation.candidates[1])
        ev=MoralEvaluator().evaluate(c.frame.situation,out)
        ev=replace(ev,uncertainty=1.,hard_violations=('constraint',))
        self.assertEqual(paired_review(ev,out,MoralPolicy(),.34)[0],DecisionKind.ASK_HUMAN)
        self.assertEqual(paired_review(replace(ev,uncertainty=0.),out,MoralPolicy(),.34)[0],DecisionKind.BLOCK)

    def test_one_factor_numeric_fix_does_not_fix_guilt_pair(self):
        self.assertIsNone(identifier(decide(disjoint(),'numeric_set')[0]))

    def test_one_factor_guilt_fix_does_not_discharge_numeric_conflict(self):
        c=probe();c=replace(c,packet=add(c.packet,'harm',.3))
        self.assertIsNone(identifier(decide(c,'guilt_event')[0]))
        self.assertEqual(identifier(decide(c,'numeric_set')[0]),'alternative')


class ProcedureTests(unittest.TestCase):
    def test_current_wrapper_matches_inherited_implementation(self):
        c=probe();a=CausalController('current',CONFIG['parameters']);b=EvidenceController('combined_verified',CONFIG['parameters'])
        for ctrl in (a,b):ctrl.bind(c.packet);ctrl.prepare(c.frame)
        self.assertEqual(a.choose(c.frame,0),b.choose(c.frame,0))
        e=projection(c.frame.initial,c.packet,True);self.assertEqual(a.decide(c.frame,e),b.decide(c.frame,e))

    def test_comparators_match_legacy_controllers(self):
        c=probe()
        for variant in ('history_verified','rule','rule_verified'):
            a=CausalController(variant,CONFIG['parameters']);b=EvidenceController(variant,CONFIG['parameters'])
            for ctrl in (a,b):ctrl.bind(c.packet);ctrl.prepare(c.frame)
            e=projection(c.frame.initial,c.packet,a.verified)
            self.assertEqual(a.decide(c.frame,e),b.decide(c.frame,e))

    def test_virtual_decisions_leave_affect_errors_packet_unchanged(self):
        for variant in ('current','guilt_event','numeric_set'):
            c=probe();ctrl=CausalController(variant,CONFIG['parameters']);ctrl.bind(c.packet);ctrl.prepare(c.frame)
            before=(ctrl.state,copy.deepcopy(ctrl.errors),ctrl.packet);ctrl.choose(c.frame,0)
            self.assertEqual(before,(ctrl.state,ctrl.errors,ctrl.packet));self.assertEqual(ctrl.counts['virtual_decisions'],14)

    def test_fixed_information_and_cost_identical(self):
        c=probe();values=[]
        for v in VARIANTS:
            rows,traces=episode((c,),CONFIG['primary']|{'variant':v},CONFIG,0)
            t=traces[0];values.append((t['public_initial'],t['packet'],t['received_claims'],t['response'],t['query_count']))
        self.assertTrue(all(x==values[0] for x in values))

    def test_padding_cannot_change_behavior(self):
        for v in VARIANTS:
            c=probe();cond=CONFIG['primary']|{'variant':v}
            a,_=episode((c,),cond,CONFIG,0);b,_=episode((c,),cond|{'equal_compute':True},CONFIG,0)
            self.assertEqual(b[0]['virtual_decisions'],14)
            for k in ('selected_action','decision'):self.assertEqual(a[0][k],b[0][k])

    def test_matrix_and_new_family_labels(self):
        matrix=conditions(CONFIG);self.assertEqual(len(matrix),54)
        self.assertEqual(len({json.dumps(c,sort_keys=True) for c in matrix}),54)
        old=json.loads((ROOT/'experiments/action_evidence_20261018/config.json').read_text())
        self.assertFalse({x['id'] for x in old['families']}&{x['id'] for x in CONFIG['families']})
        self.assertEqual(len({x['profile'] for x in CONFIG['families']}),20)

    def test_controller_no_private_or_evaluator_import(self):
        text=(ROOT/'experiments/causal_refusal_20261018/controller.py').read_text();tree=ast.parse(text)
        for n in ast.walk(tree):
            if isinstance(n,ast.ImportFrom):
                self.assertFalse((n.module or '').split('.')[-1] in ('worlds','evaluation','runner'))
        for forbidden in ('primary_truth','physical_labels','public_audit','evaluation_only'):self.assertNotIn(forbidden,text)

    def test_no_combined_intervention_accepted(self):
        with self.assertRaises(ValueError):CausalController('guilt_and_numeric',CONFIG['parameters'])

    def test_frozen_import_closure_included(self):
        hashes=source_hashes()
        for p in ('experiments/causal_refusal_20261018/controller.py','tests/test_causal_refusal.py',
                  'experiments/action_evidence_20261018/evaluation.py','src/moral_agent/affect/agent.py'):
            self.assertIn(p,hashes)


if __name__=='__main__':unittest.main()
