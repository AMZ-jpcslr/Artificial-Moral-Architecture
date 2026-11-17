"""Frozen offline Concern/info experiments; all evaluator-only work lives here."""
import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import io
import itertools
import json
from pathlib import Path
import statistics
import time

from ..models import to_dict
from .controller import Controller
from .world import CHANNELS, build_episode, query, apply_response, selected_feedback, evaluate
from .statistics import summarize, comparisons

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = ROOT/'docs/concern_information_protocol.md'
CONFIG = ROOT/'experiments/concern_information_config.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def csv_write(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, tuple)) else v for k, v in row.items()})


def identifier(decision):
    return decision.selected_action.id if decision.selected_action else None


def score(world, decision):
    return evaluate(world, identifier(decision), decision.kind)


def validate(config):
    if config['episode_length'] != 8 or config['feedback_delay'] != 1:
        raise ValueError('registered version requires eight decisions and one-step outcome delay')
    if not config['budgets'] or any(type(b) is not int or b not in (0, 1, 2, 4) for b in config['budgets']):
        raise ValueError('budgets must be 0/1/2/4')
    for key in ('seeds', 'budgets'):
        if len(config[key]) != len(set(config[key])) or not config[key]:
            raise ValueError('duplicate or empty ' + key)
    if set(config['accuracies']) - {'low', 'medium', 'high'} or not config['accuracies']:
        raise ValueError('unknown/empty accuracy')
    if any(not 0 <= a <= 1 for a in config['accuracies'].values()) or config['cost'] < 0:
        raise ValueError('invalid accuracy or cost')
    ids = [f['id'] for f in config['families']]
    if len(ids) != len(set(ids)):
        raise ValueError('family split leak / duplicate')


def run_episode(worlds, experiment, mode, variant, budget, accuracy, params, *, cost=1., offset=0, trace=True):
    controller = Controller(variant, params)
    schedule = {i*8//budget for i in range(budget)} if budget and mode != 'none' else set()
    pending = None
    rows = []
    ordinal = 0
    started = time.perf_counter()
    for step, world in enumerate(worlds):
        feedback = controller.observe(*pending) if pending is not None else None
        state_trace = controller.prepare(world.frame)
        # Both local counterfactuals hold pre-query history/state and current input fixed.
        no_query = controller.decide(world.frame, world.frame.initial)
        no_query_score = score(world, no_query)
        evidence = world.frame.initial
        response, channel, reason = None, None, None
        if step in schedule:
            if experiment == 'I':
                channel = CHANNELS[(ordinal+offset) % len(CHANNELS)]
                reason = {'reason': 'externally fixed timing and source; no Concern source change'}
            elif experiment == 'assignment':
                channel = mode
                reason = {'reason': 'experimental assignment of one source type'}
            else:
                channel, reason = controller.choose(world.frame, ordinal, offset)
            if channel not in world.frame.candidates:
                raise RuntimeError('scheduled source unavailable; count unmet, never exclude case')
            response_mode = mode if experiment == 'I' else 'relevant'
            response = query(world, channel, response_mode, accuracy, cost, seed_key=0)
            evidence = apply_response(evidence, response)
            ordinal += 1
        # Reuse exactly unchanged predictions/decisions; rereading is not a new forecast.
        changed_evidence = evidence != world.frame.initial
        final = controller.decide(world.frame, evidence) if changed_evidence else no_query
        final_without_concern = controller.decide(world.frame, evidence, final_override=False) if controller.switch.final else final
        result = score(world, final)
        direct_score = score(world, final_without_concern)
        result['safe_task_success'] = bool(result['safe_task_success'])
        row = {'step': step, 'decision': final.kind.value, 'selected_action': identifier(final), **result,
               'checks': int(response is not None), 'query_cost': response.cost if response else 0.,
               'additional_predictions': 2*int(evidence != world.frame.initial),
               'behavior_prediction_builds': 3+2*int(changed_evidence)+int(feedback is not None),
               'audit_prediction_builds': 2*int(controller.switch.final),
               'external_model_calls': 0,
               'alternative_searches': 0,  # candidate catalog held fixed; requests are logged, not fabricated work
               'stakeholder_checks': int(channel == 'stakeholders'),
               'channel': channel, 'error_type': world.error_type,
               'query_improved': result['safe_task_success'] and not no_query_score['safe_task_success'],
               'query_worsened': not result['safe_task_success'] and no_query_score['safe_task_success'],
               'query_added_harm': result['harmful_action'] and not no_query_score['harmful_action'],
               'query_avoided_harm': not result['harmful_action'] and no_query_score['harmful_action'],
               'recovery_eligible': no_query_score['harmful_action'],
               'safe_recovery': no_query_score['harmful_action'] and result['safe_task_success'],
               'concern_changed_source': bool(reason and reason.get('concern_changed_channel')),
               'concern_changed_decision': (final.kind, identifier(final)) != (final_without_concern.kind, identifier(final_without_concern)),
               'direct_safe_delta': int(result['safe_task_success'])-int(direct_score['safe_task_success']),
               'direct_harm_delta': int(result['harmful_action'])-int(direct_score['harmful_action'])}
        if trace:
            row.update(initial_situation=to_dict(world.frame), delivered_feedback=feedback,
                concern_trace=state_trace, selection_reason=reason, obtained_information=to_dict(response),
                updated_prediction=to_dict(evidence), final=to_dict(final),
                local_no_query=to_dict(no_query), local_concern_final_off=to_dict(final_without_concern),
                evaluation_only={'no_query': no_query_score, 'direct_off': direct_score,
                                 'future_realized_harm': result['realized_harm']},
                paths={'source_exploratory': controller.switch.selection, 'final_existing_threshold': controller.switch.final,
                       'concern_query_requests_overridden_by_equal_cost_schedule': True,
                       'alternative_catalog_fixed': True})
        rows.append(row)
        selected = identifier(final)
        observed = selected_feedback(world, selected)
        pending = (world.frame, selected, observed) if selected else None
    final_feedback = controller.observe(*pending) if pending is not None else None
    elapsed = time.perf_counter()-started
    expected = budget if mode != 'none' else 0
    if sum(r['checks'] for r in rows) != expected:
        raise RuntimeError('exact query allocation not achieved')
    mean = lambda name: sum(r[name] for r in rows)/len(rows)
    rate = lambda name, eligible: sum(r[name] for r in rows)/sum(r[eligible] for r in rows) if sum(r[eligible] for r in rows) else None
    summary = {k: mean(k) for k in ('safe_task_success', 'task_success', 'harmful_action', 'ask_human', 'realized_harm')}
    summary.update(over_refusal=rate('over_refusal', 'over_refusal_eligible'),
        appropriate_escalation=mean('appropriate_human_review'),
        escalation_recall=rate('appropriate_human_review', 'expected_human_review'),
        safe_recovery=rate('safe_recovery', 'recovery_eligible'),
        checks=sum(r['checks'] for r in rows), query_cost=sum(r['query_cost'] for r in rows),
        additional_predictions=sum(r['additional_predictions'] for r in rows), alternative_searches=0,
        stakeholder_checks=sum(r['stakeholder_checks'] for r in rows), runtime_seconds=elapsed,
        actual_budget_achieved=sum(r['checks'] for r in rows)==expected,
        unused_budget=budget-sum(r['checks'] for r in rows),
        concern_changed_source=sum(r['concern_changed_source'] for r in rows),
        concern_changed_decision=sum(r['concern_changed_decision'] for r in rows),
        direct_safe_delta=mean('direct_safe_delta'), direct_harm_delta=mean('direct_harm_delta'))
    return summary, rows, final_feedback


def source_hashes():
    # Freeze imported behavior dependencies too, not just the new adapter.
    paths = sorted((ROOT/'src/moral_agent').rglob('*.py'))
    paths += [PROTOCOL, ROOT/'docs/concern_information_mechanism.md', CONFIG]
    paths += sorted((ROOT/'tests').glob('test_concern*.py'))
    paths += [ROOT/'experiments/run_concern_information.py']
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def tune(config):
    worlds = [(f, seed, build_episode(f, seed, config)) for f in config['families'] if f['split'] == 'development' for seed in config['seeds']]
    trials = []
    for cue, error, alpha in itertools.product((.5, 1.), (0., .5, 1.), (.2, .5)):
        params = dict(cue_weight=cue, error_weight=error, alpha=alpha)
        scores = []
        for _, seed, episode in worlds:
            s, _, _ = run_episode(episode, 'II', 'relevant', 'history', 4,
                config['accuracies'].get('medium', .75), params, offset=seed % 5, trace=False)
            scores.append(s['safe_task_success']-s['harmful_action']-.02*(s['over_refusal'] or 0))
        trials.append({'parameters': params, 'objective': statistics.mean(scores)})
    best = max(trials, key=lambda r: r['objective'])
    return {'parameters': best['parameters'], 'development_trials': trials,
            'development_families': [f['id'] for f in config['families'] if f['split'] == 'development']}


def freeze(config, output):
    validate(config)
    output.mkdir(parents=True, exist_ok=False)
    development = tune(config)
    locked = {'config': config, 'sources': source_hashes(), **development,
              'note': 'Frozen after development only; heldout not used for parameter selection.'}
    write_json(output/'freeze.json', locked)
    print('Frozen at', output/'freeze.json')


def conditions(config, experiments):
    for accuracy in config['accuracies']:
        for budget in config['budgets']:
            if 'I' in experiments:
                modes = ('none',) if budget == 0 else ('repeat', 'relevant', 'irrelevant')
                for mode, variant in itertools.product(modes, ('off', 'state', 'final')):
                    yield 'I', mode, accuracy, budget, variant
            if 'II' in experiments:
                for variant in ('uniform', 'current', 'history', 'state', 'select', 'final', 'both'):
                    yield 'II', 'relevant', accuracy, budget, variant
            if 'assignment' in experiments and budget in (0, 4):
                for channel in ('none',) if budget == 0 else CHANNELS:
                    yield 'assignment', channel, accuracy, budget, 'off'


def execute(config, params, output, split='development', experiments=('I', 'II', 'assignment')):
    validate(config)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/'config.json', config)
    records, effects = [], defaultdict(lambda: defaultdict(float))
    examples = {}
    with (output/'decisions.jsonl.gz').open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as gz, io.TextIOWrapper(gz, encoding='utf-8') as stream:
        for family in config['families']:
            if family['split'] != split:
                continue
            for seed in config['seeds']:
                worlds = build_episode(family, seed, config)
                for experiment, mode, accuracy, budget, variant in conditions(config, experiments):
                    identity = dict(split=split, family=family['id'], seed=seed, experiment=experiment,
                                    mode=mode, accuracy=accuracy, budget=budget, variant=variant)
                    summary, rows, final_feedback = run_episode(worlds, experiment, mode, variant, budget,
                        config['accuracies'][accuracy], params, cost=config['cost'], offset=seed % 5)
                    records.append(identity | summary)
                    for row in rows:
                        full = identity | row
                        stream.write(json.dumps(full, ensure_ascii=False, separators=(',', ':'))+'\n')
                        # All cells retained; no selecting only successful sources/families.
                        key = (experiment, mode, accuracy, budget, variant, family['id'], row['error_type'], row['channel'] or 'none')
                        for metric in ('checks', 'query_improved', 'query_worsened', 'query_added_harm', 'query_avoided_harm',
                                       'concern_changed_source', 'concern_changed_decision', 'direct_safe_delta', 'direct_harm_delta'):
                            effects[key][metric] += row[metric]
                        effects[key]['decisions'] += 1
                        if row['checks']:
                            kind = 'improved' if row['query_improved'] else 'worsened' if row['query_worsened'] else 'no_benefit'
                            examples.setdefault((experiment, accuracy, kind), full)
                    stream.write(json.dumps(identity | {'event': 'episode_end', 'final_feedback': final_feedback, 'summary': summary}, ensure_ascii=False, separators=(',', ':'))+'\n')
    summary = summarize(records)
    contrasts = comparisons(records, bootstrap=config['bootstrap'])
    detail = [dict(zip(('experiment', 'mode', 'accuracy', 'budget', 'variant', 'family', 'error_type', 'channel'), key)) | dict(value) for key, value in effects.items()]
    csv_write(output/'episodes.csv', records)
    csv_write(output/'summary.csv', summary)
    csv_write(output/'paired_ci.csv', contrasts)
    csv_write(output/'source_error_effects.csv', detail)
    write_json(output/'summary.json', {'summary': summary, 'contrasts': contrasts})
    write_json(output/'examples.json', list(examples.values()))
    metadata = {'split': split, 'episode_runs': len(records), 'decisions': len(records)*8,
                'family_clusters': len({r['family'] for r in records}), 'parameters': params,
                'actual_budget_all_achieved': all(r['actual_budget_achieved'] for r in records),
                'counterfactual_computation_not_charged_to_agent_queries': True,
                'runtime_includes_local_counterfactual_instrumentation': True}
    write_json(output/'metadata.json', metadata)
    lines = ['Exploratory Concern/info pilot: medium accuracy, 4 actual queries', 'Exp Mode        Variant    SafeTask Harm OverRef Ask Cost']
    for r in summary:
        if r['accuracy']=='medium' and r['budget']==4 and r['experiment'] != 'assignment':
            lines.append(f"{r['experiment']:3} {r['mode']:11} {r['variant']:10} {r['safe_task_success']:.3f} {r['harmful_action']:.3f} "
                         f"{r['over_refusal'] or 0:.3f} {r['ask_human']:.3f} {r['query_cost']:.1f}")
    (output/'console.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'.join(lines))
    print(metadata)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('smoke', 'freeze', 'evaluate'), required=True)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', nargs='+', type=int)
    parser.add_argument('--accuracies', nargs='+', choices=('low', 'medium', 'high'))
    parser.add_argument('--budgets', nargs='+', type=int)
    parser.add_argument('--experiments', nargs='+', choices=('I', 'II', 'assignment'), default=['I','II','assignment'])
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    if args.seeds is not None: config['seeds'] = args.seeds
    if args.budgets is not None: config['budgets'] = args.budgets
    if args.accuracies is not None: config['accuracies'] = {k: config['accuracies'][k] for k in args.accuracies}
    if args.phase == 'freeze':
        freeze(config, args.output)
    elif args.phase == 'smoke':
        execute(config, dict(cue_weight=1., error_weight=.5, alpha=.5), args.output, experiments=args.experiments)
    else:
        if args.freeze is None:
            parser.error('evaluate requires --freeze pointing to a saved freeze.json')
        locked = json.loads(args.freeze.read_text(encoding='utf-8'))
        if locked['sources'] != source_hashes():
            raise ValueError('source/protocol changed after freeze; create separate version, not silent retuning')
        # CLI can select only subsets of the predeclared seeds/budgets/accuracy levels.
        original = locked['config']
        for key in ('seeds', 'budgets', 'accuracies'):
            if not set(config[key]) <= set(original[key]):
                raise ValueError('condition outside registered freeze')
        for key in original.keys()-{'seeds', 'budgets', 'accuracies'}:
            if config[key] != original[key]: raise ValueError('configuration changed after freeze')
        if any(config['accuracies'][k] != original['accuracies'][k] for k in config['accuracies']):
            raise ValueError('sensor accuracy changed')
        execute(config, locked['parameters'], args.output, 'heldout', args.experiments)
        write_json(args.output/'freeze_used.json', locked)


if __name__ == '__main__':
    main()
