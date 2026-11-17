"""Verification on an existing second Python, not new independent evidence."""
import argparse,datetime,gzip,json,platform,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.analyze import load_csv
from experiments.research_20261018.runner import csv_write,write_json
from experiments.causal_refusal_20261018.runner import episode,source_hashes
from experiments.causal_refusal_20261018.worlds import build_episode
from experiments.causal_refusal_20261018.controller import VARIANTS
from experiments.causal_refusal_20261018.diagnostics import primary,key


def main():
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);base=p.parse_args().base
    out=base/'cross_runtime_replay';out.mkdir(exist_ok=False);start=time.perf_counter()
    freeze=json.loads((base/'registration_v1/freeze.json').read_text());config=freeze['config']
    if source_hashes()!=freeze['sources']:raise ValueError('source changed')
    seed=config['seeds'][0]
    expected={(r['variant'],*key(r)):r for r in load_csv(base/'prospective_v1/decisions.csv') if primary(r) and r['seed']==seed and r['replicate']==0}
    rows=[];errors=[]
    with gzip.open(out/'traces.jsonl.gz','wt',encoding='utf-8') as target:
        for family in config['families']:
            cases=build_episode(family,seed)
            for variant in VARIANTS:
                batch,traces=episode(cases,config['primary']|dict(variant=variant),config,0);rows.extend(batch)
                for r,t in zip(batch,traces):
                    target.write(json.dumps(t,ensure_ascii=False)+'\n');old=expected[(variant,*key(r))]
                    for k,v in r.items():
                        if k not in ('policy_seconds','policy_cpu_seconds') and old[k]!=v:
                            errors.append(dict(key=(variant,*key(r)),field=k,expected=old[k],actual=v))
    csv_write(out/'decisions.csv',rows)
    info=dict(decisions=len(rows),non_time_mismatches=errors,python=sys.version,executable=sys.executable,platform=platform.platform(),
        elapsed_seconds=time.perf_counter()-start,source_freeze_equal=True,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write_json(out/'verification.json',info);print(json.dumps(info),flush=True)
    if errors:raise RuntimeError('cross-runtime replay mismatch')


if __name__=='__main__':main()
