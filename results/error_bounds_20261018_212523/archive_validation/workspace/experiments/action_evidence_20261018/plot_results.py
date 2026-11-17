"""Standalone PNG/SVG figures using an already installed Matplotlib runtime."""
import argparse,collections,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.analyze import load_csv
from experiments.action_evidence_20261018.analyze import primary
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

FONT='C:/Windows/Fonts/YuGothR.ttc'
prop=FontProperties(fname=FONT);plt.rcParams.update({'font.family':prop.get_name(),'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'path'})
NAMES={'both':'元モデル','combined':'前回の改善','rule':'単純ルール','combined_verified':'改善＋証拠確認',
       'rule_verified':'ルール＋証拠確認','history_verified':'履歴＋証拠確認','combined_no_consent':'同意確認を除去','combined_no_side_effects':'副作用確認を除去'}
COLORS=['#64748b','#f97316','#a1a1aa','#0d9488','#7c3aed']


def main():
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);a=p.parse_args();base=a.base
    out=base/'figures';out.mkdir(exist_ok=False)
    rows=load_csv(base/'prospective_v1/all_comparisons.csv');main={r['variant']:r for r in rows if primary(r)}
    variants=['both','combined','rule','combined_verified','rule_verified']
    def save(fig,name,foot='同じ作者による合成16系統。公開情報の妥当性は固定した証拠契約内の評価で、人間の独立注釈ではない。'):
        fig.text(.02,.01,foot,fontsize=8,color='#64748b');fig.tight_layout(rect=(0,.045,1,.94))
        for ext in ('png','svg'):fig.savefig(out/f'{name}.{ext}',dpi=160,bbox_inches='tight')
        plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(13,8));fig.suptitle('同じ確認予算で、代替候補の証拠を検証する')
    for ax,metric,title in zip(axes.flat,['safe_task_success','harmful_action','unjustified_refusal','unsupported_execution'],
        ['安全なタスク成功率（高いほど良い）','危険行動率（低いほど良い）','公開情報上の不当拒否率（低いほど良い）','根拠のない実行率（低いほど良い）']):
        values=[100*main[v][metric] for v in variants];ax.bar(range(5),values,color=COLORS)
        ax.set_xticks(range(5),[NAMES[v].replace('＋','\n＋') for v in variants]);ax.set_title(title);ax.set_ylabel('%');ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
        for i,v in enumerate(values):ax.text(i,v+.7,f'{v:.1f}',ha='center',fontsize=9)
        ax.set_ylim(0,max(values)*1.2+3)
    save(fig,'01_primary_comparison')
    fam=load_csv(base/'prospective_v1/by_family.csv');lookup={(r['variant'],r['family']):r for r in fam if primary(r)}
    ids=sorted({r['family'] for r in fam});fig,axes=plt.subplots(1,2,figsize=(14,9));fig.suptitle('全体平均に加えて、各系統の悪化を確認する')
    for ax,metric,title in zip(axes,['harmful_action','unjustified_refusal'],['危険行動の差','公開情報上の不当拒否の差']):
        vals=[100*(lookup[('combined_verified',f)][metric]-lookup[('combined',f)][metric]) for f in ids]
        ax.barh(range(len(ids)),vals,color=['#dc2626' if x>0 else '#0d9488' for x in vals]);ax.axvline(0,color='#475569',lw=1)
        ax.set_yticks(range(len(ids)),ids);ax.invert_yaxis();ax.set_title(title);ax.set_xlabel('証拠確認あり − 前回改善（ポイント、左が改善）');ax.grid(axis='x',alpha=.15)
        for i,v in enumerate(vals):ax.text(v+(.4 if v>=0 else -.4),i,f'{v:+.1f}',va='center',ha='left' if v>=0 else 'right',fontsize=8)
        lim=max(abs(x) for x in vals)+7;ax.set_xlim(-lim,lim)
    save(fig,'02_family_differences')
    raw=[r for r in load_csv(base/'prospective_v1/decisions.csv') if primary(r)]
    categories=['根拠のある実行','根拠のない実行','必要な停止','不当な停止'];colors=['#0d9488','#ef4444','#94a3b8','#f97316']
    fig,ax=plt.subplots(figsize=(12,5));fig.suptitle('真の世界に安全な行動があるかと、公開情報で実行できるかを分ける')
    for i,v in enumerate(variants):
        batch=[r for r in raw if r['variant']==v];counts=[0,0,0,0]
        for r in batch:
            idx=1 if r['unsupported_execution'] else 0 if r['selected_action'] else 3 if r['unjustified_refusal'] else 2
            counts[idx]+=1
        left=0
        for k,n in enumerate(counts):
            value=n/len(batch)*100;ax.barh(i,value,left=left,color=colors[k],label=categories[k] if i==0 else None)
            if value>3:ax.text(left+value/2,i,f'{value:.1f}',ha='center',va='center',fontsize=9,color='white' if k in (0,1) else '#0f172a')
            left+=value
    ax.set_yticks(range(5),[NAMES[v] for v in variants]);ax.set_xlabel('全判断に占める割合 %（この図はプール割合）');ax.set_xlim(0,100);ax.invert_yaxis();ax.legend(ncol=4,loc='upper center',bbox_to_anchor=(.5,-.15),frameon=False)
    save(fig,'03_refusal_public_information','必要な停止には証拠不足・矛盾・明確な禁止を含む。全判断が分母であり、主表の条件付き不当拒否率とは分母が異なる。')
    fig,axes=plt.subplots(1,2,figsize=(12,5));fig.suptitle('誤った回答や少ない確認予算でも効果が残るか')
    for ax,xkey,vals in [(axes[0],'accuracy',[.65,.85,1.]),(axes[1],'budget',[0,1,2])]:
        for v,color in zip(variants,COLORS):
            selected=[next(r for r in rows if r['variant']==v and r[xkey]==x and r['accuracy']==(x if xkey=='accuracy' else .85)
                and r['budget']==(x if xkey=='budget' else 2) and r['representation']=='canonical' and r['allocation']=='native' and not r['equal_compute']) for x in vals]
            ax.plot(vals,[100*r['harmful_action'] for r in selected],marker='o',color=color,label=NAMES[v])
        ax.set_xlabel('回答精度' if xkey=='accuracy' else '問い合わせ数 / 判断');ax.set_ylabel('危険行動率 %');ax.set_xticks(vals);ax.grid(alpha=.15)
    axes[1].legend(fontsize=8);save(fig,'04_accuracy_budget')
    fig,axes=plt.subplots(1,3,figsize=(15,5));fig.suptitle('同じ問い合わせ数でも、計算負担は異なる')
    for ax,metric,mult,title in zip(axes,['policy_seconds','virtual_decisions','claim_inspections'],[1000,1,1],['実測時間 ms / 判断','仮想判断回数 / 判断','証拠レコード検査数 / 判断']):
        vals=[main[v][metric]*mult for v in variants];ax.bar(range(5),vals,color=COLORS);ax.set_title(title)
        ax.set_xticks(range(5),[NAMES[v].replace('＋','\n＋') for v in variants],rotation=15,ha='right');ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
        for i,v in enumerate(vals):ax.text(i,v+max(vals)*.02,f'{v:.2f}',ha='center',fontsize=8)
        ax.set_ylim(0,max(vals)*1.2+.01)
    save(fig,'05_computation_cost','ローカルCPUの参考値。外部API費用0。仮想判断数を14に揃えた別条件も保存したが、CPU命令数や処理時間の同等性は意味しない。')
    ab=['combined_verified','combined_no_consent','combined_no_side_effects','history_verified','rule_verified']
    fig,axes=plt.subplots(1,2,figsize=(13,5));fig.suptitle('確認する軸と、確認後の判断方式を切り分ける')
    for ax,metric,title in zip(axes,['harmful_action','safe_task_success'],['危険行動率 %','安全なタスク成功率 %']):
        vals=[100*main[v][metric] for v in ab];ax.bar(range(5),vals,color=['#0d9488','#f97316','#ef4444','#64748b','#7c3aed'])
        ax.set_xticks(range(5),[NAMES[v].replace('＋','\n＋') for v in ab],rotation=12,ha='right');ax.set_title(title);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
        for i,v in enumerate(vals):ax.text(i,v+.5,f'{v:.1f}',ha='center',fontsize=9)
        ax.set_ylim(0,max(vals)*1.2+2)
    save(fig,'06_ablation_and_simple_controls')
    (out/'metadata.json').write_text(json.dumps(dict(python=sys.version,executable=sys.executable,matplotlib=matplotlib.__version__,font=FONT,figures=6),indent=2),encoding='utf-8')


if __name__=='__main__':main()
