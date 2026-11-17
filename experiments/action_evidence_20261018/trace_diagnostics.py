"""Post-run trace diagnosis. Reconstructs only already-observed refusal decisions."""
import argparse,collections,datetime,gzip,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from moral_agent.models import to_dict
from moral_agent.affect.appraisal import AffectState
from experiments.research_20261018.public import ExtendedEvidence
from experiments.research_20261018.runner import csv_write,write_json
from experiments.action_evidence_20261018.analyze import primary,key
from experiments.action_evidence_20261018.public import Claim,Scope,Packet
from experiments.action_evidence_20261018.controller import EvidenceController
from experiments.action_evidence_20261018.worlds import build_case
from experiments.action_evidence_20261018.runner import source_hashes

def main():
 p=argparse.ArgumentParser();p.add_argument('base',type=Path);base=p.parse_args().base
 out=base/'trace_diagnostics';out.mkdir(exist_ok=False);start=time.perf_counter()
 freeze=json.loads((base/'registration_v1/freeze.json').read_text());config=freeze['config']
 if source_hashes()!=freeze['sources']:raise ValueError('freeze mismatch')
 refusals=[];dangers=[];mismatches=[];replayed=0;reasons=collections.Counter();scanned=0
 with gzip.open(base/'prospective_v1/decisions.jsonl.gz','rt',encoding='utf-8') as stream:
  for line in stream:
   t=json.loads(line);scanned+=1
   if not primary(t) or t['variant']!='combined_verified':continue
   if t['selected_action']=='alternative' and t['harmful_action'] and t['scored']:
    ref=t['evaluation_only'];d=t['dossier_trace']
    false_consent=[s for s,v in ref['consents'] if not v and d['consents'].get(s) is True]
    harmful_events=[(ev,s) for ev,s,h,r in ref['events'] if h>=.5 or(h>=.4 and r<=.2)]
    dangers.append(dict(family=t['family'],profile=t['profile'],seed=t['seed'],replicate=t['replicate'],step=t['step'],
     false_consent=false_consent,hidden_harmful_events=harmful_events,public_status=d['status'],unsupported=t['unsupported_execution']))
   if not t['unjustified_refusal']:continue
   # Reuse the frozen generator only to reconstruct the public frame. Never pass
   # its private fields to a controller; verify exact equality to the saved input.
   frame=build_case(t['family'],t['profile'],t['seed'],t['step']).frame
   if to_dict(frame)!=t['public_initial']:raise ValueError('public reconstruction mismatch')
   q=t['packet'];z=q['scope'];scope=Scope(z['action'],z['revision'],tuple(z['consent_subjects']),tuple(tuple(x) for x in z['event_subjects']),z['coverage_complete'])
   packet=Packet(scope,q['now'],tuple(Claim(**x) for x in q['claims']),q['disputed'])
   ctrl=EvidenceController('combined_verified',config['parameters']);ctrl.bind(packet)
   ctrl.state=AffectState(**t['state_trace']['after']);ctrl.errors=dict(t['state_trace']['ema'])
   decision=ctrl.decide(frame,ExtendedEvidence(**t['public_final']['initial']));replayed+=1
   if to_dict(decision)!=t['decision_trace']:mismatches.append(key(t))
   policies={x['action']:x for x in ctrl.last_policies}
   for assessment in t['decision_trace']['assessments']:
    action=assessment['action']['id']
    if action not in t['public_audit']['permitted']:continue
    e=assessment['evaluation'];policy=policies[action]['policy']
    reason=('uncertainty' if e['uncertainty']>=policy['uncertainty_limit'] else 'hard_violation' if e['hard_violations'] else
      'harm_review' if e['harm']>=policy['review_harm'] else 'rights_review' if e['rights']>=policy['review_rights'] else
      'consent_review' if e['consent']>=policy['review_consent'] else 'fairness_review' if e['fairness']>=policy['review_fairness'] else 'other')
    reasons[reason]+=1
    refusals.append(dict(family=t['family'],seed=t['seed'],replicate=t['replicate'],step=t['step'],action=action,reason=reason,
     harm=e['harm'],reversibility=e['reversibility'],uncertainty=e['uncertainty'],review_harm=policy['review_harm'],
     uncertainty_limit=policy['uncertainty_limit'],local_concern=policies[action]['local_concern'],
     anticipated_guilt=t['state_trace']['after']['anticipated_guilt'],publicly_permitted=True))
 csv_write(out/'unjustified_refusal_paths.csv',refusals);csv_write(out/'dangerous_alternative_evidence.csv',dangers)
 result=dict(scanned_rows=scanned,refusal_decisions_reconstructed=replayed,replay_mismatches=mismatches,
  publicly_permitted_action_paths=len(refusals),refusal_path_reasons=dict(reasons),dangerous_alternatives=len(dangers),
  dangerous_alternatives_with_false_consent=sum(bool(r['false_consent']) for r in dangers),
  dangerous_alternatives_with_hidden_harm=sum(bool(r['hidden_harmful_events']) for r in dangers),
  dangerous_alternatives_systematic_false_profile=sum(r['profile']=='valid_false_attestation' for r in dangers),
  elapsed_seconds=time.perf_counter()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  note='Descriptive failure paths, overlapping causes; reconstructed decisions are not new experimental observations.')
 write_json(out/'metadata.json',result);print(json.dumps(result),flush=True)
 if mismatches:raise SystemExit(1)
if __name__=='__main__':main()
