"""Frozen offline comparison; never executes a real action."""
import argparse,copy,datetime,gzip,hashlib,json,sys,time
from dataclasses import replace
from pathlib import Path
from moral_agent.models import to_dict
from moral_agent.concern_information.world import apply_response,CHANNELS,keyed
from experiments.research_20261018.runner import csv_write,write_json
from .public import Packet,Claim,projection
from .controller import EvidenceController,VARIANTS
from .evaluation import score
from .metrics import GROUP,RATES,summaries,paired
from . import worlds

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent


def source_hashes():
    paths=list((ROOT/'src/moral_agent').rglob('*.py'))
    paths+=list((ROOT/'experiments/research_20261018').glob('*.py'))
    paths+=[HERE/p for p in ('__init__.py','public.py','controller.py','worlds.py','evaluation.py','metrics.py','runner.py','config.json','PROTOCOL.md')]
    paths+=[ROOT/'tests/test_action_evidence.py',ROOT/'experiments/run_action_evidence.py']
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def conditions(config,development=False):
    base=config['primary'];matrix=[base|{'variant':v} for v in VARIANTS]
    main=('both','combined','rule','combined_verified','rule_verified')
    if not development:
        extras=[{'accuracy':.65},{'accuracy':1.0},{'budget':0},{'budget':1},
                {'representation':'paraphrase_ja'},{'representation':'paraphrase_en'},
                {'allocation':'fixed'},{'equal_compute':True}]
        matrix.extend(base|changes|{'variant':v} for changes in extras for v in main)
    return matrix


def episode(cases,condition,config,replicate):
    ctrl=EvidenceController(condition['variant'],config['parameters']);rows=[];traces=[];previous=None
    for raw in cases:
        case=worlds.represent(raw,condition['representation']);frame=case.frame;packet=case.packet
        before=dict(ctrl.counts);tick=time.perf_counter();cpu=time.process_time()
        feedback=ctrl.observe(*previous) if previous else None
        ctrl.bind(packet);state=ctrl.prepare(frame);returned=();response=None;reason=None;channel=None
        if condition['budget']>=1:
            returned=worlds.dossier_query(case,condition['accuracy'],replicate)
            packet=replace(packet,claims=packet.claims+returned)
        ctrl.bind(packet)
        evidence=projection(frame.initial,packet,ctrl.verified,consent=ctrl.check_consent,side_effects=ctrl.check_side)
        if condition['budget']>=2:
            if condition['allocation']=='fixed':channel=CHANNELS[(case.step+case.seed)%len(CHANNELS)];reason={'allocation':'fixed'}
            else:channel,reason=ctrl.choose(replace(frame,initial=evidence),case.step,case.seed%5)
            response=worlds.legacy_query(case,channel,condition['accuracy'],replicate);evidence=apply_response(evidence,response)
            if channel=='alternative':
                availability=Claim(packet.scope.action,packet.scope.revision,'resource','availability','available',
                    response.value['alternative'],'resource',.95,packet.now,packet.now+2)
                packet=replace(packet,claims=packet.claims+(availability,));ctrl.bind(packet)
                evidence=projection(evidence,packet,ctrl.verified,consent=ctrl.check_consent,side_effects=ctrl.check_side)
        if condition['equal_compute']:
            used=ctrl.counts['virtual_decisions']-before['virtual_decisions']
            for _ in range(14-used):ctrl.decide(frame,evidence,virtual=True)
        decision=ctrl.decide(frame,evidence)
        seconds=time.perf_counter()-tick;cpu_seconds=time.process_time()-cpu
        count={k:ctrl.counts[k]-before[k] for k in ctrl.counts}
        if count['virtual_decisions']>14:raise RuntimeError('virtual computation budget exceeded')
        if condition['equal_compute'] and count['virtual_decisions']!=14:raise RuntimeError('padding failed')
        final_frame=replace(frame,initial=evidence)
        results,audit=score(case,final_frame,packet,decision)
        row=condition|dict(family=case.family,profile=case.profile,seed=case.seed,step=case.step,replicate=replicate,
            decision=decision.kind.value,selected_action=decision.selected_action.id if decision.selected_action else None,
            query_channel=channel,query_count=condition['budget'],query_cost=float(condition['budget']),returned_claims=len(returned),
            policy_seconds=seconds,policy_cpu_seconds=cpu_seconds,**count,**results)
        trace=row|dict(public_initial=to_dict(frame),initial_packet=to_dict(case.packet),public_final=to_dict(final_frame),
            packet=to_dict(packet),received_claims=to_dict(returned),response=to_dict(response),query_reason=reason,
            state_trace=state,delivered_feedback=feedback,decision_trace=to_dict(decision),dossier_trace=ctrl.last_dossier,
            public_audit=audit,evaluation_only=dict(primary=to_dict(case.primary_truth),consents=case.consents,
                events=case.events,available=case.available,ambiguous=case.ambiguous,key=case.key))
        rows.append(row);traces.append(trace)
        selected=row['selected_action'];previous=(frame,selected,worlds.feedback(case,selected)) if selected else None
    return rows,traces


def execute(config,out,development=False):
    out.mkdir(parents=True,exist_ok=False);start=time.perf_counter();rows=[];n=0
    families=[{'id':'development_manual','profile':'development_probe'}] if development else config['families']
    seeds=[37,41] if development else config['seeds'];reps=[0] if development else config['replicates']
    matrix=conditions(config,development)
    with gzip.open(out/'decisions.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as stream:
        for family in families:
            for seed in seeds:
                cases=worlds.build_episode(family,seed)
                order=sorted(matrix,key=lambda c:keyed(family['id'],seed,json.dumps(c,sort_keys=True)))
                for rep in reps:
                    for condition in order:
                        batch,traces=episode(cases,condition,config,rep);rows.extend(batch);n+=len(batch)
                        for trace in traces:stream.write(json.dumps(trace,ensure_ascii=False,separators=(',',':'))+'\n')
                write_json(out/'progress.json',dict(family=family['id'],seed=seed,decisions=n,elapsed_seconds=time.perf_counter()-start))
            print(f"{family['id']} complete: {n} decisions",flush=True)
    csv_write(out/'decisions.csv',rows)
    csv_write(out/'all_comparisons.csv',summaries(rows))
    for axis in ('family','severity','profile','public_label'):
        csv_write(out/f'by_{axis}.csv',summaries(rows,(axis,)))
    groups={}
    for r in rows:groups.setdefault(tuple(r[k] for k in GROUP[:-1]),[]).append(r)
    contrasts=[]
    for key,batch in groups.items():
        available={r['variant'] for r in batch}
        for left,right in [('combined_verified','combined'),('combined_verified','both'),('combined_verified','rule'),
                           ('combined_verified','rule_verified'),('combined_verified','history_verified'),
                           ('combined_verified','combined_no_consent'),('combined_verified','combined_no_side_effects')]:
            if {left,right}<=available:
                for metric in RATES:
                    contrasts.append(dict(zip(GROUP[:-1],key))|paired(batch,left,right,metric,config['bootstrap'],config['bootstrap_seed']))
    csv_write(out/'paired_ci.csv',contrasts)
    metadata=dict(phase='development' if development else 'prospective',decision_runs=n,conditions=len(matrix),
        families=len(families),seeds=len(seeds),sensor_replicates=len(reps),unique_world_states=len(families)*len(seeds)*8,
        queries=sum(r['query_count'] for r in rows),virtual_decisions=sum(r['virtual_decisions'] for r in rows),
        policy_seconds=sum(r['policy_seconds'] for r in rows),elapsed_seconds=time.perf_counter()-start,
        finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_hashes=source_hashes(),
        paid_api_calls=0,external_actions=0)
    write_json(out/'metadata.json',metadata);return metadata


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['development','freeze','prospective'],required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--freeze',type=Path);parser.add_argument('--development',type=Path)
    args=parser.parse_args();config=json.loads((HERE/'config.json').read_text())
    if args.phase=='freeze':
        dev=json.loads((args.development/'metadata.json').read_text())
        if dev['source_hashes']!=source_hashes():raise ValueError('sources changed after development')
        args.output.mkdir(parents=True,exist_ok=False)
        result=dict(config=config,sources=source_hashes(),frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            development=str(args.development),parameters_tuned=False,new_families_not_yet_evaluated=True)
        write_json(args.output/'freeze.json',result)
    else:
        if args.phase=='prospective':
            frozen=json.loads(args.freeze.read_text())
            if frozen['sources']!=source_hashes() or frozen['config']!=config:raise ValueError('freeze mismatch')
        result=execute(config,args.output,args.phase=='development')
    print(json.dumps({k:v for k,v in result.items() if k not in ('config','sources','source_hashes')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
