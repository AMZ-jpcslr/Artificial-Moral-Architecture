"""Handwritten development inputs, separate from prospective world generation."""
from dataclasses import replace
from decimal import Decimal
from moral_agent.models import Action,ActionKind,Situation
from moral_agent.affect.appraisal import AppraisalContext
from moral_agent.concern_information.world import PublicFrame,CHANNELS
from experiments.research_20261018.public import ExtendedEvidence
from experiments.action_evidence_20261018.public import Scope,Claim
from experiments.causal_refusal_20261018.worlds import Case
from .public import BoundPacket,Certificate,CalibrationPoint,Measurement,claim_digest


def packet(h=.1,r=.8):
    scope=Scope('alternative','manual-r1',('user','third_party'),(('manual_event','third_party'),))
    claims=[Claim('alternative','manual-r1','resource','availability','available',True,'resource',.95,100,120)]
    claims.extend(Claim('alternative','manual-r1',s,'permission','consent',True,'owner',.95,100,120) for s in scope.consent_subjects)
    certs=[];measurements=[]
    for axis,value in [('harm',h),('reversibility',r)]:
        for source,offset,bound in [('lab',.02,.042),('inspector',.04,.062)]:
            points=tuple(CalibrationPoint(x,float(Decimal(str(x))+Decimal(str(offset))),f'reference-{source}:{axis}:{x}') for x in (0.,.25,.5,.75,1.))
            cert=Certificate(source+'-'+axis,source,axis,'grid_lipschitz_v1',source+'-'+axis,'reference-'+source,'independent-root-'+source,95,120,(0.,1.),(10.,35.),points,bound)
            claim=Claim('alternative','manual-r1','third_party','manual_event',axis,round(min(1.,value+offset),8),source,.95,100,120)
            measurement=Measurement(claim_digest(claim),cert.id,100,22.,'acquisition-'+source,'independent-root-'+source,round(bound+.001,6))
            certs.append(cert);claims.append(claim);measurements.append(measurement)
    return BoundPacket(scope,100,tuple(claims),False,tuple(certs),tuple(measurements))


def examples():
    safe=packet();missing=replace(safe,certificates=())
    conflicting=next(c for c in safe.claims if c.axis=='consent')
    conflict=replace(safe,claims=safe.claims+(replace(conflicting,value=False,source='registry'),))
    correlated=replace(safe,measurements=tuple(replace(m,lineage='independent-root-lab',pipeline='acquisition-lab') if m.pipeline=='acquisition-inspector' else m for m in safe.measurements))
    return [('all_observed_safe_true_inside',safe,.13,.83),
            ('all_observed_safe_true_outside_no_bound',missing,.75,.83),
            ('bound_crosses_harm_threshold',packet(.46,.8),.46,.8),
            ('certified_envelope_safe',safe,.1,.8),
            ('consent_conflict',conflict,.1,.8),
            ('declared_correlated',correlated,.1,.8)]


def development_cases():
    cases=[];bundles={}
    for step,(name,p,h,r) in enumerate(examples()):
        key='manual-enclosure:'+name
        truth=ExtendedEvidence(.9,0.,0.,True,True,True,.15)
        situation=Situation('手書きの上界検証probe',(
            Action('primary','当初候補',ActionKind.UNKNOWN,.9),Action('alternative','代替候補',ActionKind.UNKNOWN,.7)))
        frame=PublicFrame(situation,truth,(.2,)*5,CHANNELS,.5,AppraisalContext(.8,.8,.5))
        empty=replace(p,claims=(),certificates=(),measurements=())
        cases.append(Case('manual_development',name,name,47,step,key,frame,empty,truth,
                         (('user',True),('third_party',True)),(('manual_event','third_party',h,r),),True,False))
        bundles[key]=(p.claims,p.certificates,p.measurements)
    return tuple(cases),bundles
