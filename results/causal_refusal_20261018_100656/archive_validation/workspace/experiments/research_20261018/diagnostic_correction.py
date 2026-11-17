"""A transparent post-run measurement correction; original experiment is retained."""
import argparse
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
from experiments.research_20261018 import runner, worlds
from experiments.research_20261018.metrics import group_summaries
from moral_agent.concern_information.world import keyed


def fixed_diagnostic_prediction(evidence,response):
    """Sensor responses cannot alter a controlled diagnostic forecast intervention."""
    return evidence


def main():
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path);args=parser.parse_args()
    base=args.base;output=base/'diagnostic_v11';registration=base/'diagnostic_registration_v11.json'
    locked=json.loads((base/'registration_v1/freeze.json').read_text(encoding='utf-8'))
    if runner.source_hashes()!=locked['sources']:raise RuntimeError('original frozen implementation changed')
    paths=[Path(__file__),Path(__file__).with_name('DIAGNOSTIC_CORRECTION.md'),base/'registration_v1/freeze.json']
    registered=dict(registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        purpose='post-run correction of initial Oracle forecasts being overwritten by fallible sensor updates',
        changes_to_model_parameters=False,changes_to_labels=False,changes_to_primary_comparison=False,
        files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    if registration.exists():raise FileExistsError(registration)
    runner.write_json(registration,registered)
    output.mkdir(exist_ok=False);started=time.perf_counter();config=locked['config'];rows=[]
    conditions=[config['primary']|{'prediction':p,'variant':v}
                for p in ('oracle','noisy_oracle') for v in ('rule','no_affect','both','combined')]
    runner.write_json(output/'conditions.json',conditions)
    original=runner.apply_response
    try:
        runner.apply_response=fixed_diagnostic_prediction
        with gzip.open(output/'decisions.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as stream:
            for family in config['families']:
                for seed in config['seeds']:
                    cases=worlds.prospective_episode(family,seed)
                    for replicate in config['replicates']:
                        ordered=sorted(conditions,key=lambda c:keyed(family['id'],seed,replicate,'v11order',json.dumps(c,sort_keys=True)))
                        for condition in ordered:
                            batch,traces=runner.run_episode(cases,condition,config,replicate)
                            rows.extend(batch)
                            for trace in traces:
                                if trace['updated_evidence']!=trace['public_input']['initial']:
                                    raise RuntimeError('diagnostic forecast changed')
                                trace['diagnostic_correction']='v1.1: controlled prediction retained; obtained sensor reply not used'
                                stream.write(json.dumps(trace,ensure_ascii=False,separators=(',',':'))+'\n')
                print(json.dumps({'family':family['id'],'decisions':len(rows),'seconds':time.perf_counter()-started}),flush=True)
    finally:
        runner.apply_response=original
    if runner.apply_response is not original:raise RuntimeError('failed to restore simulator interface')
    if runner.source_hashes()!=locked['sources']:raise RuntimeError('frozen source changed during diagnostics')
    runner.csv_write(output/'decisions.csv',rows)
    runner.csv_write(output/'all_comparisons.csv',group_summaries(rows))
    runner.csv_write(output/'by_family.csv',group_summaries(rows,('family',)))
    runner.csv_write(output/'by_failure.csv',group_summaries(rows,('failure_class',)))
    runner.csv_write(output/'paired_ci.csv',runner.contrasts(rows,config))
    runner.write_json(output/'metadata.json',dict(decision_runs=len(rows),episode_runs=len(rows)//8,
        elapsed_seconds=time.perf_counter()-started,queries=sum(r['query_count'] for r in rows),
        audit_decisions=sum(r['audit_decisions'] for r in rows),virtual_decisions=sum(r['virtual_decisions'] for r in rows),
        diagnostic_prediction_preserved_all_rows=True,original_frozen_sources_unchanged=True,
        operating_model_comparison_unchanged=True,not_new_unseen_data=True,
        finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    print('Diagnostic correction saved:',output)


if __name__=='__main__':main()
