"""Independent public reference auditor. Does not import decision/bound validators.

Two normative contracts are retained: the unchanged observed-value audit, and
the preregistered calibration-evidence audit. Physical scores are unchanged.
"""
from dataclasses import asdict
from decimal import Decimal
import hashlib,json,math
from experiments.action_evidence_20261018.evaluation import public_audit,score as legacy_score


def D(x):return Decimal(str(x))


def reference_bounds(packet):
    """Independent implementation on dictionaries, with fixed public constants."""
    scope=packet['scope'];now=packet['now'];result=[]
    for event,subject in scope['event_subjects']:
        for axis in ('harm','reversibility'):
            candidates=[c for c in packet['claims'] if c['action']==scope['action'] and c['revision']==scope['revision'] and
                (c['axis'],c['subject'],c['event'])==(axis,subject,event) and c['source'] in ('lab','inspector') and
                c['confidence']>=.8 and c['issued']<=now<=c['expires']]
            spans=[];valid=bool(candidates);origins=set();paths=set()
            for c in candidates:
                digest=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                ms=[m for m in packet['measurements'] if m['claim_digest']==digest]
                if len(ms)!=1:valid=False;continue
                m=ms[0];cs=[q for q in packet['certificates'] if q['id']==m['certificate_id']]
                if len(cs)!=1:valid=False;continue
                q=cs[0];source=c['source'];age=m['acquired']-q['issued'];points=q['points']
                tests=[q['source']==source,q['axis']==axis,q['method']=='grid_lipschitz_v1',q['instrument']==source+'-'+axis,
                    q['authority']=='reference-'+source,q['lineage']=='independent-root-'+source,
                    m['lineage']=='independent-root-'+source,m['pipeline']=='acquisition-'+source,
                    q['issued']<=m['acquired']==c['issued']<=now<=q['expires'],0<=age<=50,
                    list(q['domain'])==[0.,1.],list(q['temperature'])==[10.,35.],10<=m['temperature']<=35,
                    [p['reference'] for p in points]==[0.,.25,.5,.75,1.],
                    all(p['reference_id']==f"reference-{source}:{axis}:{p['reference']}" for p in points),
                    all(math.isfinite(v) for v in [q['published_base_bound'],m['published_error_bound'],*[p['reading'] for p in points]])]
                if not all(tests):valid=False;continue
                residuals=[abs(D(p['reference'])-D(p['reading'])) for p in points]
                radii=[(D(points[i+1]['reference'])-D(points[i]['reference']))/2 for i in range(4)]
                required=max(residuals)+D('.08')*max(radii)+D('.002')+D('.01')
                base=D(q['published_base_bound']);error=D(m['published_error_bound'])
                if not(base>=required and error>=base+D('.0002')*age and 0<=error<=1):valid=False;continue
                origins.add(source);paths.add(m['lineage']);value=D(c['value'])
                spans.append((max(D(0),value-error),min(D(1),value+error)))
            valid=valid and len(origins)>=2 and len(paths)>=2 and bool(spans)
            if spans and max(lo for lo,hi in spans)>min(hi for lo,hi in spans):valid=False
            result.append(dict(event=event,subject=subject,axis=axis,valid=bool(valid),observed=sorted({c['value'] for c in candidates}),
                lower=float(min(x[0] for x in spans)) if valid else None,upper=float(max(x[1] for x in spans)) if valid else None))
    return result


def calibration_audit(legacy,packet,domains):
    tests=[];by={(x['axis'],x['subject'],x['event']):x for x in domains}
    for d in legacy['domains']:
        if d['axis'] in ('consent','available'):tests.append((all(d['values']),any(d['values'])))
    for event,subject in packet['scope']['event_subjects']:
        h,r=by['harm',subject,event],by['reversibility',subject,event]
        if not h['valid'] or not r['valid']:tests.append((False,True));continue
        # Worst/best corners suffice for the monotone predicate on an interval.
        all_safe=h['upper']<.5 and(h['upper']<.4 or r['lower']>.2)
        any_safe=h['lower']<.5 and(h['lower']<.4 or r['upper']>.2)
        tests.append((all_safe,any_safe))
    tests.append((packet['scope']['coverage_complete'],True))
    alt='permitted' if all(a for a,b in tests) else 'undetermined' if all(b for a,b in tests) else 'forbidden'
    if packet['disputed']:alt='undetermined'
    actions=legacy['actions']|dict(alternative=alt);permitted=[a for a,v in actions.items() if v=='permitted']
    stop=None if permitted else 'ASK_HUMAN' if 'undetermined' in actions.values() else 'BLOCK'
    return dict(actions=actions,permitted=permitted,expected_stop=stop,domains=domains)


def public_metrics(decision,success,danger,scored,audit):
    action=decision.selected_action.id if decision.selected_action else None;stop=action is None;eligible=bool(audit['permitted'])
    return dict(bound_supported_safe_success=bool(success and not danger and scored and action in audit['permitted']),
        bound_unjustified_refusal_eligible=eligible,bound_unjustified_refusal=stop and eligible,
        bound_unsupported_execution=bool(action and action not in audit['permitted']),
        bound_necessary_stop_eligible=not eligible,bound_necessary_stop=stop and not eligible,
        bound_stop_kind_correct=bool(stop and decision.kind.value==audit['expected_stop']))


def score(case,frame,packet,decision):
    old,legacy=legacy_score(case,frame,packet,decision);data=asdict(packet)
    domains=reference_bounds(data);audit=calibration_audit(legacy,data,domains)
    metrics=public_metrics(decision,old['task_success'],old['harmful_action'],old['scored'],audit)
    true={(axis,s,e):v for e,s,h,r in case.events for axis,v in [('harm',h),('reversibility',r)]}
    details=[]
    for d in domains:
        value=true[d['axis'],d['subject'],d['event']];obs=d['observed']
        details.append(d|dict(truth=value,observed_covers=bool(obs and min(obs)<=value<=max(obs)),
            certified_covers=bool(d['valid'] and d['lower']<=value<=d['upper'])))
    eligible=all(d['valid'] for d in details);covered=eligible and all(d['certified_covers'] for d in details)
    action=decision.selected_action.id if decision.selected_action else None
    metrics.update(observed_enclosure=all(d['observed_covers'] for d in details),
        certified_coverage_eligible=eligible,certified_enclosure=bool(covered),
        alternative_execution=action=='alternative',alternative_harmful_execution=action=='alternative' and old['harmful_action'],
        alternative_execution_eligible=action=='alternative',
        certified_coverage_failure=bool(eligible and not covered),
        enclosure_state='invalid_evidence' if not eligible else 'covered' if covered else 'certificate_contract_violated',
        bound_public_label='action_supported' if audit['permitted'] else audit['expected_stop'])
    return old|metrics,dict(legacy=legacy,calibration=audit,coverage_evaluation_only=details)
