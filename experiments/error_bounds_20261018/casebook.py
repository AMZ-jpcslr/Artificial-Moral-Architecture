"""Retain failures, latent expected harm and concrete evidence examples."""
import argparse,collections,gzip,json,math,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.runner import csv_write,write_json
from experiments.research_20261018.analyze import load_csv
from experiments.error_bounds_20261018.runner import key


def main(base):
    out=base/'casebook';out.mkdir(exist_ok=False);start=time.perf_counter()
    selected=json.loads((base/'analysis/casebook_selection.json').read_text())
    wanted={(r[v],r['family'],r['seed'],r['replicate'],r['step']) for r in selected for v in ('left','right')}
    keep={};latent=[];failure=[];reasons=collections.Counter();alltraces={};rows=[]
    with gzip.open(base/'verification/primary_traces.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            t=json.loads(line);v=t['variant'];ident=key(t)
            alltraces[v,*ident]={k:t[k] for k in ('variant','family','seed','replicate','step','selected_action','decision','harmful_action')}
            if (v,*ident) in wanted:keep[v,*ident]=t
            a=t['selected_action'];e=t['evaluation_only']
            risk=e['primary']['harm'] if a=='primary' else 1-math.prod(1-h for _,_,h,_ in e['events']) if a=='alternative' and e['available'] else 0.
            latent.append(dict(variant=v,family=t['family'],seed=t['seed'],replicate=t['replicate'],step=t['step'],expected_harm=risk,realized_harm=t['realized_harm']))
            if t['certified_coverage_failure'] or (a=='alternative' and t['harmful_action']):
                failure.append({k:t[k] for k in ('variant','family','seed','replicate','step','profile','enclosure_state','selected_action','harmful_action','scored','certified_coverage_failure')}|dict(expected_harm=risk))
                if len([x for x in selected if x.get('tag')=='certified_false_enclosure' and x['left']==v])<1 and t['certified_coverage_failure']:
                    selected.append(dict(left=v,right=v,family=t['family'],seed=t['seed'],replicate=t['replicate'],step=t['step'],tag='certified_false_enclosure'));keep[v,*ident]=t
            if t['unjustified_refusal']:
                if t['bound_unjustified_refusal']:reason='unjustified_under_both_public_contracts'
                else:reason='old_contract_permits_bound_contract_requires_stop'
                reasons[v,reason]+=1
            d=t['dossier_trace']
            if d and 'bound_domains' in d:
                for issue in {i['reason'] for x in d['bound_domains'] for i in x['issues']}:reasons[v,'bound:'+issue]+=1
    csv_write(out/'latent_expected_harm.csv',latent);csv_write(out/'all_enclosure_failures_and_unsafe_alternatives.csv',failure)
    csv_write(out/'refusal_and_evidence_reasons.csv',[dict(variant=v,reason=r,n=n) for (v,r),n in sorted(reasons.items())])
    ld={(r['variant'],r['family'],r['seed'],r['replicate'],r['step']):r for r in latent};comparisons=[]
    for left,right in [('bound_verified','numeric_set'),('bound_verified','current'),('rule_bound_verified','bound_verified')]:
        changes=[]
        for ident in sorted({key(t) for t in alltraces.values()}):changes.append(ld[left,*ident]['expected_harm']-ld[right,*ident]['expected_harm'])
        comparisons.append(dict(left=left,right=right,n=len(changes),expected_harm_change_sum=sum(changes),expected_harm_change_mean=statistics_mean(changes)))
    csv_write(out/'latent_harm_comparison.csv',comparisons)
    shared=load_csv(base/'shared_state_diagnostic/decisions.csv');differences=[]
    for r in shared:
        if r['variant']!='bound_verified':continue
        t=alltraces['bound_verified',*key(r)]
        if (r['new_action'],r['new_decision'])!=(t['selected_action'],t['decision']):
            differences.append(dict(family=r['family'],seed=r['seed'],replicate=r['replicate'],step=r['step'],shared_state_action=r['new_action'],sequential_action=t['selected_action'],
                shared_state_harm=r['harmful_action'],sequential_harm=t['harmful_action']))
    csv_write(out/'shared_vs_sequential_differences.csv',differences)
    lines=['# 具体例と残余失敗','',
        '全結果を保存した後、各変化区分のキー順先頭2件を記載。成功例だけを採らない。評価専用真値は判断後の分析だけに用いる。','',
        '潜在期待被害は、既存シミュレータの各事象を独立Bernoulliとする仮定の下で計算した保存後の診断。採否や判断には使わない。','']
    with gzip.open(out/'selected_traces.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as dest:
        for t in keep.values():dest.write(json.dumps(t,ensure_ascii=False)+'\n')
    for item in selected:
        ident=(item['family'],item['seed'],item['replicate'],item['step']);a=keep[item['left'],*ident];b=keep[item['right'],*ident]
        lines.extend([f"## {item['tag']} / {ident}",'',f"{item['right']}: {b['decision']} {b['selected_action']} → {item['left']}: {a['decision']} {a['selected_action']}",
            f"危険 {b['harmful_action']} → {a['harmful_action']}、安全成功 {b['safe_task_success']} → {a['safe_task_success']}",
            f"旧公開監査: {a['public_audit']['actions']}、上界監査: {a['bound_public_audit']['actions']}",'',
            '上界検証トレース:', '```json',json.dumps(a['dossier_trace'],ensure_ascii=False,indent=2),'```','',
            '評価専用の被覆検算（モデル入力ではない）:', '```json',json.dumps(a['evaluation_only']['coverage'],ensure_ascii=False,indent=2),'```',''])
    (out/'CASEBOOK.md').write_text('\n'.join(lines),encoding='utf-8')
    info=dict(primary_rows=len(alltraces),selected_examples=len(selected),selected_traces=len(keep),coverage_or_alternative_failure_rows=len(failure),
        shared_vs_sequential_differences=len(differences),seconds=time.perf_counter()-start)
    write_json(out/'metadata.json',info);print(json.dumps(info))


def statistics_mean(values):return sum(values)/len(values)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);main(p.parse_args().base)
