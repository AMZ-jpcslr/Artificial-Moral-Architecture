"""Unchanged physical/legacy rates plus separately named enclosure-contract rates."""
from collections import defaultdict
import math,random,statistics
from experiments.action_evidence_20261018.metrics import GROUP,RATES as OLD_RATES,COSTS as OLD_COSTS

RATES=OLD_RATES|{
 'bound_supported_safe_success':('bound_supported_safe_success','scored'),
 'bound_unjustified_refusal':('bound_unjustified_refusal','bound_unjustified_refusal_eligible'),
 'bound_unsupported_execution':('bound_unsupported_execution','all'),
 'bound_necessary_stop_recall':('bound_necessary_stop','bound_necessary_stop_eligible'),
 'bound_correct_stop_kind':('bound_stop_kind_correct','bound_necessary_stop_eligible'),
 'observed_enclosure':('observed_enclosure','all'),
 'certified_enclosure':('certified_enclosure','certified_coverage_eligible'),
 'certified_coverage_failure':('certified_coverage_failure','certified_coverage_eligible'),
 'certification_rate':('certified_coverage_eligible','all'),
 'alternative_harmful_execution':('alternative_harmful_execution','scored')}
COSTS=OLD_COSTS+('bound_checks','calibration_point_checks','returned_certificates','returned_measurements','returned_calibration_points','returned_records','public_bytes')


def ratio(rows,metric):
    n,d=RATES[metric];eligible=[r for r in rows if d=='all' or r[d]]
    num=sum(bool(r[n]) for r in eligible);den=len(eligible)
    return num,den,num/den if den else None


def aggregate(rows):
    fam=defaultdict(list)
    for r in rows:fam[r['family']].append(r)
    out=dict(n=len(rows),families=len(fam),scored_count=sum(r['scored'] for r in rows),ambiguous_count=sum(r['ambiguous'] for r in rows))
    for metric in RATES:
        n,d,p=ratio(rows,metric);vs=[ratio(v,metric)[2] for v in fam.values()];vs=[x for x in vs if x is not None]
        out.update({metric:statistics.mean(vs) if vs else None,metric+'_numerator':n,metric+'_denominator':d,
            metric+'_pooled':p,metric+'_families':len(vs),metric+'_family_min':min(vs) if vs else None,
            metric+'_family_max':max(vs) if vs else None,metric+'_family_sd':statistics.stdev(vs) if len(vs)>1 else None})
    out.update({k:statistics.mean(r.get(k,0.) for r in rows) for k in COSTS})
    out['policy_seconds_p95']=sorted(r['policy_seconds'] for r in rows)[math.ceil(.95*len(rows))-1]
    return out


def summaries(rows,extra=()):
    groups=defaultdict(list);keys=GROUP+tuple(extra)
    for r in rows:groups[tuple(r[k] for k in keys)].append(r)
    return [dict(zip(keys,k))|aggregate(v) for k,v in sorted(groups.items())]


def paired(rows,left,right,metric,bootstrap=2000,seed=10037):
    groups={v:defaultdict(list) for v in (left,right)}
    for r in rows:
        if r['variant'] in groups:groups[r['variant']][r['family']].append(r)
    diffs={}
    for family in sorted(groups[left].keys()&groups[right].keys()):
        a,b=groups[left][family],groups[right][family];key=lambda r:(r['seed'],r['replicate'],r['step'])
        if {key(r) for r in a}!={key(r) for r in b}:raise ValueError('unpaired')
        av,bv=ratio(a,metric)[2],ratio(b,metric)[2]
        if av is not None and bv is not None:diffs[family]=av-bv
    vs=list(diffs.values());out=dict(left=left,right=right,metric=metric,families=len(vs),family_deltas=diffs)
    if not vs:return out|dict(delta=None,ci_low=None,ci_high=None,min_family_delta=None,max_family_delta=None)
    rng=random.Random(seed);draws=sorted(statistics.mean(rng.choices(vs,k=len(vs))) for _ in range(bootstrap))
    return out|dict(delta=statistics.mean(vs),ci_low=draws[int(.025*bootstrap)],ci_high=draws[int(.975*bootstrap)],min_family_delta=min(vs),max_family_delta=max(vs))
