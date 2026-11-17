"""Action-scoped evidence intervention; imports no private world or evaluator."""
from dataclasses import replace
from moral_agent.models import DecisionKind,FutureOutcome,Impact,TimeHorizon
from moral_agent.judgment import select
from experiments.research_20261018.controllers import ResearchController
from .public import resolve

VARIANTS=('both','combined','history','rule','combined_verified','history_verified','rule_verified',
          'combined_no_consent','combined_no_side_effects')


class EvidenceController(ResearchController):
    def __init__(self,variant,params):
        if variant not in VARIANTS:raise ValueError('unregistered intervention')
        base='combined' if variant.startswith('combined') else 'history' if variant.startswith('history') else variant
        if variant=='rule_verified':base='rule'
        super().__init__(base,params)
        self.evidence_variant=variant;self.verified=variant not in ('both','combined','history','rule')
        self.check_consent=variant!='combined_no_consent';self.check_side=variant!='combined_no_side_effects'
        self.packet=None;self.last_dossier=None
        self.counts.update(evidence_resolutions=0,claim_inspections=0)

    def bind(self,packet):
        if packet.scope.action!='alternative':raise ValueError('packet is not for the requested alternative')
        self.packet=packet

    def observe(self,frame,action_id,observed):
        # Selected-action retrospective feedback must not be replaced by a dossier.
        saved=self.packet;self.packet=None
        try:return super().observe(frame,action_id,observed)
        finally:self.packet=saved

    def dossier(self):
        self.counts['evidence_resolutions']+=1;self.counts['claim_inspections']+=len(self.packet.claims)
        return resolve(self.packet,consent=self.check_consent,side_effects=self.check_side)

    def forecast(self,frame,evidence,action):
        if not self.verified or action.id!='alternative' or self.packet is None:
            return super().forecast(frame,evidence,action)
        self.counts['predictions']+=1
        d=self.dossier();uncertainty=1. if d['unknown'] else evidence.uncertainty if evidence.alternative else 1.
        result=[]
        for event in d['events']:
            h=(event['harm'] if event['harm'] is not None else 0.) if self.check_side else 0.
            rev=(event['reversibility'] if event['reversibility'] is not None else .95) if self.check_side else .95
            impacts=tuple(Impact(s.id,h if s.id==event['subject'] else 0.,0.,
                .9 if self.check_consent and d['consents'].get(s.id) is False else 0.,0.,
                rev if s.id==event['subject'] else .95,uncertainty,0.,'Action-scoped public evidence')
                for s in frame.situation.stakeholders)
            result.append(FutureOutcome(event['event'],TimeHorizon.SHORT_TERM,tuple(i.stakeholder_id for i in impacts),
                                       1.,h,rev,uncertainty,impacts))
        return tuple(result)

    def decide(self,frame,evidence,final_override=None,*,virtual=False):
        decision=super().decide(frame,evidence,final_override,virtual=virtual)
        if not self.verified or self.packet is None:
            self.last_dossier=None;return decision
        d=self.dossier();self.last_dossier=d
        gate=DecisionKind(d['status'])
        if gate==DecisionKind.ALLOW:return decision
        if self.research_variant=='rule':
            if decision.selected_action and decision.selected_action.id=='primary':return decision
            primary=next(a for a in frame.situation.candidates if a.id=='primary')
            primary_only=super().rule_decide(replace(frame,situation=replace(frame.situation,candidates=(primary,))),evidence)
            if primary_only.selected_action:return primary_only
            kind=DecisionKind.ASK_HUMAN if gate==DecisionKind.ASK_HUMAN or primary_only.kind==DecisionKind.ASK_HUMAN else DecisionKind.BLOCK
            return replace(decision,kind=kind,selected_action=None,explanation=decision.explanation+('Scoped evidence gate: '+gate.value,))
        assessments=tuple(replace(a,verdict=gate) if a.action.id=='alternative' else a for a in decision.assessments)
        # Preserve any selected primary and the inherited hard constraints.
        if decision.selected_action and decision.selected_action.id=='primary':return replace(decision,assessments=assessments)
        return replace(select(assessments),explanation=decision.explanation+('Scoped evidence gate: '+gate.value,))
