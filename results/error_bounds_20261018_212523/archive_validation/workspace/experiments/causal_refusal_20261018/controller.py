"""Public-input-only interventions; no evaluator, scenarios or private labels."""
from dataclasses import replace
from itertools import product
from moral_agent.models import DecisionKind,to_dict
from moral_agent.moral_evaluation import MoralPolicy
from moral_agent.affect.agent import control_plan
from moral_agent.judgment import select
from experiments.action_evidence_20261018.controller import EvidenceController
from experiments.action_evidence_20261018.public import resolve

VARIANTS=('current','guilt_event','numeric_set','history_verified','rule','rule_verified')

def numeric_dossier(packet):
    """Only discharge observed numeric disagreement when all values are safe.

    Missing values, Boolean disagreement, provenance, coverage, and disputes retain
    the original unresolved status. No average or last-observation substitution.
    Each accepted event retains a conservative envelope of its observed domain.
    """
    d=resolve(packet);details={(x['axis'],x['subject'],x['event']):x for x in d['details']}
    proofs=[];discharged=set();events=[]
    for event in d['events']:
        name,subject=event['event'],event['subject']
        h=details[('harm',subject,name)];r=details[('reversibility',subject,name)]
        pairs=list(product(h['values'],r['values']))
        safe=bool(pairs) and all(a<.5 and (a<.4 or b>.2) for a,b in pairs)
        conflicting=h['status']=='conflicting' or r['status']=='conflicting'
        if safe and conflicting:
            proofs.append(dict(event=name,subject=subject,harm_domain=h['values'],reversibility_domain=r['values'],
                checked_pairs=len(pairs),all_pairs_safe=True,scope='same event and stakeholder'))
            for slot in (h,r):
                if slot['status']=='conflicting':discharged.add('/'.join((slot['axis'],subject,name)))
            events.append(event|dict(harm=max(h['values']),reversibility=min(r['values'])))
        else:events.append(event)
    unknown=[x for x in d['unknown'] if x not in discharged]
    status='BLOCK' if d['prohibited'] else 'ASK_HUMAN' if unknown else 'ALLOW'
    if packet.disputed:status='ASK_HUMAN'
    return d|dict(status=status,unknown=unknown,events=events,numeric_proofs=proofs,
                  original_unknown=d['unknown'],discharged_numeric_conflicts=sorted(discharged))

def paired_review(evaluation,outcomes,policy,irreversible_threshold):
    """Change only the soft harm-review pairing, retaining all other guards."""
    pairs=[]
    for index,o in enumerate(outcomes):
        if o.probability<=0:continue
        pairs.append((f'outcome:{index}',o.severity,o.reversibility))
        pairs.extend((f'outcome:{index}/stakeholder:{i.stakeholder_id}',i.harm,i.reversibility) for i in o.impacts)
    checks=[dict(scope=name,harm=h,reversibility=r,threshold=irreversible_threshold if r<.5 else .5,
                 triggers=h>=(irreversible_threshold if r<.5 else .5)) for name,h,r in pairs]
    if evaluation.uncertainty>=policy.uncertainty_limit:verdict=DecisionKind.ASK_HUMAN
    elif evaluation.hard_violations:verdict=DecisionKind.BLOCK
    elif (any(x['triggers'] for x in checks) or evaluation.rights>=policy.review_rights or
          evaluation.consent>=policy.review_consent or evaluation.fairness>=policy.review_fairness):verdict=DecisionKind.ASK_HUMAN
    else:verdict=DecisionKind.ALLOW
    return verdict,checks

class CausalController(EvidenceController):
    def __init__(self,variant,params):
        if variant not in VARIANTS:raise ValueError('unregistered intervention')
        super().__init__('combined_verified' if variant in ('current','guilt_event','numeric_set') else variant,params)
        self.study_variant=variant;self.last_pairing=[]
        self.counts.update(paired_review_checks=0,numeric_domain_pairs=0)

    def dossier(self):
        if self.study_variant!='numeric_set':return super().dossier()
        self.counts['evidence_resolutions']+=1;self.counts['claim_inspections']+=len(self.packet.claims)
        d=numeric_dossier(self.packet)
        self.counts['numeric_domain_pairs']+=sum(x['checked_pairs'] for x in d['numeric_proofs'])
        return d

    def decide(self,frame,evidence,final_override=None,*,virtual=False):
        self.last_pairing=[]
        original=super().decide(frame,evidence,final_override,virtual=virtual)
        if self.study_variant!='guilt_event':return original
        use=self.switch.final if final_override is None else final_override
        plan=control_plan(self.state,replace(self.config,concern_enabled=use and self.config.concern_enabled))
        policies={x['action']:MoralPolicy(**x['policy']) for x in self.last_policies};assessments=[]
        for a in original.assessments:
            verdict,checks=paired_review(a.evaluation,a.outcomes,policies[a.action.id],plan.irreversible_review_harm)
            self.counts['paired_review_checks']+=len(checks)
            if a.action.id=='alternative' and self.last_dossier and self.last_dossier['status']!='ALLOW':
                verdict=DecisionKind(self.last_dossier['status'])
            self.last_pairing.append(dict(action=a.action.id,old_verdict=a.verdict.value,new_verdict=verdict.value,
                checks=checks,hard_violations=a.evaluation.hard_violations,uncertainty=a.evaluation.uncertainty))
            assessments.append(replace(a,verdict=verdict))
        decision=select(tuple(assessments))
        # Retain the old reversible-choice preference. This study changes review
        # pairing only, not the candidate-ranking score or affect update equations.
        if plan.prefer_reversible:
            allowed=[a for a in assessments if a.verdict==DecisionKind.ALLOW]
            if allowed:
                chosen=min(allowed,key=lambda a:(a.evaluation.harm*(1-a.evaluation.reversibility),-a.action.task_utility,a.action.id))
                if chosen.action!=decision.selected_action:
                    decision=replace(decision,selected_action=chosen.action,
                        kind=DecisionKind.ALLOW if chosen.action==decision.proposed_action else DecisionKind.MODIFY)
        return replace(decision,explanation=decision.explanation+('Soft harm review paired within each outcome/stakeholder.',))
