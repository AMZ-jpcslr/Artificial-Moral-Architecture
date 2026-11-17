"""Small cross-process, cross-interpreter replay; not a fresh evaluation set."""
import argparse
import gzip
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
from experiments.research_20261018.runner import run_episode, source_hashes, csv_write, write_json
from experiments.research_20261018.worlds import prospective_episode
from experiments.research_20261018.analyze import load_csv, primary_row, case_key


def main():
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path);args=parser.parse_args()
    base=args.base;out=base/'verification_replay';out.mkdir(exist_ok=False)
    freeze=json.loads((base/'registration_v1/freeze.json').read_text(encoding='utf-8'))
    if source_hashes()!=freeze['sources']:raise RuntimeError('source changed')
    config=freeze['config'];variants=('rule','history','both','combined');seed=config['seeds'][0]
    saved={(r['family'],r['variant'],r['step']):r for r in load_csv(base/'prospective_v1/decisions.csv')
           if primary_row(r) and r['variant'] in variants and r['seed']==seed and r['replicate']==0}
    differences=[];rows=[];start=time.perf_counter()
    ignore={'policy_seconds','policy_cpu_seconds'}
    with gzip.open(out/'replay_traces.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as stream:
        for family in config['families']:
            cases=prospective_episode(family,seed)
            for variant in variants:
                batch,traces=run_episode(cases,config['primary']|{'variant':variant},config,0,audit=False)
                for row,trace in zip(batch,traces):
                    old=saved[(row['family'],variant,row['step'])]
                    for key,value in row.items():
                        if key not in ignore and old[key]!=value:
                            differences.append(dict(family=family['id'],variant=variant,step=row['step'],field=key,old=old[key],new=value))
                    rows.append(row);stream.write(json.dumps(trace,ensure_ascii=False,separators=(',',':'))+'\n')
    csv_write(out/'decisions.csv',rows)
    write_json(out/'verification.json',dict(decisions=len(rows),fields_match_except_timing=not differences,
        differences=differences,elapsed_seconds=time.perf_counter()-start,python=sys.version,executable=sys.executable,
        python_hash_seed=os.environ.get('PYTHONHASHSEED'),frozen_sources_equal=source_hashes()==freeze['sources'],
        scope='12 families, first frozen seed, replicate 0, four current-prediction methods; already evaluated cases'))
    if differences:raise RuntimeError('replay differs')
    print('Replay matched:',len(rows),'decisions; Python',sys.version)


if __name__=='__main__':main()
