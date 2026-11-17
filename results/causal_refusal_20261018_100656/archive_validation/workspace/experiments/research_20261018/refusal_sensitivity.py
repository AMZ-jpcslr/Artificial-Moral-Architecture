"""Post-hoc descriptive check of the operational over-refusal denominator."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018 import worlds
from experiments.research_20261018.analyze import load_csv,primary_row
from experiments.research_20261018.metrics import aggregate
from experiments.research_20261018.runner import csv_write


def main():
    base=Path(sys.argv[1]);output=base/'analysis/refusal_information_sensitivity.csv'
    if output.exists():raise FileExistsError(output)
    config=json.loads((ROOT/'experiments/research_20261018/config.json').read_text())
    groups={}
    for family in config['families']:
        for seed in config['seeds']:
            for case in worlds.prospective_episode(family,seed):
                groups[(case.family,seed,case.step)]=dict(case.world.physical)['pending_check']
    rows=[r for r in load_csv(base/'prospective_v1/decisions.csv') if primary_row(r)]
    results=[]
    for variant in ('rule','history','both','combined'):
        for pending in (False,True):
            selected=[r for r in rows if r['variant']==variant and groups[(r['family'],r['seed'],r['step'])]==pending]
            results.append(dict(variant=variant,procedural_pending=pending,
                interpretation='post-hoc descriptive stratum; original labels and criteria unchanged',**aggregate(selected)))
    csv_write(output,results)
    print(json.dumps([{k:r[k] for k in ('variant','procedural_pending','over_refusal','over_refusal_denominator','safe_task_success','harmful_action')} for r in results]))


if __name__=='__main__':main()
