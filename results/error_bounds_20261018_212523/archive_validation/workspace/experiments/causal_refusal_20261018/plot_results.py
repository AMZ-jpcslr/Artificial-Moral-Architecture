"""Local plotting with an already installed matplotlib; no downloads."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from experiments.research_20261018.analyze import load_csv
from experiments.causal_refusal_20261018.diagnostics import primary

LABEL={'current':'Current','guilt_event':'H1: event pairing','numeric_set':'H2: numeric domains',
       'history_verified':'History + evidence','rule':'Simple rule','rule_verified':'Rule + evidence'}
COLORS=['#596579','#197c91','#da8a21','#6b66ad','#b45155','#658c61']


def main():
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);base=p.parse_args().base
    out=base/'figures';out.mkdir(exist_ok=False)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    summary=load_csv(base/'prospective_v1/all_comparisons.csv');main={r['variant']:r for r in summary if primary(r)}
    variants=list(LABEL)
    def save(fig,name):
        fig.savefig(out/(name+'.png'),dpi=180,bbox_inches='tight');fig.savefig(out/(name+'.svg'),bbox_inches='tight');plt.close(fig)
    fig,axes=plt.subplots(2,3,figsize=(14,8),constrained_layout=True)
    for ax,metric,title in zip(axes.flat,('harmful_action','unjustified_refusal','safe_task_success','supported_safe_success','safe_alternative_success','unsupported_execution'),
            ('Dangerous action','Unjustified refusal / public opportunity','Safe task success','Supported safe success','Safe alternative / safe opportunity','Execution without public support')):
        vals=[main[v][metric]*100 for v in variants];ax.barh([LABEL[v] for v in variants],vals,color=COLORS);ax.invert_yaxis()
        ax.set_title(title);ax.set_xlabel('Family-macro rate (%)');ax.set_xlim(0,max(vals)*1.18+1)
        for i,val in enumerate(vals):ax.text(val+.2,i,f'{val:.2f}',va='center',fontsize=9)
    fig.suptitle('Prospective synthetic probes: 20 families, 8 seeds, 3 sensor replicates\nPrimary fixed-information condition; denominators differ by metric',fontsize=13)
    save(fig,'01_primary_rates')
    ci=[r for r in load_csv(base/'prospective_v1/paired_ci.csv') if primary(r) and r['right']=='current' and r['left'] in ('guilt_event','numeric_set')]
    metrics=['harmful_action','unjustified_refusal','supported_safe_success','safe_task_success','unsupported_execution','realized_harm']
    fig,axes=plt.subplots(1,2,figsize=(13,5),constrained_layout=True)
    for ax,v,color in zip(axes,('guilt_event','numeric_set'),COLORS[1:3]):
        vals={r['metric']:r for r in ci if r['left']==v}
        for i,m in enumerate(metrics):
            r=vals[m];ax.plot([r['ci_low']*100,r['ci_high']*100],[i,i],color=color,lw=3);ax.plot(r['delta']*100,i,'o',color=color)
        ax.axvline(0,color='#555',lw=1);ax.set_yticks(range(len(metrics)),[m.replace('_',' ') for m in metrics]);ax.invert_yaxis()
        ax.set_xlabel('Candidate minus current (percentage points)');ax.set_title(LABEL[v])
    fig.suptitle('Paired family bootstrap intervals (2,000 draws)\nExploratory mechanism-family uncertainty; no significance claim')
    save(fig,'02_paired_intervals')
    families=[r for r in load_csv(base/'prospective_v1/by_family.csv') if primary(r)]
    ids=sorted({r['family'] for r in families});lookup={(r['variant'],r['family']):r for r in families}
    fig,axes=plt.subplots(1,2,figsize=(12,7),constrained_layout=True)
    for ax,metric in zip(axes,('harmful_action','supported_safe_success')):
        data=[[100*(lookup[(v,f)][metric]-lookup[('current',f)][metric]) for v in ('guilt_event','numeric_set')] for f in ids]
        lim=max(1,max(abs(x) for row in data for x in row));im=ax.imshow(data,cmap='RdBu',vmin=-lim,vmax=lim,aspect='auto')
        ax.set_yticks(range(len(ids)),ids);ax.set_xticks([0,1],['H1 pairing','H2 numeric']);ax.set_title(metric.replace('_',' '))
        for i,row in enumerate(data):
            for j,val in enumerate(row):ax.text(j,i,f'{val:+.1f}',ha='center',va='center',fontsize=8,color='white' if abs(val)>lim*.65 else 'black')
        fig.colorbar(im,ax=ax,label='Change (percentage points)')
    fig.suptitle('Effects by family; related synthetic mechanisms are not population samples')
    save(fig,'03_family_effects')
    fig,axes=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    for v,color in zip(variants,COLORS):
        group=sorted([r for r in summary if r['variant']==v and r['budget']==2 and r['representation']=='canonical' and r['allocation']=='fixed' and not r['equal_compute']],key=lambda r:r['accuracy'])
        axes[0].plot([r['accuracy'] for r in group],[r['harmful_action']*100 for r in group],marker='o',label=LABEL[v],color=color)
        axes[1].plot([r['accuracy'] for r in group],[r['supported_safe_success']*100 for r in group],marker='o',label=LABEL[v],color=color)
    for ax,title in zip(axes,('Dangerous action (%)','Supported safe success (%)')):ax.set_xlabel('Random sensor accuracy parameter');ax.set_ylabel(title);ax.grid(alpha=.2)
    axes[1].legend(fontsize=8);fig.suptitle('Accuracy stress: systematic false testimony persists even at 1.0')
    save(fig,'04_accuracy_stress')
    fig,axes=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    for ax,allocation in zip(axes,('fixed','native')):
        for v,color in zip(variants,COLORS):
            r=next(r for r in summary if r['variant']==v and r['accuracy']==.85 and r['budget']==2 and r['representation']=='canonical' and r['allocation']==allocation and not r['equal_compute'])
            ax.scatter(r['policy_seconds']*1000,r['supported_safe_success']*100,color=color,s=60,label=LABEL[v])
            ax.annotate(LABEL[v],(r['policy_seconds']*1000,r['supported_safe_success']*100),fontsize=7,xytext=(4,4),textcoords='offset points')
        ax.set_xlabel('Measured mean policy time (ms)');ax.set_ylabel('Supported safe success (%)');ax.set_title('Fixed query channel' if allocation=='fixed' else 'Adaptive query channel')
        ax.grid(alpha=.2)
    fig.suptitle('Benefit and runtime burden; local timings are descriptive, not equal CPU work')
    save(fig,'05_runtime_tradeoff')
    diagnostic=load_csv(base/'shared_state_diagnostic/summary.csv');trans=load_csv(base/'analysis/transition_counts.csv')
    fig,axes=plt.subplots(1,2,figsize=(11,4),constrained_layout=True)
    for ax,v in zip(axes,('guilt_event','numeric_set')):
        d=next(r for r in diagnostic if r['variant']==v);t=next(r for r in trans if r['variant']==v)
        labels=['Recovered refusals','New dangers'];direct=[d['refusals_recovered'],d['newly_dangerous']]
        total=[t['unjustified_refusal_removed'],t['harmful_action_added']]
        ax.bar([-.18,.82],direct,width=.36,label='Same saved current state',color='#197c91');ax.bar([.18,1.18],total,width=.36,label='Own sequential state',color='#da8a21')
        ax.set_xticks([0,1],labels);ax.set_ylabel('Paired changes (rows, not independent N)');ax.set_title(LABEL[v]);ax.legend(fontsize=8)
    fig.suptitle('Direct intervention vs action-feedback propagation')
    save(fig,'06_direct_and_sequential')
    print('Saved 6 PNG and 6 SVG figures',flush=True)


if __name__=='__main__':main()
