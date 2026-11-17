"""Replay already-evaluated rows on an existing second interpreter."""
import argparse,datetime,gzip,json,platform,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.analyze import load_csv
from experiments.research_20261018.runner import csv_write,write_json
from experiments.action_evidence_20261018.runner import episode,source_hashes
from experiments.action_evidence_20261018.worlds import build_episode

def main():
 p=argparse.ArgumentParser();p.add_argument('base',type=Path);base=p.parse_args().base
 out=base/'cross_runtime_replay';out.mkdir(exist_ok=False);start=time.perf_counter()
 frozen=json.loads((base/'registration_v1/freeze.json').read_text());config=frozen['config']
 if source_hashes()!=frozen['sources']:raise RuntimeError('freeze changed')
 key=lambda r:(r['variant'],r['family'],r['seed'],r['replicate'],r['step'])
 expected={key(r):r for r in load_csv(base/'prospective_v1/decisions.csv') if r['accuracy']==.85 and r['budget']==2
  and r['representation']=='canonical' and r['allocation']=='native' and not r['equal_compute'] and r['seed']==1201 and r['replicate']==0}
 rows=[];errors=[]
 with gzip.open(out/'traces.jsonl.gz','wt',encoding='utf-8') as stream:
  for family in config['families']:
   cases=build_episode(family,1201)
   for variant in ('both','combined','rule','combined_verified','rule_verified'):
    batch,traces=episode(cases,config['primary']|{'variant':variant},config,0);rows.extend(batch)
    for r,t in zip(batch,traces):
     stream.write(json.dumps(t,ensure_ascii=False)+'\n')
     for field,value in r.items():
      if field not in ('policy_seconds','policy_cpu_seconds') and expected[key(r)][field]!=value:
       errors.append(dict(key=key(r),field=field,actual=value,expected=expected[key(r)][field]))
 csv_write(out/'decisions.csv',rows)
 result=dict(rows=len(rows),mismatches=errors,python=sys.version,executable=sys.executable,platform=platform.platform(),
  source_freeze_equal=True,elapsed_seconds=time.perf_counter()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  note='Verification replay, not new independent evidence. All non-time decision CSV fields compared.')
 write_json(out/'verification.json',result);print(json.dumps(result),flush=True)
 if errors:raise SystemExit(1)
if __name__=='__main__':main()
