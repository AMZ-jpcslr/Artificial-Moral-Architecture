"""Standalone publication-style plots using an already-installed Matplotlib.

No install, network, chart inference, or model execution. All numbers come from
saved CSVs. PNG and SVG are exported together for inspection and reuse.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


def load(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def primary(r):
    return r['prediction']=='current' and r['accuracy']=='0.75' and r['budget']=='4' and r['representation']=='canonical'


def save(fig,out,name,caption):
    fig.text(.01,.012,caption,fontsize=9,color='#4b5563',va='bottom')
    fig.savefig(out/(name+'.png'),dpi=180,bbox_inches='tight',facecolor='white')
    fig.savefig(out/(name+'.svg'),bbox_inches='tight',facecolor='white')
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path)
    parser.add_argument('--output',default='figures')
    parser.add_argument('--diagnostics',type=Path)
    args=parser.parse_args()
    base=args.base;out=base/args.output;out.mkdir(exist_ok=False)
    fontpath=Path('C:/Windows/Fonts/YuGothR.ttc')
    font_manager.fontManager.addfont(str(fontpath))
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=str(fontpath)).get_name(),
        'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False,
        'axes.labelsize':11,'axes.titlesize':13,'font.size':10,'svg.fonttype':'none'})
    comparisons=load(base/'prospective_v1/all_comparisons.csv')
    data={r['variant']:r for r in comparisons if primary(r)}
    order=['rule','no_affect','history','both','sensitivity','scoped','combined']
    labels=['単純\nルール','Affect\nなし','単純\n履歴','元モデル\n両経路ON','H1\n確認先','H2\n候補単位','H1＋H2']
    colors=['#a1a1aa','#7c8da5','#64748b','#2563eb','#0d9488','#7c3aed','#ea580c']
    metrics=[('safe_task_success','安全なタスク達成率（高いほど良い）'),
             ('harmful_action','危険選択率（低いほど良い）'),
             ('over_refusal','過剰拒否率（低いほど良い）')]
    fig,axes=plt.subplots(1,3,figsize=(16,5.6))
    for ax,(metric,title) in zip(axes,metrics):
        values=[100*float(data[v][metric]) for v in order]
        bars=ax.bar(np.arange(len(order)),values,color=colors,width=.72)
        ax.set_xticks(np.arange(len(order)),labels,fontsize=9);ax.set_ylabel('%');ax.set_title(title)
        ax.set_ylim(0,max(values)*1.20+2);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
        ax.bar_label(bars,labels=[f'{v:.1f}' for v in values],padding=3,fontsize=9)
    fig.suptitle('新規12系統：拒否の削減と安全な達成・危険選択を同時に測る',fontsize=17,y=1.01)
    fig.tight_layout(rect=(0,.09,1,.98))
    save(fig,out,'01_primary_comparison','現行予測・精度0.75・4確認/8判断。系統内のseed/反復をまとめた12系統平均。曖昧ケースは規範指標から分離。分母は指標ごとに異なる。')

    families=load(base/'prospective_v1/by_family.csv')
    a={r['family']:r for r in families if primary(r) and r['variant']=='combined'}
    b={r['family']:r for r in families if primary(r) and r['variant']=='both'}
    ids=sorted(a)
    family_labels=['01 危険＋権限','02 撤回＋遮断','03 復旧・代替の共通故障','04 二段階の曝露',
                   '05 防護＋同意範囲','06 復旧＋資源不足','07 権限の競合','08 複数同意＋資源',
                   '09 代替の同意侵害','10 代替の不可逆被害','11 遅い撤回＋損失','12 複数当事者の故障']
    fig,axes=plt.subplots(1,2,figsize=(13,7.2),sharey=True)
    for ax,metric,title in zip(axes,['safe_task_success','harmful_action'],['安全な達成の差（右が改善）','危険選択の差（左が改善）']):
        values=[100*(float(a[f][metric])-float(b[f][metric])) for f in ids]
        good=lambda x:x>=0 if metric=='safe_task_success' else x<=0
        ax.barh(range(len(ids)),values,color=['#0d9488' if good(v) else '#dc2626' for v in values])
        ax.axvline(0,color='#374151',lw=1);ax.set_title(title);ax.set_xlabel('H1＋H2 − 元モデル（ポイント）')
        ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
        pad=max(abs(v) for v in values)*.04+.1
        for i,v in enumerate(values):ax.text(v+(pad if v>=0 else -pad),i,f'{v:+.1f}',ha='left' if v>=0 else 'right',va='center',fontsize=9)
        lo,hi=ax.get_xlim();ax.set_xlim(lo-5,hi+5)
    axes[0].set_yticks(range(len(ids)),family_labels);axes[0].invert_yaxis()
    fig.suptitle('全体平均では隠れる系統ごとの副作用',fontsize=17)
    fig.tight_layout(rect=(0,.07,1,.95))
    save(fig,out,'02_family_differences','同じ系統・seed・反復・stepの対応比較。12系統は同じ作者・原始因果部品を共有する合成環境で、外部の独立した道徳判断データではない。')

    predicted={(r['prediction'],r['variant']):r for r in comparisons if r['accuracy']=='0.75' and r['budget']=='4' and r['representation']=='canonical'}
    if args.diagnostics:
        predicted.update({(r['prediction'],r['variant']):r for r in load(args.diagnostics/'all_comparisons.csv')})
    conditions=['current','checked','noisy_oracle','oracle'];pnames=['現行予測','現行＋\n整合性確認','誤差注入Oracle\n診断専用','Oracle\n診断専用']
    fig,axes=plt.subplots(1,3,figsize=(14,5.8))
    for ax,(metric,title) in zip(axes,metrics):
        x=np.arange(4)
        for offset,variant,color,label in [(-.18,'both','#2563eb','元モデル'),(.18,'combined','#ea580c','H1＋H2')]:
            values=[100*float(predicted[(p,variant)][metric]) for p in conditions]
            bars=ax.bar(x+offset,values,.34,color=color,label=label)
            for bar,index in zip(bars,range(4)):
                if index>=2:bar.set_hatch('//')
            ax.bar_label(bars,labels=[f'{v:.1f}' for v in values],fontsize=8,padding=2)
        ax.set_xticks(x,pnames,fontsize=9);ax.set_ylabel('%');ax.set_title(title);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
        ax.margins(y=.2)
    axes[0].legend(frameon=False)
    fig.suptitle('予測の改善で回復できる失敗と、残る判断の問題',fontsize=17,y=1.01)
    fig.tight_layout(rect=(0,.12,1,.98))
    save(fig,out,'03_prediction_diagnostics','Oracleは原因診断専用。v1.1では誤センサーによる上書きを止め、診断予測を判断まで保持。事後の測定修正として別登録し、主比較・正解ラベルは変更していない。' if args.diagnostics else 'Oracleは正解参照を使う原因診断であり、実運用方式の成績ではない。誤差注入Oracleも別枠。新しいデータでは代替候補の副作用を含めて採点。')

    variants=['combined_no_concern','combined_no_empathy','combined_no_guilt','combined_no_persistence','combined_no_alternatives']
    names=['Concernを外す','Empathyを外す','Guiltを外す','Affect持続を外す','代替候補を外す']
    cis=load(base/'prospective_v1/paired_ci.csv')
    fig,axes=plt.subplots(1,3,figsize=(14,6.4),sharey=True)
    for ax,(metric,title) in zip(axes,metrics):
        values=[100*(float(data[v][metric])-float(data['combined'][metric])) for v in variants]
        intervals=[]
        for v,value in zip(variants,values):
            row=next(r for r in cis if primary(r) and r['left']=='combined' and r['right']==v and r['metric']==metric)
            lo,hi=-100*float(row['ci_high']),-100*float(row['ci_low'])
            intervals.append((max(0,value-lo),max(0,hi-value)))
        ax.barh(range(5),values,color='#64748b',alpha=.7)
        ax.errorbar(values,range(5),xerr=np.array(intervals).T,fmt='o',color='#111827',capsize=3,markersize=3)
        ax.axvline(0,color='#374151',lw=1);ax.set_title(title);ax.set_xlabel('機構を外した方式 − H1＋H2（pt）')
        ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    axes[0].set_yticks(range(5),names);axes[0].invert_yaxis()
    fig.suptitle('一要因ずつ外した寄与と不確実性',fontsize=17)
    fig.tight_layout(rect=(0,.09,1,.95))
    save(fig,out,'04_component_ablation','横線は12系統を復元抽出した対応bootstrap 95%区間（2,000回）。多重比較未補正。seed・反復・判断数を独立標本としていない。')

    fig,axes=plt.subplots(1,2,figsize=(12,5.8))
    for ax,metric,title,scale in [(axes[0],'predictions','予測構築回数 / 判断',1),(axes[1],'policy_seconds','実測処理時間 / 判断（ms）',1000)]:
        values=[scale*float(data[v][metric]) for v in order]
        bars=ax.bar(range(7),values,color=colors);ax.set_xticks(range(7),labels,fontsize=9)
        ax.bar_label(bars,labels=[f'{v:.2f}' for v in values],padding=3,fontsize=9)
        ax.set_title(title);ax.margins(y=.2);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.suptitle('同じ4確認でも、判断感度の計算負担は増える',fontsize=17)
    fig.tight_layout(rect=(0,.12,1,.95))
    save(fig,out,'05_computation_cost','判断感度の仮想判断を推論回数へ含める。監査用Oracle再計算は方策時間から分離。API呼出・課金は0。実測時間はこのWindows環境の値であり性能保証ではない。')

    acceptance=json.loads((base/'analysis/acceptance.json').read_text(encoding='utf-8'))
    dev={r['variant']:r for r in load(base/'development_v1/all_comparisons.csv')}
    selected=next(r for r in acceptance if r['candidate']=='combined')
    fig,axes=plt.subplots(1,3,figsize=(12,5.4))
    for ax,(metric,title) in zip(axes,metrics):
        values=[100*(float(dev['combined'][metric])-float(dev['both'][metric])),100*selected['differences'][metric]['delta']]
        bars=ax.bar([0,1],values,color=['#64748b','#ea580c'],width=.55)
        d=selected['differences'][metric];ax.errorbar([1],[values[1]],yerr=[[max(0,values[1]-100*d['ci_low'])],[max(0,100*d['ci_high']-values[1])]],fmt='none',color='#111827',capsize=5)
        ax.bar_label(bars,labels=[f'{v:+.2f}' for v in values],padding=4)
        ax.axhline(0,color='#374151',lw=1);ax.set_xticks([0,1],['既知4系統\n探索用','新規12系統\n固定後の評価']);ax.set_title(title);ax.set_ylabel('H1＋H2 − 元モデル（pt）');ax.margins(y=.25)
    fig.suptitle('探索で得た改善が、新規構造でも維持されるか',fontsize=17)
    fig.tight_layout(rect=(0,.11,1,.95))
    save(fig,out,'06_development_vs_prospective','探索と評価は異なる系統集合。評価の区間は系統単位bootstrap。旧留保ケースを新規未見データとして再利用していない。')
    (out/'plot_metadata.json').write_text(json.dumps(dict(python=sys.version,executable=sys.executable,
        matplotlib=matplotlib.__version__,font=str(fontpath),source='saved CSV and acceptance JSON only',
        diagnostic_data=str(args.diagnostics) if args.diagnostics else None,
        files=[p.name for p in out.iterdir()]),ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved 6 figures as PNG and SVG:',out)


if __name__=='__main__':main()
