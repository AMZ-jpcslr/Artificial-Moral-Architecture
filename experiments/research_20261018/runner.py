"""Reproducible bounded study. No external action, communication, or installation."""
import argparse
from collections import Counter
import copy
import csv
from dataclasses import replace
import datetime
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import time

from moral_agent.concern_information.world import apply_response, keyed
from moral_agent.models import to_dict
from .controllers import ResearchController, identifier
from . import worlds
from .metrics import GROUP, RATES, aggregate, group_summaries, paired

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def csv_write(path, rows):
    if not rows:
        path.write_text('', encoding='utf-8'); return
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys); writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (tuple,list,dict)) else v for k,v in row.items()})


def source_hashes():
    paths = sorted((ROOT/'src/moral_agent').rglob('*.py'))
    paths += [HERE/p for p in ('__init__.py', 'public.py', 'controllers.py', 'worlds.py', 'metrics.py', 'runner.py', 'config.json', 'PROTOCOL.md')]
    paths += [ROOT/'tests/test_research_followup.py', ROOT/'experiments/run_research_followup.py']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def conditions(config, smoke=False):
    all_conditions = []
    primary = config['primary']
    def add(variants, **changes):
        for variant in variants:
            all_conditions.append(primary | changes | {'variant': variant})
    add(config['variants'])
    if not smoke:
        main = ('rule', 'no_affect', 'both', 'combined')
        for prediction in ('oracle', 'noisy_oracle', 'checked'):
            add(main, prediction=prediction)
        for accuracy, budget in ((.55,4), (.95,4), (.75,0), (.75,2)):
            add((*main, 'history'), accuracy=accuracy, budget=budget)
        for representation in ('paraphrase_ja', 'paraphrase_en'):
            add(main, representation=representation)
            add(('both','combined'), representation=representation, prediction='checked')
        add(main, representation='incomplete')
    unique = {tuple(c[k] for k in GROUP):c for c in all_conditions}
    return list(unique.values())


def diagnosis(case, controller, evidence, decision, result):
    started = time.perf_counter()
    failure = result['scored'] and (result['harmful_action'] or result['over_refusal'] or result['unavailable_action'] or
        (result['safe_available'] and not result['safe_task_success'] and decision.selected_action is not None))
    if not failure:
        return {'failure': False, 'failure_class': 'none', 'failure_flags': [], 'audit_decisions': 0,
                'audit_seconds': time.perf_counter()-started}, {}
    # Local diagnostic interventions never replace the acting controller or its state.
    plain = copy.deepcopy(controller)
    plain.config = replace(plain.config, enabled=False)
    plain_decision = plain.decide(case.world.frame, evidence)
    reference = worlds.reference(case.world)
    perfect = copy.deepcopy(controller)
    perfect_decision = perfect.decide(case.world.frame, reference)
    plain_ref = copy.deepcopy(plain)
    plain_ref_decision = plain_ref.decide(case.world.frame, reference)
    plain_score, perfect_score, plain_ref_score = (
        worlds.score(case, d) for d in (plain_decision, perfect_decision, plain_ref_decision))
    flags = []
    if evidence.exposed != reference.exposed:
        flags.append('stakeholder_omission')
    if result['safe_alternative_eligible'] and (not evidence.alternative or controller.research_variant == 'combined_no_alternatives'):
        flags.append('alternative_shortage')
    if any(getattr(evidence, f) != getattr(reference, f) for f in
           ('harm','rights','consent','reversible','alternative','fallback_harm','fallback_rights','fallback_consent','fallback_reversibility')):
        flags.append('prediction_error')
    if plain_ref_score['harmful_action']:
        flags.append('evaluation_error')
    if plain_score['safe_task_success'] and not result['safe_task_success']:
        flags.append('constraint_selection_error')
    if not flags:
        flags.append('unresolved')
    # Prespecified explanatory priority; flags are nonexclusive and are not causal
    # mediation estimates. The diagnostic contrasts provide additional evidence.
    order = ('stakeholder_omission','alternative_shortage','prediction_error','evaluation_error','constraint_selection_error','unresolved')
    primary = next(k for k in order if k in flags)
    metrics = {'failure': True, 'failure_class': primary, 'failure_flags': flags,
        'oracle_local_recovery': perfect_score['safe_task_success'] and not result['safe_task_success'],
        'no_affect_local_recovery': plain_score['safe_task_success'] and not result['safe_task_success'],
        'oracle_no_affect_harm': plain_ref_score['harmful_action'],
        'audit_decisions': 3, 'audit_seconds': time.perf_counter()-started}
    trace = {'same_evidence_no_affect': to_dict(plain_decision),
             'oracle_same_state': to_dict(perfect_decision),
             'oracle_no_affect': to_dict(plain_ref_decision),
             'scores': [plain_score, perfect_score, plain_ref_score]}
    return metrics, trace


def run_episode(cases, condition, config, replicate, *, audit=True):
    controller = ResearchController(condition['variant'], config['parameters'], checked=condition['prediction']=='checked')
    budget = condition['budget']
    schedule = {i*8//budget for i in range(budget)} if budget else set()
    previous = None; ordinal = 0; rows = []; traces = []
    for raw in cases:
        case = worlds.transform(raw, condition['prediction'], condition['representation'], replicate)
        frame = case.world.frame
        counts_before = dict(controller.counts)
        tick, cpu = time.perf_counter(), time.process_time()
        observed = controller.observe(*previous) if previous else None
        state_trace = controller.prepare(frame)
        evidence = frame.initial
        response = reason = channel = None
        if case.step in schedule:
            channel, reason = controller.choose(frame, ordinal, case.seed % 5)
            # The local synthetic sensor computation is included in policy time.
            response = worlds.get_response(case, channel, condition['accuracy'], replicate)
            evidence = apply_response(evidence, response)
            ordinal += 1
        decision = controller.decide(frame, evidence)
        seconds, cpu_seconds = time.perf_counter()-tick, time.process_time()-cpu
        selected = identifier(decision)
        counts = {k: controller.counts[k]-counts_before[k] for k in controller.counts}
        policies, issues = controller.last_policies, controller.last_issues
        result = worlds.score(case, decision)  # First access to evaluator, after selection.
        if audit:
            diagnostics, diagnostic_trace = diagnosis(case, controller, evidence, decision, result)
        else:
            diagnostics, diagnostic_trace = {}, {}
        row = condition | dict(family=case.family, structure=case.structure, seed=case.seed,
            replicate=replicate, step=case.step, decision=decision.kind.value, selected_action=selected,
            error_type=case.world.error_type, query_channel=channel, query_count=int(response is not None),
            query_cost=response.cost if response else 0., external_model_calls=0, api_money_cost=0.,
            policy_seconds=seconds, policy_cpu_seconds=cpu_seconds, **counts, **result, **diagnostics)
        trace = row | {'public_input': to_dict(frame), 'delivered_feedback': observed,
            'state_trace': state_trace, 'selection_reason': reason, 'response': to_dict(response),
            'updated_evidence': to_dict(evidence), 'policies': policies, 'consistency_issues': issues,
            'decision_trace': to_dict(decision), 'diagnostic_trace': diagnostic_trace,
            'evaluation_only_reference': to_dict(worlds.reference(case.world))}
        rows.append(row); traces.append(trace)
        # Feedback is delivered only at the next step. No unselected outcomes.
        previous = (frame, selected, worlds.feedback(case, selected)) if selected else None
    if sum(r['query_count'] for r in rows) != budget:
        raise RuntimeError('query budget not achieved')
    return rows, traces


def contrasts(rows, config):
    base_keys = GROUP[:-1]
    groups = {}
    for row in rows:
        groups.setdefault(tuple(row[k] for k in base_keys), []).append(row)
    result = []
    pairs = [('combined','both'),('sensitivity','both'),('scoped','both'),
             ('combined','history'),('combined','rule'),('combined','no_affect'),('state','history')]
    pairs += [('combined', v) for v in config['variants'] if v.startswith('combined_no_')]
    for key, group in sorted(groups.items()):
        present = {r['variant'] for r in group}
        for left,right in pairs:
            if left not in present or right not in present:
                continue
            for metric in RATES:
                contrast = paired(group,left,right,metric,bootstrap=config['bootstrap'],seed=config['bootstrap_seed'])
                result.append(dict(zip(base_keys,key)) | contrast)
    return result


def execute(config, output, *, smoke=False, limit_families=None):
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write_json(output/'config.json', config)
    matrix = conditions(config, smoke=smoke)
    write_json(output/'conditions.json', matrix)
    if smoke:
        old = json.loads((ROOT/'experiments/concern_information_config.json').read_text(encoding='utf-8'))
        families = [f for f in old['families'] if f['split']=='development']
        seeds, repeats = config['development_seeds'], [0]
    else:
        families, seeds, repeats = config['families'], config['seeds'], config['replicates']
    if limit_families is not None:
        if not smoke:
            raise ValueError('prospective subset selection is prohibited')
        families = families[:limit_families]
    rows = []; executions = 0; episodes = 0
    with gzip.open(output/'decisions.jsonl.gz', 'wt', encoding='utf-8', compresslevel=1) as stream:
        for family in families:
            for seed in seeds:
                cases = worlds.development_episode(family,seed,old) if smoke else worlds.prospective_episode(family,seed)
                for replicate in repeats:
                    # Randomized order for runtime estimates, deterministic seed.
                    ordered = sorted(matrix, key=lambda c: keyed(family['id'],seed,replicate,'order',json.dumps(c,sort_keys=True)))
                    for condition in ordered:
                        batch,traces = run_episode(cases,condition,config,replicate)
                        rows.extend(batch); episodes += 1; executions += len(batch)
                        for trace in traces:
                            stream.write(json.dumps(trace,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
                progress = dict(family=family['id'], seed=seed, episodes=episodes, decisions=executions,
                                elapsed_seconds=time.perf_counter()-started)
                write_json(output/'progress.json', progress)
            print(json.dumps(progress),flush=True)
    csv_write(output/'decisions.csv', rows)
    csv_write(output/'all_comparisons.csv', group_summaries(rows))
    csv_write(output/'by_family.csv', group_summaries(rows,('family',)))
    csv_write(output/'by_severity.csv', group_summaries(rows,('severity',)))
    csv_write(output/'by_failure.csv', group_summaries(rows,('failure_class',)))
    csv_write(output/'by_seed.csv', group_summaries(rows,('seed',)))
    csv_write(output/'by_conflict.csv', group_summaries(rows,('conflict',)))
    csv_write(output/'by_ambiguity.csv', group_summaries(rows,('ambiguous',)))
    paired_rows = contrasts(rows, config)
    csv_write(output/'paired_ci.csv', paired_rows)
    metadata = dict(phase='development' if smoke else 'prospective',
        started_utc=datetime.datetime.now(datetime.timezone.utc).timestamp()-(time.perf_counter()-started),
        finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), elapsed_seconds=time.perf_counter()-started,
        episode_runs=episodes, decision_runs=executions, unique_world_episodes=len(families)*len(seeds),
        unique_world_steps=len(families)*len(seeds)*8, family_clusters=len(families),
        sensor_replicates=len(repeats), conditions=len(matrix),
        policy_time_seconds=sum(r['policy_seconds'] for r in rows),
        audit_decisions=sum(r['audit_decisions'] for r in rows),
        virtual_decisions=sum(r['virtual_decisions'] for r in rows),
        actual_queries=sum(r['query_count'] for r in rows),
        query_budget_all_achieved=True, api_calls=0, monetary_api_cost=0,
        failure_classes=dict(Counter(r['failure_class'] for r in rows)), source_hashes=source_hashes())
    write_json(output/'metadata.json', metadata)
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=('development','freeze','prospective'),required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--freeze',type=Path)
    parser.add_argument('--development',type=Path)
    args = parser.parse_args(argv)
    config = json.loads((HERE/'config.json').read_text(encoding='utf-8'))
    if args.phase == 'development':
        metadata = execute(config,args.output,smoke=True)
    elif args.phase == 'freeze':
        if args.development is None or not (args.development/'metadata.json').exists():
            parser.error('freeze requires a completed development run')
        dev = json.loads((args.development/'metadata.json').read_text(encoding='utf-8'))
        if dev['source_hashes'] != source_hashes():
            raise ValueError('source changed since development; rerun with new output and record reason')
        args.output.mkdir(parents=True,exist_ok=False)
        metadata = dict(frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),config=config,
            sources=source_hashes(),development=str(args.development),parameters_tuned=False,
            note='New graph families have not been evaluated. No post-holdout tuning is permitted.')
        write_json(args.output/'freeze.json',metadata)
    else:
        if args.freeze is None:
            parser.error('prospective requires --freeze')
        locked = json.loads(args.freeze.read_text(encoding='utf-8'))
        if locked['sources'] != source_hashes() or locked['config'] != config:
            raise ValueError('source or configuration changed after freeze')
        metadata = execute(config,args.output)
        write_json(args.output/'freeze_used.json',locked)
    print(json.dumps({k:v for k,v in metadata.items() if k not in ('sources','source_hashes','config')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
