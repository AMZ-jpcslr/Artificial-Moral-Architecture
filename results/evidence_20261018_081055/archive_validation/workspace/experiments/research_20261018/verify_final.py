"""Independent arithmetic checks, diagnostic-correction audit, and preservation."""
import argparse
from collections import defaultdict
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
from experiments.research_20261018.analyze import load_csv, external_rescore, condition_key, primary_row
from experiments.research_20261018.runner import csv_write, write_json, source_hashes


def main():
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path);args=parser.parse_args()
    base=args.base;output=base/'verification_final';output.mkdir(exist_ok=False);start=time.perf_counter()
    rows=load_csv(base/'prospective_v1/decisions.csv')
    groups=defaultdict(list)
    for row in rows:groups[condition_key(row)].append(row)
    discrepancies=[];checked=0
    for saved in load_csv(base/'prospective_v1/all_comparisons.csv'):
        group=groups[condition_key(saved)];families=defaultdict(list)
        for r in group:families[r['family']].append(r)
        for metric,denom in [('safe_task_success','scored'),('task_success','scored'),('harmful_action','scored'),
                              ('over_refusal','over_refusal_eligible'),('safe_alternative_success','safe_alternative_eligible')]:
            rates=[];numerator=denominator=0
            for family in families.values():
                eligible=[r for r in family if r['scored'] and r[denom]]
                if eligible:
                    n=sum(1 for r in eligible if r[metric]);d=len(eligible);rates.append(n/d)
                    numerator+=n;denominator+=d
            expected=statistics.mean(rates) if rates else None
            actual=saved[metric]
            if (expected is None)!=(actual is None) or (expected is not None and abs(expected-actual)>1e-12):
                discrepancies.append(dict(condition=condition_key(saved),metric=metric,expected=expected,actual=actual))
            if numerator!=saved[metric+'_numerator'] or denominator!=saved[metric+'_denominator']:
                discrepancies.append(dict(condition=condition_key(saved),metric=metric,counts_mismatch=True))
            checked+=1
    correction_errors=[];n=0;residual=defaultdict(lambda:defaultdict(int));examples=[]
    with gzip.open(base/'diagnostic_v11/decisions.jsonl.gz','rt',encoding='utf-8') as stream:
        for line in stream:
            r=json.loads(line);n+=1
            if r['public_input']['initial']!=r['updated_evidence']:
                correction_errors.append(dict(row=n,reason='prediction not preserved'))
            for metric,value in external_rescore(r).items():
                if value!=r[metric]:correction_errors.append(dict(row=n,metric=metric))
            if r['prediction']=='oracle' and r['scored'] and r['harmful_action']:
                ref=r['evaluation_only_reference'];key=(r['variant'],r['family'])
                residual[key]['danger_count']+=1
                intermediate=(r['selected_action']=='primary' and .4<=ref['harm']<.5 and not ref['reversible'])
                residual[key]['moderate_irreversible_threshold_gap']+=intermediate
                if len(examples)<8:
                    examples.append({k:r[k] for k in ('variant','family','seed','replicate','step','selected_action','failure_flags')}|
                        {'reference':ref,'assessments':r['decision_trace']['assessments']})
    csv_write(output/'oracle_residuals.csv',[dict(variant=v,family=f,**values) for (v,f),values in sorted(residual.items())])
    write_json(output/'oracle_residual_examples.json',examples)
    # Source freeze and original repository preservation are independent checks.
    locked=json.loads((base/'registration_v1/freeze.json').read_text(encoding='utf-8'))
    current=source_hashes();source_equal=current==locked['sources']
    original=json.loads((base/'preservation/original_files.json').read_text(encoding='utf-8'))
    changed=[]
    for record in original:
        path=ROOT/record['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:
            changed.append(record['path'])
    combined=load_csv(base/'all_comparisons.csv')
    combined += [dict(phase='diagnostic_v11',aggregation_note='post-run measurement correction; privileged diagnostic only',**r)
                 for r in load_csv(base/'diagnostic_v11/all_comparisons.csv')]
    csv_write(base/'all_comparisons_final.csv',combined)
    metadata=dict(checked_summary_metrics=checked,summary_discrepancies=discrepancies,
        diagnostic_rows=n,diagnostic_discrepancies=correction_errors,
        original_files_checked=len(original),original_files_changed=changed,frozen_sources_equal=source_equal,
        finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),elapsed_seconds=time.perf_counter()-start,
        all_comparison_rows=len(combined))
    write_json(output/'verification.json',metadata)
    if discrepancies or correction_errors or changed or not source_equal:raise RuntimeError('verification failed')
    print(json.dumps(metadata,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
