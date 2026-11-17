"""Keep representative benefits and harms; the complete transition CSV is primary."""
import argparse,gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.causal_refusal_20261018.diagnostics import key


def main():
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);base=p.parse_args().base
    choices=json.loads((base/'analysis/casebook_selection.json').read_text());wanted={(r['variant'],*key(r)) for r in choices}|{('current',*key(r)) for r in choices}
    selected={}
    with gzip.open(base/'verification/all_primary_traces.jsonl.gz','rt',encoding='utf-8') as stream:
        for line in stream:
            t=json.loads(line);k=(t['variant'],*key(t))
            if k in wanted:selected[k]=t
    if set(selected)!=wanted:raise ValueError('casebook trace missing')
    with gzip.open(base/'analysis/selected_case_traces.jsonl.gz','wt',encoding='utf-8') as out:
        for k,t in sorted(selected.items()):out.write(json.dumps(t,ensure_ascii=False)+'\n')
    lines=['# 改善・悪化の具体例','',
        '結果確認後、方式ごと・変化種類ごとのキー順先頭2件を表示した。恣意的な成功例だけの採用を避けるため、悪化を含む全対応はpaired_transitions.csvとall_adverse_transitions.csvに保存している。例示は新しい独立検証ではない。','']
    for c in choices:
        a=selected[(c['variant'],*key(c))];b=selected[('current',*key(c))]
        lines.extend([f"## {c['variant']} / {c['tag']} / {key(c)}",'',
            f"判断: {b['decision']} / {b['selected_action']} → {a['decision']} / {a['selected_action']}",
            f"危険: {b['harmful_action']} → {a['harmful_action']}。不当拒否: {b['unjustified_refusal']} → {a['unjustified_refusal']}。安全達成: {b['safe_task_success']} → {a['safe_task_success']}。",
            f"公開情報上の候補状態: {a['public_audit']['actions']}",
            f"Guilt状態: {b['state_before_decision']['anticipated_guilt']:.6f} → {a['state_before_decision']['anticipated_guilt']:.6f}",'',
            '同じ初期観測でも、以前の行動が変わると後続の状態が変わる。固定状態の直接効果はshared_state_diagnosticを参照。','',
            '証拠確認とペアリング:', '```json',json.dumps(dict(dossier=a['dossier_trace'],pairing=a['pairing_trace']),ensure_ascii=False,indent=2),'```','',
            '評価専用の物理参照（判断モデルには渡さない）:', '```json',json.dumps(a['evaluation_only'],ensure_ascii=False,indent=2),'```',''])
    (base/'analysis/CASEBOOK.md').write_text('\n'.join(lines),encoding='utf-8');print('casebook',len(choices),'examples,',len(selected),'traces')


if __name__=='__main__':main()
