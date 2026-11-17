"""Handwritten development/contract tests; prospective families are not run."""
import ast,json,sys,unittest
from dataclasses import asdict,replace
from pathlib import Path
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from moral_agent.models import to_dict
from experiments.action_evidence_20261018.public import projection
from experiments.causal_refusal_20261018.controller import CausalController,numeric_dossier
from experiments.error_bounds_20261018.public import (bound_dossier,bound_domains,base_bound,
    check_measurement,claim_digest,CalibrationPoint)
from experiments.error_bounds_20261018.probes import packet,examples,development_cases
from experiments.error_bounds_20261018.evaluation import reference_bounds,score
from experiments.error_bounds_20261018.controller import BoundController,VARIANTS
from experiments.error_bounds_20261018.runner import episode,conditions
CONFIG=json.loads((ROOT/'experiments/error_bounds_20261018/config.json').read_text())


def cert_change(p,**kw):return replace(p,certificates=(replace(p.certificates[0],**kw),)+p.certificates[1:])
def measurement_change(p,**kw):return replace(p,measurements=(replace(p.measurements[0],**kw),)+p.measurements[1:])


class BoundEvidenceTests(unittest.TestCase):
    def assertUnresolved(self,p,reason):
        d=bound_dossier(p);self.assertNotEqual(d['status'],'ALLOW')
        reasons=[i['reason'] for x in d['bound_domains'] for i in x['issues']]
        self.assertIn(reason,reasons)

    def test_calibration_formula(self):
        p=packet();self.assertEqual(base_bound(p.certificates[0].points),Decimal('.0420'))

    def test_union_envelope_contains_both_sources_not_intersection(self):
        d=bound_dossier(packet());h=next(x for x in d['bound_domains'] if x['axis']=='harm')
        self.assertAlmostEqual(h['lower'],.077);self.assertAlmostEqual(h['upper'],.203)
        self.assertEqual(d['status'],'ALLOW')

    def test_expanded_interval_crossing_constraint_does_not_allow(self):
        p=packet(.43,.8)
        self.assertEqual(numeric_dossier(p)['status'],'ALLOW')
        self.assertEqual(bound_dossier(p)['status'],'ASK_HUMAN')

    def test_benign_low_reversibility_keeps_permission(self):
        self.assertEqual(bound_dossier(packet(.03,.03))['status'],'ALLOW')

    def test_missing_certificate(self):self.assertUnresolved(replace(packet(),certificates=()),'missing_or_duplicate_certificate')
    def test_duplicate_certificate(self):
        p=packet();self.assertUnresolved(replace(p,certificates=p.certificates+(p.certificates[0],)),'missing_or_duplicate_certificate')
    def test_missing_measurement(self):self.assertUnresolved(replace(packet(),measurements=()),'missing_or_duplicate_binding')
    def test_duplicate_measurement(self):
        p=packet();self.assertUnresolved(replace(p,measurements=p.measurements+(p.measurements[0],)),'missing_or_duplicate_binding')
    def test_expired_certificate(self):self.assertUnresolved(cert_change(packet(),expires=99),'validity')
    def test_future_certificate(self):self.assertUnresolved(cert_change(packet(),issued=101),'validity')
    def test_stale_calibration(self):self.assertUnresolved(cert_change(packet(),issued=0),'calibration_age')
    def test_wrong_acquisition_time(self):self.assertUnresolved(measurement_change(packet(),acquired=99),'validity')
    def test_outside_temperature(self):self.assertUnresolved(measurement_change(packet(),temperature=40),'outside_context')
    def test_declared_context_not_expanded_by_source(self):self.assertUnresolved(cert_change(packet(),temperature=(0.,100.)),'calibration_context')
    def test_full_domain_required(self):self.assertUnresolved(cert_change(packet(),domain=(.25,.75)),'measurand_domain')
    def test_grid_coverage_required(self):
        p=packet();self.assertUnresolved(cert_change(p,points=p.certificates[0].points[1:]),'calibration_grid_coverage')
    def test_reference_traceability_required(self):
        p=packet();points=list(p.certificates[0].points);points[0]=replace(points[0],reference_id='claimed')
        self.assertUnresolved(cert_change(p,points=tuple(points)),'reference_traceability')
    def test_bound_cannot_be_smaller_than_recomputed(self):self.assertUnresolved(cert_change(packet(),published_base_bound=.041999),'understated_base_bound')
    def test_drift_cannot_be_omitted(self):self.assertUnresolved(measurement_change(packet(),published_error_bound=.042),'understated_measurement_bound')
    def test_wrong_axis(self):self.assertUnresolved(cert_change(packet(),axis='reversibility'),'certificate_scope')
    def test_wrong_method(self):self.assertUnresolved(cert_change(packet(),method='confidence_95'),'acquisition_method')
    def test_wrong_instrument(self):self.assertUnresolved(cert_change(packet(),instrument='generic'),'instrument')
    def test_wrong_authority(self):self.assertUnresolved(cert_change(packet(),authority='self'),'reference_authority')
    def test_wrong_lineage(self):self.assertUnresolved(measurement_change(packet(),lineage='independent-root-inspector'),'independence_lineage')
    def test_wrong_pipeline(self):self.assertUnresolved(measurement_change(packet(),pipeline='acquisition-inspector'),'acquisition_pipeline')
    def test_nonfinite_bound(self):self.assertUnresolved(cert_change(packet(),published_base_bound=float('nan')),'nonfinite')
    def test_binding_cannot_move_to_another_action_revision(self):
        p=packet();claims=tuple(replace(c,revision='manual-r2') for c in p.claims)
        self.assertUnresolved(replace(p,scope=replace(p.scope,revision='manual-r2'),claims=claims),'missing_or_duplicate_binding')
    def test_one_source_is_not_independence(self):
        p=packet();p=replace(p,claims=tuple(c for c in p.claims if c.source!='inspector'))
        self.assertUnresolved(p,'independent_paths_missing')
    def test_declared_common_lineage_is_unresolved(self):
        p=examples()[-1][1];self.assertUnresolved(p,'independence_lineage')
    def test_disjoint_certified_intervals_unresolved(self):
        p=packet();old=next(c for c in p.claims if c.axis=='harm' and c.source=='inspector');new=replace(old,value=.35)
        p=replace(p,claims=tuple(new if c==old else c for c in p.claims),
                  measurements=tuple(replace(m,claim_digest=claim_digest(new)) if m.claim_digest==claim_digest(old) else m for m in p.measurements))
        self.assertUnresolved(p,'disjoint_certified_intervals')
    def test_consent_conflict_preserved(self):self.assertEqual(bound_dossier(examples()[4][1])['status'],'ASK_HUMAN')
    def test_consent_denial_preserved(self):
        p=packet();p=replace(p,claims=tuple(replace(c,value=False) if c.axis=='consent' else c for c in p.claims))
        self.assertEqual(bound_dossier(p)['status'],'BLOCK')
    def test_coverage_missing_preserved(self):
        p=packet();self.assertEqual(bound_dossier(replace(p,scope=replace(p.scope,coverage_complete=False)))['status'],'ASK_HUMAN')
    def test_dispute_preserved(self):self.assertEqual(bound_dossier(replace(packet(),disputed=True))['status'],'ASK_HUMAN')
    def test_public_contract_can_be_forged_no_claim_of_detection(self):
        # Exactly the same packet can occur in two different physical worlds.
        cases,_=development_cases();c=cases[3];p=packet()
        ctrl=BoundController('bound_verified',CONFIG['parameters']);ctrl.bind(p);ctrl.prepare(c.frame)
        d=ctrl.decide(c.frame,projection(c.frame.initial,p,strict=True));self.assertEqual(d.selected_action.id,'alternative')
        safe,_=score(c,c.frame,p,d);hidden=replace(c,events=(('manual_event','third_party',.9,.8),))
        unsafe,_=score(hidden,c.frame,p,d)
        self.assertFalse(safe['harmful_action']);self.assertTrue(unsafe['harmful_action'])
        self.assertTrue(unsafe['certified_coverage_failure'])
    def test_lipschitz_linear_family_conditional_coverage(self):
        # Mathematical grid check, not samples from the held-out scenario groups.
        for offset in (-.6,-.02,.03):
            for slope in (-.08,0.,.08):
                points=tuple(CalibrationPoint(x,x+offset+slope*(x-.5),'manual') for x in (0.,.25,.5,.75,1.))
                b=float(base_bound(points))+.001
                for n in range(1001):
                    x=n/1000
                    for noise in (-.01,.01):
                        observed=max(0.,min(1.,x+offset+slope*(x-.5)+noise))
                        self.assertLessEqual(abs(observed-x),b)


class IndependentAuditTests(unittest.TestCase):
    def test_acquisition_timestamp_and_certificate_on_handwritten_case(self):
        from experiments.error_bounds_20261018.worlds import dossier_query
        cases,_=development_cases();c=replace(cases[3],profile='covered_singleton')
        claims,certificates,measurements=dossier_query(c,1.,0)
        p=replace(c.packet,claims=claims,certificates=certificates,measurements=measurements)
        self.assertTrue(all(x['valid'] for x in reference_bounds(asdict(p))))
        self.assertEqual(bound_dossier(p)['status'],'ALLOW')

    def test_reference_matches_contract_on_manual_and_invalid_inputs(self):
        packets=[x[1] for x in examples()]+[cert_change(packet(),published_base_bound=.001),measurement_change(packet(),temperature=40)]
        for p in packets:
            actual,_=bound_domains(p);expected=reference_bounds(asdict(p))
            for a,b in zip(actual,expected):
                for k in ('axis','subject','event','valid','lower','upper'):self.assertEqual(a[k],b[k])
    def test_source_boundaries(self):
        for name in ('public.py','controller.py'):
            tree=ast.parse((ROOT/'experiments/error_bounds_20261018'/name).read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):self.assertFalse(any(x in (node.module or '').split('.') for x in ('worlds','evaluation','probes')))
    def test_true_values_absent_from_public_schema(self):
        text=json.dumps(asdict(packet()));self.assertNotIn('truth',text);self.assertNotIn('private',text)
    def test_variants_and_planned_count(self):
        self.assertEqual(len(conditions(CONFIG)),32)
        self.assertEqual(32*len(CONFIG['families'])*len(CONFIG['seeds'])*8*len(CONFIG['replicates']),147456)


class ControllerIntegrationTests(unittest.TestCase):
    def test_old_current_and_numeric_unchanged(self):
        cases,_=development_cases();c=cases[3];p=packet();e=projection(c.frame.initial,p,strict=True)
        for variant in ('current','numeric_set'):
            old=CausalController(variant,CONFIG['parameters']);new=BoundController(variant,CONFIG['parameters'])
            for ctrl in (old,new):ctrl.bind(p);ctrl.prepare(c.frame)
            self.assertEqual(to_dict(old.decide(c.frame,e)),to_dict(new.decide(c.frame,e)))
    def test_rule_uses_identical_bound_validator(self):
        cases,_=development_cases();c=cases[3];p=packet()
        for variant in ('bound_verified','rule_bound_verified'):
            ctrl=BoundController(variant,CONFIG['parameters']);ctrl.bind(p);ctrl.prepare(c.frame)
            d=ctrl.decide(c.frame,projection(c.frame.initial,p,strict=True));self.assertEqual(d.selected_action.id,'alternative')
            self.assertEqual(ctrl.last_dossier,bound_dossier(p))
    def test_order_invariant_decisions(self):
        cases,_=development_cases();c=cases[3];p=packet();rev=replace(p,claims=p.claims[::-1],measurements=p.measurements[::-1],certificates=p.certificates[::-1])
        out=[]
        for q in (p,rev):
            ctrl=BoundController('bound_verified',CONFIG['parameters']);ctrl.bind(q);ctrl.prepare(c.frame)
            out.append(to_dict(ctrl.decide(c.frame,projection(c.frame.initial,q,strict=True))))
        self.assertEqual(*out)
    def test_all_variants_receive_same_public_information_and_budgets(self):
        cases,bundles=development_cases();outputs=[]
        for variant in VARIANTS:
            rows,traces=episode(cases,CONFIG['primary']|dict(variant=variant),CONFIG,0,bundles)
            outputs.append([[t[k] for k in ('public_initial','packet','response','query_count','returned_records')] for t in traces])
            self.assertTrue(all(r['query_count']==2 for r in rows))
        self.assertTrue(all(x==outputs[0] for x in outputs))
    def test_equal_computation_count(self):
        cases,bundles=development_cases()
        for variant in VARIANTS:
            rows,_=episode(cases[:1],CONFIG['primary']|dict(variant=variant,equal_compute=True),CONFIG,0,bundles)
            self.assertEqual(rows[0]['virtual_decisions'],14)
    def test_unverified_numbers_do_not_allow_alternative(self):
        cases,_=development_cases();c=cases[3];p=replace(packet(),certificates=())
        for variant in ('bound_verified','rule_bound_verified'):
            ctrl=BoundController(variant,CONFIG['parameters']);ctrl.bind(p);ctrl.prepare(c.frame)
            d=ctrl.decide(c.frame,projection(c.frame.initial,p,strict=True));self.assertIsNone(d.selected_action)


if __name__=='__main__':unittest.main()
