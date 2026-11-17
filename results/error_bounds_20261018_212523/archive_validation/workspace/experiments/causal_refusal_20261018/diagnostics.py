"""Post-freeze replay diagnostics on saved public inputs and saved current state."""
import argparse,collections,datetime,gzip,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from moral_agent.models import Action,ActionKind,Stakeholder,Situation,to_dict
from moral_agent.affect.appraisal import AppraisalContext,AffectState
from moral_agent.concern_information.world import PublicFrame
from experiments.research_20261018.public import ExtendedEvidence
from experiments.research_20261018.runner import csv_write,write_json
from experiments.action_evidence_20261018.public import Scope,Packet,Claim
from experiments.action_evidence_20261018.verify import rescore,public_reference
from experiments.causal_refusal_20261018.controller import CausalController
from experiments.causal_refusal_20261018.runner import source_hashes


def primary(r):
    return r['accuracy']==.85 and r['budget']==2 and r['representation']=='canonical' and r['allocation']=='fixed' and not r['equal_compute']


def key(r):return r['family'],r['seed'],r['replicate'],r['step']


def public_input(t):
    x=t['public_initial'];s=x['situation']
    situation=Situation(s['goal'],tuple(Action(**(a|{'kind':ActionKind(a['kind'])})) for a in s['candidates']),
                        tuple(Stakeholder(**a) for a in s['stakeholders']),s['context'])
    frame=PublicFrame(situation,ExtendedEvidence(**x['initial']),tuple(x['cues']),tuple(x['candidates']),x['nuisance'],AppraisalContext(**x['context']))
    q=t['packet'];s=q['scope']
    scope=Scope(s['action'],s['revision'],tuple(s['consent_subjects']),tuple(tuple(x) for x in s['event_subjects']),s['coverage_complete'])
    packet=Packet(scope,q['now'],tuple(Claim(**x) for x in q['claims']),q['disputed'])
    if to_dict(frame)!=x or to_dict(packet)!=q:raise ValueError('lossy public input reconstruction')
    return frame,packet,ExtendedEvidence(**t['public_final']['initial'])


def replay(t,config):
    frame,packet,e=public_input(t);out=[];mismatch=[]
    old_by={a['action']['id']:a for a in t['decision_trace']['assessments']}
    for variant in ('current','guilt_event','numeric_set'):
        ctrl=CausalController(variant,config['parameters']);ctrl.bind(packet)
        ctrl.state=AffectState(**t.get('state_before_decision',t['state_trace']['after']))
        ctrl.errors=dict(t['state_trace']['ema'])
        d=ctrl.decide(frame,e);saved=to_dict(d)
        if variant=='current' and saved!=t['decision_trace']:mismatch.append(key(t))
        action=d.selected_action.id if d.selected_action else None
        revised=t|dict(selected_action=action,decision=d.kind.value)
        scored,actions=rescore(revised)
        hard_removed=[]
        for a in d.assessments:
            before=old_by[a.action.id]['evaluation']['hard_violations']
            if not set(before)<=set(a.evaluation.hard_violations):hard_removed.append(a.action.id)
        new_unsupported_alt=action=='alternative' and t['selected_action']!='alternative' and actions['alternative']!='permitted'
        row=dict(variant=variant,family=t['family'],seed=t['seed'],replicate=t['replicate'],step=t['step'],
            old_action=t['selected_action'],new_action=action,old_decision=t['decision'],new_decision=d.kind.value,
            old_unjustified_refusal=t['unjustified_refusal'],old_harmful_action=t['harmful_action'],
            old_safe_task_success=t['safe_task_success'],old_supported_safe_success=t['supported_safe_success'],
            publicly_unsupported_alternative_newly_selected=new_unsupported_alt,old_hard_violations_removed=bool(hard_removed),
            **scored)
        out.append((row,dict(**row,decision_trace=saved,dossier_trace=ctrl.last_dossier,pairing_trace=ctrl.last_pairing,
            fixed_state=to_dict(ctrl.state),hard_removed_actions=hard_removed,public_actions=actions)))
    return out,mismatch


def run(base,old=False):
    name='old_refusal_regression' if old else 'shared_state_diagnostic';out=base/name;out.mkdir(exist_ok=False)
    freeze=json.loads((base/'registration_v1/freeze.json').read_text());config=freeze['config']
    if source_hashes()!=freeze['sources']:raise ValueError('frozen source changed')
    path=ROOT/'results/evidence_20261018_081055/prospective_v1/decisions.jsonl.gz' if old else base/'verification/current_primary_traces.jsonl.gz'
    start=time.perf_counter();rows=[];mismatches=[];selected=0
    with gzip.open(path,'rt',encoding='utf-8') as source,gzip.open(out/'traces.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as target:
        for line in source:
            t=json.loads(line)
            if old and not(t['variant']=='combined_verified' and t['accuracy']==.85 and t['budget']==2 and t['representation']=='canonical'
                    and t['allocation']=='native' and not t['equal_compute'] and t['unjustified_refusal']):continue
            selected+=1;batch,errors=replay(t,config);mismatches.extend(errors)
            for row,trace in batch:rows.append(row);target.write(json.dumps(trace,ensure_ascii=False,separators=(',',':'))+'\n')
    csv_write(out/'decisions.csv',rows);summary=[]
    for v in ('current','guilt_event','numeric_set'):
        batch=[r for r in rows if r['variant']==v]
        summary.append(dict(variant=v,rows=len(batch),refusals_recovered=sum(r['old_unjustified_refusal'] and not r['unjustified_refusal'] for r in batch),
            new_unjustified_refusals=sum(not r['old_unjustified_refusal'] and r['unjustified_refusal'] for r in batch),
            newly_dangerous=sum(not r['old_harmful_action'] and r['harmful_action'] for r in batch),
            danger_removed=sum(r['old_harmful_action'] and not r['harmful_action'] for r in batch),
            safe_success_added=sum(not r['old_safe_task_success'] and r['safe_task_success'] for r in batch),
            safe_success_removed=sum(r['old_safe_task_success'] and not r['safe_task_success'] for r in batch),
            public_unsupported_alt_new=sum(r['publicly_unsupported_alternative_newly_selected'] for r in batch),
            old_hard_violations_removed=sum(r['old_hard_violations_removed'] for r in batch)))
    csv_write(out/'summary.csv',summary)
    info=dict(saved_states=selected,decision_replays=len(rows),current_replay_mismatches=mismatches,
        elapsed_seconds=time.perf_counter()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        note='Same saved public input and current state. Replays are diagnostics, not new independent evidence.')
    write_json(out/'metadata.json',info);print(json.dumps(info),flush=True)
    if mismatches:raise RuntimeError('current replay failed')


def remaining(base):
    out=base/'remaining_refusals';out.mkdir(exist_ok=False);rows=[];counts=collections.Counter();start=time.perf_counter()
    with gzip.open(base/'verification/all_primary_traces.jsonl.gz','rt',encoding='utf-8') as stream:
        for line in stream:
            t=json.loads(line)
            if t['variant'] not in ('current','guilt_event','numeric_set') or not t['unjustified_refusal']:continue
            for a in t['decision_trace']['assessments']:
                aid=a['action']['id']
                if aid not in t['public_audit']['permitted']:continue
                e=a['evaluation'];policy=next(x['policy'] for x in t['policies_trace'] if x['action']==aid);d=t['dossier_trace'] if aid=='alternative' else None
                if e['uncertainty']>=policy['uncertainty_limit']:
                    if d and d['unknown']:
                        slots=[x for x in d['details'] if '/'.join((x['axis'],x['subject'],x['event'])) in d['unknown']]
                        reason='missing_numeric_evidence' if any(x['status']=='missing' and x['axis'] in ('harm','reversibility') for x in slots) else 'numeric_disagreement' if any(x['status']=='conflicting' and x['axis'] in ('harm','reversibility') for x in slots) else 'other_unresolved_evidence'
                    else:reason='inherited_procedural_uncertainty'
                elif e['harm']>=policy['review_harm']:reason='soft_harm_review'
                else:reason='other'
                counts[(t['variant'],reason)]+=1
                rows.append(dict(variant=t['variant'],family=t['family'],seed=t['seed'],replicate=t['replicate'],step=t['step'],action=aid,reason=reason,
                    uncertainty=e['uncertainty'],uncertainty_limit=policy['uncertainty_limit'],harm=e['harm'],reversibility=e['reversibility'],
                    review_harm=policy['review_harm'],unknown=d['unknown'] if d else [],publicly_permitted=True))
    csv_write(out/'paths.csv',rows);csv_write(out/'counts.csv',[dict(variant=v,reason=r,count=n) for (v,r),n in sorted(counts.items())])
    write_json(out/'metadata.json',dict(paths=len(rows),elapsed_seconds=time.perf_counter()-start,
        note='Post-run finer trace attribution, not revised labels, acceptance rules, or independent evidence.'))
    print(json.dumps(dict(counts=[(v,r,n) for (v,r),n in sorted(counts.items())])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);p.add_argument('--old',action='store_true');p.add_argument('--remaining',action='store_true');a=p.parse_args()
    remaining(a.base) if a.remaining else run(a.base,a.old)
