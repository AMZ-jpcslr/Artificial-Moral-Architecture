"""Independent aggregate arithmetic plus descriptive residual-risk decomposition."""
import argparse,collections,datetime,gzip,json,math,statistics,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.analyze import load_csv
from experiments.research_20261018.runner import csv_write,write_json
from experiments.action_evidence_20261018.metrics import GROUP,RATES
from experiments.causal_refusal_20261018.diagnostics import primary,key


def main():
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);base=p.parse_args().base
    out=base/'arithmetic_audit';out.mkdir(exist_ok=False);start=time.perf_counter();errors=[];checks=0
    rows=load_csv(base/'prospective_v1/decisions.csv');summary=load_csv(base/'prospective_v1/all_comparisons.csv')
    groups=collections.defaultdict(list)
    for r in rows:groups[tuple(r[k] for k in GROUP)].append(r)
    def check(actual,expected,label):
        nonlocal checks
        checks+=1
        okay=actual is None and expected is None or actual is not None and expected is not None and math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-12)
        if not okay:errors.append(dict(field=label,actual=actual,expected=expected))
    for s in summary:
        batch=groups[tuple(s[k] for k in GROUP)];families=collections.defaultdict(list)
        for r in batch:families[r['family']].append(r)
        check(s['n'],len(batch),'n');check(s['scored_count'],sum(r['scored'] for r in batch),'scored_count')
        check(s['ambiguous_count'],sum(r['ambiguous'] for r in batch),'ambiguous_count')
        for metric,(numerator,denominator) in RATES.items():
            selected=[r for r in batch if denominator=='all' or r[denominator]]
            n=sum(bool(r[numerator]) for r in selected);d=len(selected);values=[]
            for family in families.values():
                eligible=[r for r in family if denominator=='all' or r[denominator]]
                if eligible:values.append(sum(bool(r[numerator]) for r in eligible)/len(eligible))
            expected={metric+'_numerator':n,metric+'_denominator':d,metric+'_pooled':n/d if d else None,
                metric:sum(values)/len(values) if values else None,metric+'_family_min':min(values) if values else None,
                metric+'_family_max':max(values) if values else None,metric+'_family_sd':statistics.stdev(values) if len(values)>1 else None}
            for k,v in expected.items():check(s[k],v,k)
    by={v:{key(r):r for r in rows if primary(r) and r['variant']==v} for v in ('current','guilt_event','numeric_set')}
    direct={key(r):r for r in load_csv(base/'shared_state_diagnostic/decisions.csv') if r['variant']=='numeric_set'}
    wanted={};counts=[]
    for v in ('guilt_event','numeric_set'):
        batch=by[v];danger=[k for k,r in batch.items() if r['harmful_action'] and not by['current'][k]['harmful_action']]
        new_harm=[k for k,r in batch.items() if r['realized_harm'] and not by['current'][k]['realized_harm']]
        for k in danger:wanted[(v,*k)]='new_danger'
        for k in new_harm:wanted.setdefault((v,*k),'new_realized_harm')
        counts.append(dict(variant=v,new_danger_rows=len(danger),new_danger_world_states=len({(k[0],k[1],k[3]) for k in danger}),
            new_danger_families=len({k[0] for k in danger}),new_harm_rows=len(new_harm),
            new_harm_world_states=len({(k[0],k[1],k[3]) for k in new_harm}),new_harm_families=len({k[0] for k in new_harm})))
    state_effect=[k for k,r in by['numeric_set'].items() if (r['selected_action'],r['decision'])!=(direct[k]['new_action'],direct[k]['new_decision'])]
    for k in state_effect:wanted[('numeric_set',*k)]='state_feedback_difference'
    severity={};details=[];expected_delta=collections.Counter();selected_count=collections.Counter()
    with gzip.open(base/'verification/all_primary_traces.jsonl.gz','rt',encoding='utf-8') as stream,gzip.open(out/'residual_cases.jsonl.gz','wt',encoding='utf-8') as target:
        for line in stream:
            t=json.loads(line);ref=t['evaluation_only'];e=ref['primary'];events=ref['events']
            sev='high' if max(e['harm'],e['rights'],e['consent'],.9 if any(not x for _,x in ref['consents']) else 0.,*[h for _,_,h,_ in events])>=.8 else 'moderate' if any(h>=.4 for _,_,h,_ in events) else 'low'
            world=(t['family'],t['seed'],t['step']);severity[world]=sev
            v=t['variant'];k=key(t)
            if v in ('guilt_event','numeric_set'):
                old=by['current'][k]['selected_action'];new=t['selected_action']
                def risk(action):
                    if action=='primary':return e['harm']
                    if action=='alternative' and ref['available']:return 1.-math.prod(1-h for _,_,h,_ in events)
                    return 0.
                expected_delta[v]+=risk(new)-risk(old);selected_count[v]+=int(new!=old)
            ident=(v,*k)
            if ident in wanted:
                target.write(json.dumps(t,ensure_ascii=False)+'\n')
                details.append(dict(variant=v,family=k[0],seed=k[1],replicate=k[2],step=k[3],tag=wanted[ident],
                    old_action=by['current'][k]['selected_action'],new_action=t['selected_action'],
                    variant_guilt=t['state_before_decision']['anticipated_guilt'],
                    public_actions=t['public_audit']['actions'],observed_events=t['dossier_trace']['events'],
                    true_events=events,numeric_proofs=t['dossier_trace'].get('numeric_proofs'),
                    fixed_state_action=direct[k]['new_action'] if v=='numeric_set' else None))
    for r in rows:
        if r['severity']!=severity[(r['family'],r['seed'],r['step'])]:errors.append(dict(field='severity',key=key(r)))
    csv_write(out/'new_danger_independence.csv',counts);csv_write(out/'residual_cases.csv',details)
    csv_write(out/'expected_harm_proxy.csv',[dict(variant=v,decision_changes=selected_count[v],expected_harm_probability_sum_change=expected_delta[v],
        mean_probability_change=expected_delta[v]/len(by[v]),assumption='Latent per-event Bernoulli probabilities independent; diagnostic only, not adoption metric') for v in ('guilt_event','numeric_set')])
    info=dict(aggregate_scalar_checks=checks,summary_conditions=len(summary),severity_rows_checked=len(rows),world_states=len(severity),
        mismatches=errors,numeric_state_feedback_differences=len(state_effect),elapsed_seconds=time.perf_counter()-start,
        finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write_json(out/'verification.json',info);print(json.dumps(info),flush=True)
    if errors:raise RuntimeError('aggregate or severity audit failed')


if __name__=='__main__':main()
