"""Publication artifacts from saved CSVs; uses already installed matplotlib."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from experiments.research_20261018.analyze import load_csv
from experiments.error_bounds_20261018.runner import primary


def main(base):
    out=base/'figures';out.mkdir(exist_ok=False)
    rs={r['variant']:r for r in load_csv(base/'analysis/primary_comparison.csv')}
    names=['current','numeric_set','bound_verified','rule_bound_verified'];labels=['Current','Numeric set','Bound evidence','Rule + bounds'];colors=['#697886','#d19a38','#147d78','#7254a3']
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':140})
    fig,axes=plt.subplots(2,3,figsize=(13,7),constrained_layout=True)
    for ax,(metric,title) in zip(axes.flat,[('harmful_action','Dangerous action'),('unjustified_refusal','Unjustified refusal: legacy audit'),('bound_unjustified_refusal','Unjustified refusal: bound audit'),
            ('safe_task_success','Safe task success'),('bound_supported_safe_success','Safe success with bound support'),('realized_harm','Realized harm')]):
        values=[100*rs[v][metric] for v in names];ax.bar(range(4),values,color=colors)
        ax.set_xticks(range(4),labels,rotation=18,ha='right');ax.set_ylabel('Family-macro rate (%)');ax.set_title(title)
        ax.set_ylim(0,max(values)*1.22+1)
        for x,y in enumerate(values):ax.text(x,y+.3,f'{y:.2f}',ha='center',fontsize=9)
    fig.suptitle('Prospective synthetic probes | 24 families, 4,608 decisions per method\nSame public information; distinct evaluation contracts')
    for ext in ('png','svg','pdf'):fig.savefig(out/f'primary_comparison.{ext}')
    plt.close(fig)
    rows=[r for r in load_csv(base/'prospective_v1/by_family.csv') if primary(r) and r['variant']=='numeric_set']
    fig,ax=plt.subplots(figsize=(12,5),constrained_layout=True);xs=list(range(len(rows)))
    ax.bar([x-.18 for x in xs],[100*r['observed_enclosure'] for r in rows],width=.35,label='Observed range: all states',color='#d19a38')
    ax.bar([x+.18 for x in xs],[100*r['certified_enclosure'] if r['certified_enclosure'] is not None else 0 for r in rows],width=.35,label='Verified bounds: certified states only',color='#147d78')
    for x,r in enumerate(rows):
        if r['certified_enclosure'] is None:ax.text(x+.18,2,'NA',ha='center',rotation=90,fontsize=8)
    ax.set_xticks(xs,[r['family'].split('_')[1] for r in rows]);ax.set_xlabel('Scenario family (NA: no fully certified state)');ax.set_ylim(0,110);ax.set_ylabel('Enclosure coverage (%)')
    ax.set_title('Can the public ranges enclose the private simulation truth?\nCoverage is scored after the decision; never model input');ax.legend(loc='upper left',fontsize=9)
    for ext in ('png','svg','pdf'):fig.savefig(out/f'enclosure_coverage.{ext}')
    plt.close(fig)
    ci={r['metric']:r for r in load_csv(base/'prospective_v1/paired_ci.csv') if primary(r) and r['left']=='bound_verified' and r['right']=='numeric_set'}
    ms=['harmful_action','safe_task_success','unjustified_refusal','bound_unjustified_refusal','bound_unsupported_execution','realized_harm']
    titles=['Dangerous action','Safe task success','Legacy unjustified refusal','Bound unjustified refusal','Unsupported by bound audit','Realized harm']
    fig,(ax,bx)=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    for i,m in enumerate(ms):
        r=ci[m];ax.plot([100*r['ci_low'],100*r['ci_high']],[i,i],color='#147d78',linewidth=2);ax.scatter([100*r['delta']],[i],color='#147d78')
    ax.axvline(0,color='#aaa',linewidth=1);ax.set_yticks(range(len(ms)),titles);ax.invert_yaxis();ax.set_xlabel('Bound evidence minus numeric set (percentage points)');ax.set_title('Paired family bootstrap, exploratory 95% intervals')
    bx.bar(range(4),[1000*rs[v]['policy_seconds'] for v in names],color=colors)
    bx.scatter(range(4),[1000*rs[v]['policy_seconds_p95'] for v in names],marker='_',color='black',s=90,label='95th percentile')
    bx.set_xticks(range(4),labels,rotation=20,ha='right');bx.set_ylabel('Measured milliseconds / decision');bx.set_title('Policy latency (same query / record budgets)');bx.legend()
    for ext in ('png','svg','pdf'):fig.savefig(out/f'paired_effect_and_cost.{ext}')
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);main(p.parse_args().base)
