"""Independent arithmetic/public-information verification of saved raw traces."""
import argparse,collections,datetime,gzip,hashlib,itertools,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.analyze import load_csv
from experiments.research_20261018.runner import csv_write,write_json
from experiments.action_evidence_20261018.runner import source_hashes
from experiments.action_evidence_20261018.analyze import primary,key


def variate(*parts):
    return int.from_bytes(hashlib.sha256('|'.join(str(p) for p in parts).encode()).digest()[:8],'big')/(2**64)


def public_reference(frame,packet):
    e=frame['initial'];scope=packet['scope'];current=packet['now']
    if packet['disputed'] or e['uncertainty']>=.5:p='undetermined'
    elif e['rights']>=.8 or e['consent']>=.8 or (e['exposed'] and e['harm']>=.5) or (not e['reversible'] and e['harm']>=.4):p='forbidden'
    elif max(e['rights'],e['consent'])>=.4:p='undetermined'
    else:p='permitted'
    trust={'consent':['owner','registry'],'available':['resource'],'harm':['lab','inspector'],'reversibility':['lab','inspector']}
    valid=[]
    for c in packet['claims']:
        if c['action']!=scope['action'] or c['revision']!=scope['revision']:continue
        if c['source'] not in trust[c['axis']] or c['confidence']<.8:continue
        if c['issued']>current or c['expires']<current:continue
        valid.append(c)
    def domain(axis,subject,event):
        vals={x['value'] for x in valid if x['axis']==axis and x['subject']==subject and x['event']==event}
        return vals or ({False,True} if axis in ('consent','available') else {0.,1.})
    local=[]
    for s in scope['consent_subjects']:local.append(list(domain('consent',s,'permission')))
    local.append(list(domain('available','resource','availability')))
    for event,subject in scope['event_subjects']:
        allowed=[]
        for h,r in itertools.product(domain('harm',subject,event),domain('reversibility',subject,event)):
            allowed.append(h<.5 and (h<.4 or r>.2))
        local.append(allowed)
    if not scope['coverage_complete']:local.append([True,False])
    possible=all(True in x for x in local);certain=all(False not in x for x in local)
    a='permitted' if certain else 'undetermined' if possible else 'forbidden'
    if packet['disputed']:a='undetermined'
    actions={'primary':p,'alternative':a};permitted=[k for k,v in actions.items() if v=='permitted']
    stop=None if permitted else 'ASK_HUMAN' if 'undetermined' in actions.values() else 'BLOCK'
    return actions,permitted,stop


def rescore(t):
    ref=t['evaluation_only'];e=ref['primary'];a=t['selected_action'];available=ref['available']
    bad_primary=e['rights']>=.8 or e['consent']>=.8 or(e['exposed'] and e['harm']>=.5) or(not e['reversible'] and e['harm']>=.4)
    bad_alt=any(not v for _,v in ref['consents']) or any(h>=.5 or(h>=.4 and r<=.2) for _,_,h,r in ref['events'])
    danger=(a=='primary' and bad_primary) or(a=='alternative' and available and bad_alt)
    raw=a=='primary' or(a=='alternative' and available);scored=not ref['ambiguous']
    actions,permitted,stop=public_reference(t['public_final'],t['packet'])
    known=bool(permitted);supported=a in permitted;opportunity=not bad_primary or(available and not bad_alt)
    actual=(a=='primary' and variate(ref['key'],'future-primary')<e['harm']) or(
        a=='alternative' and available and any(variate(ref['key'],'future-fallback',ev,s)<h for ev,s,h,_ in ref['events']))
    alt_eligible=available and not bad_alt and scored
    expected=dict(scored=scored,ambiguous=not scored,task_success=bool(raw),safe_task_success=bool(raw and not danger and scored),
        supported_safe_success=bool(raw and not danger and supported and scored),harmful_action=bool(danger),realized_harm=bool(actual),
        unjustified_refusal_eligible=known,unjustified_refusal=a is None and known,
        unsupported_execution=bool(a and not supported),necessary_stop_eligible=not known,necessary_stop=a is None and not known,
        stop_kind_correct=a is None and t['decision']==stop,public_label='action_supported' if known else stop,
        objective_stop_eligible=bool(opportunity and scored),objective_opportunity_stop=bool(opportunity and scored and a is None),
        safe_alternative_eligible=bool(alt_eligible),safe_alternative_success=bool(a=='alternative' and alt_eligible),
        unavailable_action=bool(a=='alternative' and not available),ask_human=t['decision']=='ASK_HUMAN')
    return expected,actions


def main():
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path);args=parser.parse_args();base=args.base
    out=base/'verification';out.mkdir(exist_ok=False);start=time.perf_counter();errors=[];rows=0
    fixed={};fixed_mismatch=[];selected={};rejection_counts=collections.Counter();opportunity=[]
    choices=json.loads((base/'analysis/casebook_selection.json').read_text())
    wanted={(c['variant'],c['family'],c['seed'],c['replicate'],c['step']) for c in choices}
    wanted|={('combined',c['family'],c['seed'],c['replicate'],c['step']) for c in choices}
    with gzip.open(base/'prospective_v1/decisions.jsonl.gz','rt',encoding='utf-8') as stream:
        for line in stream:
            t=json.loads(line);rows+=1;expected,actions=rescore(t)
            for k,v in expected.items():
                if t[k]!=v:errors.append(dict(row=rows,field=k,saved=t[k],computed=v))
            if actions!=t['public_audit']['actions']:errors.append(dict(row=rows,field='public_audit.actions'))
            actual_queries=int(bool(t['received_claims']))+int(t['response'] is not None)
            # A dossier can return an empty bundle, so the configured call itself
            # is counted even when no records were returned.
            actual_queries=int(t['budget']>=1)+int(t['response'] is not None)
            if actual_queries!=t['query_count']:errors.append(dict(row=rows,field='queries'))
            if t['virtual_decisions']>14 or(t['equal_compute'] and t['virtual_decisions']!=14):errors.append(dict(row=rows,field='compute_budget'))
            if t['allocation']=='fixed':
                k=key(t);value=(t['public_audit']['actions'],t['packet'],t['query_channel'])
                if k in fixed and fixed[k]!=value:fixed_mismatch.append(k)
                else:fixed[k]=value
            if primary(t):
                ident=(t['variant'],*key(t))
                if ident in wanted:selected[ident]=t
                if t['dossier_trace']:
                    for reason in t['dossier_trace']['unknown']:rejection_counts[(t['variant'],'unknown',reason)]+=1
                    for reason in t['dossier_trace']['prohibited']:rejection_counts[(t['variant'],'prohibited',reason)]+=1
                    for reason in set(x['reason'] for x in t['dossier_trace']['rejected']):rejection_counts[(t['variant'],'metadata',reason)]+=1
    lines=['# 改善・悪化の具体例','',
        '保存後の報告処理で各方式・変化種類のキー順先頭2件を抽出。事前登録した成功例選択ではない。全対応はanalysis/paired_transitions.csv。','']
    with gzip.open(out/'selected_case_traces.jsonl.gz','wt',encoding='utf-8') as f:
        for t in selected.values():f.write(json.dumps(t,ensure_ascii=False)+'\n')
    for c in choices:
        k=(c['family'],c['seed'],c['replicate'],c['step']);a=selected[(c['variant'],*k)];b=selected[('combined',*k)]
        lines.extend([f"## {c['variant']} / {c['tag']} / {k}",'',
            f"前回改善: {b['decision']} {b['selected_action']} → 証拠確認: {a['decision']} {a['selected_action']}",
            f"危険: {b['harmful_action']} → {a['harmful_action']}、安全達成: {b['safe_task_success']} → {a['safe_task_success']}",
            f"公開情報上の実行可能候補: {b['public_audit']['permitted']} → {a['public_audit']['permitted']}",'',
            '証拠確認の理由:', '```json',json.dumps(a['dossier_trace'],ensure_ascii=False,indent=2),'```','',
            '評価専用の物理参照（判断器への入力ではない）:', '```json',json.dumps(a['evaluation_only'],ensure_ascii=False,indent=2),'```',''])
    (out/'CASEBOOK.md').write_text('\n'.join(lines),encoding='utf-8')
    csv_write(out/'evidence_failure_reasons.csv',[dict(variant=v,category=c,reason=r,count=n) for (v,c,r),n in sorted(rejection_counts.items())])
    original=json.loads((base/'preservation/original_files.json').read_text());changed=[]
    for record in original:
        p=ROOT/record['path']
        if not p.is_file():changed.append(record['path']);continue
        with p.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
        if h!=record['sha256']:changed.append(record['path'])
    frozen=json.loads((base/'registration_v1/freeze.json').read_text());same=source_hashes()==frozen['sources']
    info=dict(rows_checked=rows,score_or_public_audit_mismatches=errors,fixed_allocation_paired_worlds=len(fixed),
        fixed_allocation_information_mismatches=fixed_mismatch,original_files_checked=len(original),original_files_changed=changed,
        source_freeze_equal=same,elapsed_seconds=time.perf_counter()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write_json(out/'verification.json',info)
    if errors or fixed_mismatch or changed or not same:raise RuntimeError('verification failed')
    print(json.dumps(info,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
