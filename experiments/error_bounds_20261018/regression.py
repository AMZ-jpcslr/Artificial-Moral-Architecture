"""Post-run regression of three already-explored errors, not new evidence."""
import gzip,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from moral_agent.affect.appraisal import AffectState
from moral_agent.models import to_dict
from experiments.research_20261018.analyze import load_csv
from experiments.research_20261018.runner import csv_write,write_json
from experiments.causal_refusal_20261018.diagnostics import public_input,key
from experiments.error_bounds_20261018.public import BoundPacket
from experiments.error_bounds_20261018.controller import BoundController


def main(base):
    out=base/'old_counterexample_regression';out.mkdir(exist_ok=False);start=time.perf_counter()
    old=ROOT/'results/causal_refusal_20261018_100656';cfg=json.loads((base/'registration_v1/freeze.json').read_text())['config']
    wanted={key(r) for r in load_csv(old/'analysis/paired_transitions.csv') if r['variant']=='numeric_set' and r['harmful_action_change']>0}
    rows=[];errors=[];seen=set()
    with gzip.open(old/'verification/all_primary_traces.jsonl.gz','rt',encoding='utf-8') as source,gzip.open(out/'traces.jsonl.gz','wt',encoding='utf-8') as dest:
        for line in source:
            t=json.loads(line)
            if t['variant']!='numeric_set' or key(t) not in wanted:continue
            seen.add(key(t));frame,p,e=public_input(t)
            # No calibration information existed. Do not manufacture certificates
            # from the old evaluation-only truths or inferred true errors.
            packet=BoundPacket(p.scope,p.now,p.claims,p.disputed)
            for variant in ('numeric_set','bound_verified'):
                ctrl=BoundController(variant,cfg['parameters']);ctrl.bind(packet);ctrl.state=AffectState(**t['state_before_decision']);ctrl.errors=t['state_trace']['ema']
                d=ctrl.decide(frame,e);saved=to_dict(d);action=d.selected_action.id if d.selected_action else None
                if variant=='numeric_set' and saved!=t['decision_trace']:errors.append(key(t))
                row=dict(variant=variant,family=t['family'],seed=t['seed'],replicate=t['replicate'],step=t['step'],
                    old_action=t['selected_action'],new_action=action,new_decision=d.kind.value,certificates_supplied=0)
                rows.append(row);dest.write(json.dumps(row|dict(public_packet=to_dict(packet),decision_trace=saved,dossier=ctrl.last_dossier),ensure_ascii=False)+'\n')
    csv_write(out/'decisions.csv',rows)
    info=dict(decisions=len(rows),explored_cases=len(seen),numeric_replay_mismatches=errors,
        bound_alternative_selected=sum(r['variant']=='bound_verified' and r['new_action']=='alternative' for r in rows),
        seconds=time.perf_counter()-start,scope='post-run regression only; excluded from prospective estimates and acceptance')
    write_json(out/'verification.json',info);print(json.dumps(info))
    if errors or seen!=wanted:raise ValueError('regression coverage mismatch')


if __name__=='__main__':main(Path(sys.argv[1]))
