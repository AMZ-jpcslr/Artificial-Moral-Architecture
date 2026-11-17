"""Post-run descriptive checks with matched coverage denominators; no decisions."""
import collections,gzip,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.analyze import load_csv
from experiments.research_20261018.runner import csv_write,write_json
from experiments.error_bounds_20261018.runner import primary,key


def main(base):
    out=base/'additional_audit';out.mkdir(exist_ok=False);start=time.perf_counter()
    rows=load_csv(base/'prospective_v1/decisions.csv');numeric=[r for r in rows if r['variant']=='numeric_set' and primary(r)]
    matched=[]
    for family in sorted({r['family'] for r in numeric}):
        rs=[r for r in numeric if r['family']==family];eligible=[r for r in rs if r['certified_coverage_eligible']]
        matched.append(dict(family=family,total=len(rs),verified=len(eligible),observed_covered=sum(r['observed_enclosure'] for r in eligible),
            bounded_covered=sum(r['certified_enclosure'] for r in eligible),
            observed_rate=sum(r['observed_enclosure'] for r in eligible)/len(eligible) if eligible else None,
            bounded_rate=sum(r['certified_enclosure'] for r in eligible)/len(eligible) if eligible else None))
    csv_write(out/'matched_enclosure_coverage.csv',matched)
    selected=[];danger_by=collections.Counter();unsafe_unique=set();unsafe_states=set()
    with gzip.open(base/'verification/primary_traces.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            t=json.loads(line)
            if t['variant']!='bound_verified' or t['selected_action']!='alternative':continue
            if t['harmful_action'] and t['scored']:
                e=t['evaluation_only'];bad_consent=[s for s,allowed in e['consents'] if not allowed]
                bad_events=[dict(event=ev,subject=s,harm=h,reversibility=r) for ev,s,h,r in e['events'] if h>=.5 or(h>=.4 and r<=.2)]
                danger_by[t['family']]+=1;unsafe_unique.add(key(t));unsafe_states.add((t['family'],t['seed'],t['step']))
                selected.append(dict(family=t['family'],seed=t['seed'],replicate=t['replicate'],step=t['step'],bad_consents=bad_consent,
                    bad_events=bad_events,public_contract=t['bound_public_audit']['actions']['alternative'],
                    certified_coverage_failure=t['certified_coverage_failure']))
    csv_write(out/'residual_unsafe_bound_alternatives.csv',selected)
    verified=sum(x['verified'] for x in matched);obs=sum(x['observed_covered'] for x in matched);bounded=sum(x['bounded_covered'] for x in matched)
    info=dict(scope='Post-run descriptive audit, not an additional acceptance criterion or independent test set',
        matched_certified_states=verified,observed_covered_on_matched_states=obs,bounded_covered_on_matched_states=bounded,
        observed_matched_pooled=obs/verified,bounded_matched_pooled=bounded/verified,
        residual_danger_by_family=dict(danger_by),residual_danger_rows=len(unsafe_unique),residual_danger_world_states=len(unsafe_states),
        seconds=time.perf_counter()-start)
    write_json(out/'verification.json',info);print(json.dumps(info))


if __name__=='__main__':main(Path(sys.argv[1]))
