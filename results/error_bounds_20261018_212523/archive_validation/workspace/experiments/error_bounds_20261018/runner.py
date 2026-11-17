"""Frozen experiment; no scoring or truth feeds back into decision-making."""
import argparse,datetime,gzip,hashlib,json,time
from dataclasses import replace
from pathlib import Path
from moral_agent.models import to_dict
from moral_agent.concern_information.world import apply_response,CHANNELS,keyed
from experiments.action_evidence_20261018.public import Claim,projection
from experiments.research_20261018.runner import csv_write,write_json
from experiments.causal_refusal_20261018.runner import source_hashes as inherited_hashes
from . import worlds,probes
from .controller import BoundController,VARIANTS
from .evaluation import score
from .metrics import GROUP,RATES,summaries,paired

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent


def source_hashes():
    hashes=inherited_hashes()
    paths=[HERE/p for p in ('__init__.py','public.py','controller.py','worlds.py','probes.py','evaluation.py','metrics.py','runner.py','config.json','PROTOCOL.md')]
    paths += [ROOT/'tests/test_error_bounds.py',ROOT/'experiments/run_error_bounds.py']
    hashes.update({p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    return dict(sorted(hashes.items()))


def conditions(config,development=False):
    base=config['primary'];changes=[{}] if development else [{},{'accuracy':.65},{'accuracy':1.},
        {'budget':0},{'budget':1},{'representation':'paraphrase_ja'},{'representation':'paraphrase_en'},{'equal_compute':True}]
    return [base|c|dict(variant=v) for c in changes for v in VARIANTS]


def primary(r):return r['accuracy']==.85 and r['budget']==2 and r['representation']=='canonical' and not r['equal_compute']
def key(r):return r['family'],r['seed'],r['replicate'],r['step']


def episode(cases,condition,config,replicate,bundles=None):
    ctrl=BoundController(condition['variant'],config['parameters']);rows=[];traces=[];previous=None
    for raw in cases:
        case=worlds.represent(raw,condition['representation']);frame=case.frame;packet=case.packet
        before=dict(ctrl.counts);tick=time.perf_counter();cpu=time.process_time()
        feedback=ctrl.observe(*previous) if previous else None
        ctrl.bind(packet);state=ctrl.prepare(frame);returned=();certs=();measurements=();response=None;channel=None
        if condition['budget']>=1:
            returned,certs,measurements=bundles[case.key] if bundles is not None else worlds.dossier_query(case,condition['accuracy'],replicate)
            packet=replace(packet,claims=packet.claims+returned,certificates=certs,measurements=measurements)
        ctrl.bind(packet);evidence=projection(frame.initial,packet,strict=True)
        extra_claims=0
        if condition['budget']>=2:
            channel=CHANNELS[(case.step+case.seed)%len(CHANNELS)]
            response=worlds.legacy_query(case,channel,condition['accuracy'],replicate);evidence=apply_response(evidence,response)
            if channel=='alternative':
                claim=Claim(packet.scope.action,packet.scope.revision,'resource','availability','available',
                            response.value['alternative'],'resource',.95,packet.now,packet.now+2)
                packet=replace(packet,claims=packet.claims+(claim,));ctrl.bind(packet);extra_claims=1
                evidence=projection(evidence,packet,strict=True)
        if condition['equal_compute']:
            for _ in range(14):ctrl.decide(frame,evidence,virtual=True)
        state_before=to_dict(ctrl.state);decision=ctrl.decide(frame,evidence)
        seconds=time.perf_counter()-tick;cpu_seconds=time.process_time()-cpu
        counts={k:ctrl.counts[k]-before[k] for k in ctrl.counts}
        final=replace(frame,initial=evidence);results,audit=score(case,final,packet,decision)
        public=to_dict(packet);point_count=sum(len(c.points) for c in certs)
        row=condition|dict(family=case.family,profile=case.profile,mechanism=case.mechanism,seed=case.seed,step=case.step,replicate=replicate,
            decision=decision.kind.value,selected_action=decision.selected_action.id if decision.selected_action else None,
            query_channel=channel,query_count=condition['budget'],query_cost=float(condition['budget']),returned_claims=len(returned)+extra_claims,
            returned_certificates=len(certs),returned_measurements=len(measurements),returned_calibration_points=point_count,
            returned_records=len(returned)+extra_claims+len(certs)+len(measurements)+point_count,
            public_bytes=len(json.dumps([public,to_dict(response)],sort_keys=True).encode()),
            policy_seconds=seconds,policy_cpu_seconds=cpu_seconds,**counts,**results)
        trace=row|dict(public_initial=to_dict(frame),public_final=to_dict(final),packet=public,received_claims=to_dict(returned),
            response=to_dict(response),state_trace=state,state_before_decision=state_before,delivered_feedback=feedback,
            decision_trace=to_dict(decision),dossier_trace=ctrl.last_dossier,policies_trace=ctrl.last_policies,
            public_audit=audit['legacy'],bound_public_audit=audit['calibration'],
            evaluation_only=dict(primary=to_dict(case.primary_truth),consents=case.consents,events=case.events,
                available=case.available,ambiguous=case.ambiguous,key=case.key,coverage=audit['coverage_evaluation_only']))
        rows.append(row);traces.append(trace)
        selected=row['selected_action'];previous=(frame,selected,worlds.feedback(case,selected)) if selected else None
    return rows,traces


def execute(config,out,development=False):
    out.mkdir(parents=True,exist_ok=False);start=time.perf_counter();rows=[];matrix=conditions(config,development)
    bundles=None
    if development:
        cases,bundles=probes.development_cases();episodes=[('manual_development',47,cases)];reps=[0,1]
    else:
        episodes=((f['id'],s,worlds.build_episode(f,s)) for f in config['families'] for s in config['seeds']);reps=config['replicates']
    with gzip.open(out/'decisions.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as stream:
        for family,seed,cases in episodes:
            order=sorted(matrix,key=lambda c:keyed(family,seed,json.dumps(c,sort_keys=True)))
            for rep in reps:
                for condition in order:
                    batch,traces=episode(cases,condition,config,rep,bundles);rows.extend(batch)
                    for trace in traces:stream.write(json.dumps(trace,ensure_ascii=False,separators=(',',':'))+'\n')
            write_json(out/'progress.json',dict(family=family,seed=seed,decisions=len(rows),elapsed_seconds=time.perf_counter()-start))
            if development or seed==config['seeds'][-1]:print(f'{family}: {len(rows)} decisions',flush=True)
    csv_write(out/'decisions.csv',rows);csv_write(out/'all_comparisons.csv',summaries(rows))
    for axis in ('family','severity','mechanism','profile','public_label','bound_public_label','seed','replicate','enclosure_state'):
        csv_write(out/f'by_{axis}.csv',summaries(rows,(axis,)))
    groups={}
    for r in rows:groups.setdefault(tuple(r[k] for k in GROUP[:-1]),[]).append(r)
    contrasts=[]
    for condition,batch in groups.items():
        for left,right in [('bound_verified','numeric_set'),('bound_verified','current'),('rule_bound_verified','bound_verified'),('numeric_set','current')]:
            for metric in RATES:contrasts.append(dict(zip(GROUP[:-1],condition))|paired(batch,left,right,metric,config['bootstrap'],config['bootstrap_seed']))
    csv_write(out/'paired_ci.csv',contrasts)
    info=dict(phase='development' if development else 'prospective',decision_runs=len(rows),conditions=len(matrix),
        families=1 if development else len(config['families']),unique_world_states=6 if development else len(config['families'])*len(config['seeds'])*8,
        queries=sum(r['query_count'] for r in rows),returned_records=sum(r['returned_records'] for r in rows),
        virtual_decisions=sum(r['virtual_decisions'] for r in rows),predictions=sum(r['predictions'] for r in rows),
        policy_seconds=sum(r['policy_seconds'] for r in rows),elapsed_seconds=time.perf_counter()-start,
        source_hashes=source_hashes(),finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),paid_api_calls=0,external_actions=0)
    write_json(out/'metadata.json',info);return info


def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['development','freeze','prospective'],required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--freeze',type=Path);p.add_argument('--development',type=Path)
    a=p.parse_args();config=json.loads((HERE/'config.json').read_text())
    if a.phase=='freeze':
        dev=json.loads((a.development/'metadata.json').read_text())
        if dev['source_hashes']!=source_hashes():raise ValueError('changed since development')
        a.output.mkdir(parents=True,exist_ok=False);info=dict(config=config,sources=source_hashes(),
            frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),development=str(a.development),parameters_tuned=False,
            prospective_not_yet_evaluated=True,independent_human_annotation=False)
        write_json(a.output/'freeze.json',info)
    else:
        if a.phase=='prospective':
            freeze=json.loads(a.freeze.read_text())
            if freeze['sources']!=source_hashes() or freeze['config']!=config:raise ValueError('freeze mismatch')
        info=execute(config,a.output,a.phase=='development')
    print(json.dumps({k:v for k,v in info.items() if k not in ('config','sources','source_hashes')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
