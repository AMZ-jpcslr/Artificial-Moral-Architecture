"""Independently rescore all traces; audit common information and original hashes."""
import argparse,collections,datetime,gzip,hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.runner import csv_write,write_json
from experiments.action_evidence_20261018.verify import rescore
from experiments.causal_refusal_20261018.runner import source_hashes
from experiments.causal_refusal_20261018.diagnostics import primary,key


def failure_paths(t):
    """Trace-based descriptive paths; may overlap, never used as truth labels."""
    paths=[];a=t['selected_action'];d=t['dossier_trace']
    if t['harmful_action'] and t['scored']:
        if a=='primary' and not t['public_final']['initial']['exposed'] and t['evaluation_only']['primary']['exposed']:
            paths.append(('stakeholder_omission','primary_exposure_underobserved'))
        if t['unsupported_execution']:paths.append(('constraint_selection','executed_without_public_support'))
        else:paths.append(('prediction_error','publicly_supported_but_physically_dangerous'))
    if t['unjustified_refusal']:
        for assessment in t['decision_trace']['assessments']:
            aid=assessment['action']['id']
            if aid not in t['public_audit']['permitted']:continue
            e=assessment['evaluation'];policy=next(x['policy'] for x in t['policies_trace'] if x['action']==aid)
            if e['uncertainty']>=policy['uncertainty_limit']:
                reason='numeric_disagreement' if aid=='alternative' and d and any(x['status']=='conflicting' and x['axis'] in ('harm','reversibility') for x in d['details']) else 'unknown_or_inherited_uncertainty'
            elif e['hard_violations']:reason='hard_violation'
            elif e['harm']>=policy['review_harm']:reason='harm_review'
            else:reason='other_review_or_selection'
            paths.append(('evaluation_error',reason))
        if not t['decision_trace']['assessments']:paths.append(('constraint_selection','rule_refusal'))
    if t['unsupported_execution'] and not t['harmful_action']:
        paths.append(('constraint_selection','unsupported_execution_without_physical_danger'))
    return sorted(set(paths))


def main():
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);base=p.parse_args().base
    out=base/'verification';out.mkdir(exist_ok=False);start=time.perf_counter();errors=[];rows=0;fixed={};info_errors=[];counts=collections.Counter();failure_rows=[]
    with gzip.open(base/'prospective_v1/decisions.jsonl.gz','rt',encoding='utf-8') as stream,gzip.open(out/'current_primary_traces.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as current,gzip.open(out/'all_primary_traces.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as primary_traces:
        for line in stream:
            t=json.loads(line);rows+=1;expected,actions=rescore(t)
            for k,v in expected.items():
                if t[k]!=v:errors.append(dict(row=rows,field=k,saved=t[k],computed=v))
            if actions!=t['public_audit']['actions']:errors.append(dict(row=rows,field='public_audit'))
            if int(t['budget']>=1)+int(t['response'] is not None)!=t['query_count']:errors.append(dict(row=rows,field='query_budget'))
            if t['virtual_decisions']>14 or(t['equal_compute'] and t['virtual_decisions']!=14):errors.append(dict(row=rows,field='compute_budget'))
            if t['allocation']=='fixed':
                ident=(t['accuracy'],t['budget'],t['representation'],t['equal_compute'],*key(t))
                # Compare raw information, not each method's differently validated projection.
                data=[t[x] for x in ('public_initial','packet','received_claims','response','query_channel','query_cost')]
                digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
                if ident in fixed and fixed[ident]!=digest:info_errors.append((t['variant'],*ident))
                else:fixed[ident]=digest
            if primary(t):
                primary_traces.write(line)
                if t['variant']=='current':current.write(line)
                for category,reason in failure_paths(t):
                    counts[(t['variant'],category,reason)]+=1
                    failure_rows.append(dict(variant=t['variant'],family=t['family'],seed=t['seed'],replicate=t['replicate'],step=t['step'],category=category,reason=reason))
            if rows%20000==0:print('verified',rows,flush=True)
    csv_write(out/'failure_paths.csv',failure_rows)
    csv_write(out/'failure_counts.csv',[dict(variant=v,category=c,reason=r,count=n) for (v,c,r),n in sorted(counts.items())])
    original=json.loads((base/'preservation/original_files.json').read_text());changed=[]
    for r in original:
        path=ROOT/r['path']
        if not path.is_file():changed.append(r['path']);continue
        with path.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
        if h!=r['sha256']:changed.append(r['path'])
    freeze=json.loads((base/'registration_v1/freeze.json').read_text());same=source_hashes()==freeze['sources']
    info=dict(rows_checked=rows,score_or_public_audit_mismatches=errors,fixed_information_groups=len(fixed),
        fixed_information_mismatches=info_errors,original_files_checked=len(original),original_files_changed=changed,
        source_freeze_equal=same,elapsed_seconds=time.perf_counter()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write_json(out/'verification.json',info);print(json.dumps(info),flush=True)
    if errors or info_errors or changed or not same:raise RuntimeError('verification failed')


if __name__=='__main__':main()
