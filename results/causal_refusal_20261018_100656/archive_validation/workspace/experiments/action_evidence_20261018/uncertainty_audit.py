"""Describe unresolved evidence in already-observed unjustified refusals."""
import argparse,collections,gzip,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.runner import csv_write,write_json
from experiments.action_evidence_20261018.analyze import primary

def main():
 p=argparse.ArgumentParser();p.add_argument('base',type=Path);base=p.parse_args().base
 out=base/'uncertainty_audit';out.mkdir(exist_ok=False);rows=[];start=time.perf_counter()
 with gzip.open(base/'prospective_v1/decisions.jsonl.gz','rt',encoding='utf-8') as stream:
  for line in stream:
   t=json.loads(line)
   if not primary(t) or t['variant']!='combined_verified' or not t['unjustified_refusal']:continue
   d=t['dossier_trace']
   if not d['unknown']:continue
   details=[x for x in d['details'] if x['status']!='known']
   rows.append(dict(family=t['family'],seed=t['seed'],replicate=t['replicate'],step=t['step'],unknown=d['unknown'],
    unresolved_details=details,events=d['events'],public_permitted=t['public_audit']['permitted'],dossier_status=d['status']))
 csv_write(out/'unresolved_but_action_supported.csv',rows)
 counts=collections.Counter((x['axis'],x['status']) for r in rows for x in r['unresolved_details'])
 result=dict(refusals=len(rows),all_unknown_axes_reversibility=all(all(x.startswith('reversibility/') for x in r['unknown']) for r in rows),
  all_affected_events_harm_below_point4=all(all(e['harm'] is not None and e['harm']<.4 for e in r['events']
    if any(x['event']==e['event'] and x['subject']==e['subject'] for x in r['unresolved_details'])) for r in rows),
  unresolved_slots=[dict(axis=a,status=s,n=n) for (a,s),n in sorted(counts.items())],elapsed_seconds=time.perf_counter()-start,
  note='Robust public audit can authorize despite uncertain reversibility when every possible value is safe. Strict dossier gate requires singleton values and stops.')
 write_json(out/'metadata.json',result);print(json.dumps(result),flush=True)
if __name__=='__main__':main()
