"""Post-hoc local factorial explanation, never a new trained/model candidate.

Crosses saved evidence, saved affect history, and the final candidate-scope rule.
All 2,304 paired primary rows are retained. This is an algebraic attribution under
artificial state interventions, not uniquely identified real-world mediation.
"""
import argparse
from collections import defaultdict
from dataclasses import replace
import datetime
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
from moral_agent.affect.appraisal import AffectState
from moral_agent.models import to_dict
from experiments.research_20261018.controllers import ResearchController,identifier
from experiments.research_20261018.public import ExtendedEvidence
from experiments.research_20261018 import worlds
from experiments.research_20261018.runner import source_hashes,csv_write,write_json
from experiments.research_20261018.analyze import case_key,primary_row


METRICS=('safe_task_success','harmful_action','over_refusal','realized_harm')
FACTORS=('candidate_scope','obtained_evidence','affect_history')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path);args=parser.parse_args()
    base=args.base;out=base/'mechanism_audit';out.mkdir(exist_ok=False)
    frozen=json.loads((base/'registration_v1/freeze.json').read_text(encoding='utf-8'))
    if source_hashes()!=frozen['sources']:raise RuntimeError('source changed')
    write_json(out/'registration.json',dict(registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        timing='post-hoc explanatory audit after primary outcomes; not preregistered evidence of generalization',
        protocol='All 2304 paired primary rows, 2x2x2 local final-decision crossings of scope/evidence/affect state; unchanged model, labels, adoption criteria. Six-order mean marginal attribution.',
        original_freeze_sha256=hashlib.sha256((base/'registration_v1/freeze.json').read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    start=time.perf_counter();pairs=defaultdict(dict)
    with gzip.open(base/'prospective_v1/decisions.jsonl.gz','rt',encoding='utf-8') as stream:
        for line in stream:
            trace=json.loads(line)
            if primary_row(trace) and trace['variant'] in ('both','combined'):
                pairs[case_key(trace)][trace['variant']]=trace
    cases={}
    for family in frozen['config']['families']:
        for seed in frozen['config']['seeds']:
            for case in worlds.prospective_episode(family,seed):cases[(family['id'],seed,case.step)]=case
    records=[];attributions=[];endpoint_errors=[];decomposition_errors=[]
    with gzip.open(out/'decision_traces.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as stream:
        for key,traces in sorted(pairs.items()):
            if set(traces)!={'both','combined'}:raise RuntimeError('unpaired trace')
            b,c=traces['both'],traces['combined'];f,seed,replicate,step=key;case=cases[(f,seed,step)]
            results={}
            for mask in range(8):
                scope=bool(mask&1);evidence_trace=c if mask&2 else b;state_trace=c if mask&4 else b
                controller=ResearchController('combined' if scope else 'both',frozen['config']['parameters'])
                controller.state=AffectState(**state_trace['state_trace']['after'])
                controller.errors=dict(state_trace['state_trace']['ema'])
                evidence=ExtendedEvidence(**evidence_trace['updated_evidence'])
                decision=controller.decide(case.world.frame,evidence)
                scored=worlds.score(case,decision);results[mask]=scored
                row=dict(family=f,seed=seed,replicate=replicate,step=step,mask=mask,
                    candidate_scope='combined' if scope else 'both',
                    obtained_evidence='combined' if mask&2 else 'both',
                    affect_history='combined' if mask&4 else 'both',
                    decision=decision.kind.value,selected_action=identifier(decision),**scored)
                records.append(row)
                stream.write(json.dumps(row|{'decision_trace':to_dict(decision)},ensure_ascii=False,separators=(',',':'))+'\n')
                if mask in (0,7):
                    expected=b if mask==0 else c
                    if (row['decision'],row['selected_action'])!=(expected['decision'],expected['selected_action']):
                        endpoint_errors.append(dict(key=key,mask=mask))
                    for metric in METRICS:
                        if row[metric]!=expected[metric]:endpoint_errors.append(dict(key=key,mask=mask,metric=metric))
            attribution=dict(family=f,seed=seed,replicate=replicate,step=step,
                scored=results[0]['scored'],over_refusal_eligible=results[0]['over_refusal_eligible'])
            for metric in METRICS:
                contributions=[0.,0.,0.]
                for order in itertools.permutations(range(3)):
                    mask=0
                    for factor in order:
                        changed=mask|(1<<factor)
                        contributions[factor]+=(int(results[changed][metric])-int(results[mask][metric]))/6
                        mask=changed
                delta=int(results[7][metric])-int(results[0][metric])
                if abs(sum(contributions)-delta)>1e-12:decomposition_errors.append(dict(key=key,metric=metric))
                attribution[metric+'_total_delta']=delta
                for factor,value in zip(FACTORS,contributions):attribution[metric+'__'+factor]=value
            attributions.append(attribution)
    summaries=[]
    for metric in METRICS:
        for factor in FACTORS:
            by_family=defaultdict(list)
            for row in attributions:
                eligible=True if metric=='realized_harm' else row['scored'] and (row['over_refusal_eligible'] if metric=='over_refusal' else True)
                if eligible:by_family[row['family']].append(row[metric+'__'+factor])
            means={family:sum(values)/len(values) for family,values in by_family.items()}
            summaries.append(dict(metric=metric,factor=factor,family_clusters=len(means),
                mean_contribution=sum(means.values())/len(means),family_contributions=means,
                interpretation='local factorial mean marginal attribution; post-hoc, not unique causal mediation'))
    csv_write(out/'factorial_decisions.csv',records);csv_write(out/'local_attributions.csv',attributions)
    csv_write(out/'summary.csv',summaries)
    write_json(out/'verification.json',dict(paired_rows=len(pairs),local_diagnostic_decisions=len(records),
        endpoint_mismatches=endpoint_errors,decomposition_mismatches=decomposition_errors,
        elapsed_seconds=time.perf_counter()-start,source_hashes_still_frozen=source_hashes()==frozen['sources']))
    if endpoint_errors or decomposition_errors:raise RuntimeError('mechanism audit failed')
    print(json.dumps({'paired_rows':len(pairs),'diagnostic_decisions':len(records),'seconds':time.perf_counter()-start}),flush=True)


if __name__=='__main__':main()
