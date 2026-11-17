"""Independent CSV arithmetic and post-run descriptive diagnostics; no fitting."""
import argparse,collections,csv,datetime,json,math,statistics,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.analyze import load_csv
from experiments.research_20261018.runner import csv_write,write_json

GROUP=('accuracy','budget','representation','allocation','equal_compute','variant')
# Written independently from the frozen aggregator, according to PLAN.md.
DENOMINATORS={'task_success':'scored','safe_task_success':'scored','supported_safe_success':'scored',
 'harmful_action':'scored','realized_harm':None,'unjustified_refusal':'unjustified_refusal_eligible',
 'unsupported_execution':None,'necessary_stop_recall':'necessary_stop_eligible',
 'correct_stop_kind':'necessary_stop_eligible','objective_opportunity_stop':'objective_stop_eligible',
 'safe_alternative_success':'safe_alternative_eligible','unavailable_action':None,'ask_human':None}
NUMERATORS={'necessary_stop_recall':'necessary_stop','correct_stop_kind':'stop_kind_correct'}
def primary(r):return (r['accuracy'],r['budget'],r['representation'],r['allocation'],r['equal_compute'])==(.85,2,'canonical','native',False)
def key(r):return tuple(r[x] for x in ('family','seed','replicate','step'))

def main():
 p=argparse.ArgumentParser();p.add_argument('base',type=Path);base=p.parse_args().base
 out=base/'arithmetic_audit';out.mkdir(exist_ok=False);start=time.perf_counter()
 rows=load_csv(base/'prospective_v1/decisions.csv');groups=collections.defaultdict(list)
 for r in rows:groups[tuple(r[x] for x in GROUP)].append(r)
 summaries=load_csv(base/'prospective_v1/all_comparisons.csv');checks=0;errors=[]
 for summary in summaries:
  g=groups[tuple(summary[x] for x in GROUP)]
  for metric,den in DENOMINATORS.items():
   numerator=NUMERATORS.get(metric,metric);eligible=[r for r in g if den is None or r[den]]
   n=sum(bool(r[numerator]) for r in eligible);d=len(eligible);rates=[]
   for family in sorted({r['family'] for r in g}):
    subset=[r for r in eligible if r['family']==family]
    if subset:rates.append(sum(bool(r[numerator]) for r in subset)/len(subset))
   expected={metric:statistics.mean(rates) if rates else None,metric+'_numerator':n,metric+'_denominator':d,
    metric+'_pooled':n/d if d else None,metric+'_families':len(rates),metric+'_family_min':min(rates) if rates else None,
    metric+'_family_max':max(rates) if rates else None,metric+'_family_sd':statistics.stdev(rates) if len(rates)>1 else None}
   for field,value in expected.items():
    checks+=1;actual=summary[field]
    if not ((value is None and actual is None) or (value is not None and actual is not None and math.isclose(value,actual,abs_tol=1e-12))):
     errors.append(dict(condition={x:summary[x] for x in GROUP},field=field,expected=value,actual=actual))
 main_rows=[r for r in rows if primary(r)];by={v:{key(r):r for r in main_rows if r['variant']==v} for v in ('combined','combined_verified')}
 losses=[];gains=[];residual=[]
 for k,b in sorted(by['combined'].items()):
  a=by['combined_verified'][k]
  if b['safe_task_success'] and not a['safe_task_success']:
   losses.append(dict(family=k[0],seed=k[1],replicate=k[2],step=k[3],old_action=b['selected_action'],new_action=a['selected_action'],
    old_supported=b['supported_safe_success'],old_unsupported=b['unsupported_execution'],new_danger=a['harmful_action'],new_unjustified=a['unjustified_refusal']))
  if a['safe_task_success'] and not b['safe_task_success']:gains.append(a)
 for (profile,action),subset in __import__('itertools').groupby(sorted(by['combined_verified'].values(),key=lambda r:(r['profile'],r['selected_action'] or '')),key=lambda r:(r['profile'],r['selected_action'])):
  batch=list(subset);residual.append(dict(profile=profile,action=action,n=len(batch),danger=sum(r['harmful_action'] and r['scored'] for r in batch),
   unsupported=sum(r['unsupported_execution'] for r in batch),unjustified=sum(r['unjustified_refusal'] for r in batch),realized=sum(r['realized_harm'] for r in batch)))
 csv_write(out/'safe_success_losses.csv',losses);csv_write(out/'residual_by_profile_action.csv',residual)
 residual_precision=[]
 for r in rows:
  if r['variant']=='combined_verified' and r['accuracy']==1 and r['scored'] and r['harmful_action']:
   residual_precision.append({k:r[k] for k in ('family','profile','seed','replicate','step','selected_action','unsupported_execution')})
 csv_write(out/'residual_danger_accuracy1.csv',residual_precision)
 result=dict(summary_conditions=len(summaries),arithmetic_cells_checked=checks,arithmetic_errors=errors,
  safe_success_lost=len(losses),lost_previously_unsupported=sum(r['old_unsupported'] for r in losses),
  lost_previously_supported=sum(r['old_supported'] for r in losses),safe_success_gained=len(gains),
  gained_supported=sum(r['supported_safe_success'] for r in gains),gained_unsupported=sum(r['unsupported_execution'] for r in gains),
  elapsed_seconds=time.perf_counter()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
 write_json(out/'verification.json',result);print(json.dumps(result),flush=True)
 if errors:raise SystemExit(1)
if __name__=='__main__':main()
