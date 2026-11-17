"""Predeclared, deterministic sequential pilot with grouped paired uncertainty."""
import argparse
import csv
from collections import defaultdict
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import platform
import random
import statistics
import time

from ..models import to_dict
from .controller import Controller, METHODS, decide
from .environment import build_episode, feedback, QueryBudget
from .causal import causal_probes

ROOT = Path(__file__).resolve().parents[3]
METRICS = ('safe_task_success', 'task_success', 'harmful_action', 'over_refusal',
           'ask_human', 'checks', 'unused_budget', 'runtime_seconds')


def validate(config):
    if config['steps'] != 8 or config['per_step_cap'] != 1 or config['feedback_delay'] != 1:
        raise ValueError('this registered pilot supports 8 steps, cap 1 and one-step feedback only')
    if any(type(b) is not int or not 0 <= b <= 8 for b in config['budgets']):
        raise ValueError('invalid budgets')
    if len(config['budgets']) != len(set(config['budgets'])) or not config['budgets']:
        raise ValueError('budgets must be unique and nonempty')
    if not config['seeds'] or len(config['seeds']) != len(set(config['seeds'])):
        raise ValueError('seeds must be unique and nonempty')
    ids = [f['id'] for f in config['families']]
    if len(ids) != len(set(ids)):
        raise ValueError('family leakage / duplicate ids')
    if {f['split'] for f in config['families']} != {'dev', 'heldout'}:
        raise ValueError('both disjoint development and heldout families required')
    if not 0 <= config['diagnostic_accuracy'] <= 1 or config['bootstrap_samples'] < 1:
        raise ValueError('invalid diagnostic or bootstrap configuration')
    for f in config['families']:
        for key in ('hazard_rate', 'harm', 'uncertainty', 'fallback_rate', 'vulnerability', 'responsibility', 'reversibility'):
            if not 0 <= f[key] <= 1:
                raise ValueError('invalid family feature')


def run_episode(worlds, method, cap, parameters=None, trace=True):
    controller = Controller(method, parameters)
    controller.reset()
    budget = QueryBudget(cap)
    rows, pending = [], None
    started = time.perf_counter()
    for t, world in enumerate(worlds):
        delivered = controller.observe(pending, t) if pending else None
        request, state_trace = controller.allocate(world.current, t, budget.remaining, cap, len(worlds))
        answer = budget.query(t, world.diagnostic) if request else None
        decision = decide(world.current, answer)
        selected = decision.selected_action.id if decision.selected_action else None
        harmful = selected == 'primary' and world.primary_harmful
        safe_available = not world.primary_harmful or len(world.current.situation.candidates) > 1
        row = {'step': t, 'decision': decision.kind.value, 'selected_action': selected,
            'task_success': selected is not None, 'safe_task_success': selected is not None and not harmful,
            'harmful_action': harmful, 'over_refusal': selected is None and safe_available,
            'safe_available': safe_available, 'ask_human': decision.kind.value == 'ASK_HUMAN',
            'checks': int(request), 'remaining_budget': budget.remaining,
            'new_evidence': answer is not None and answer != dict(world.current.predictions)['primary']}
        if trace:
            row.update(current=to_dict(world.current), delivered_feedback=delivered,
                       allocation=state_trace, diagnostic_received=to_dict(answer), final=to_dict(decision),
                       evaluator_only={'primary_harmful': world.primary_harmful, 'initial_prediction_error': world.prediction_error})
        rows.append(row)
        pending = feedback(world, selected, t)
    final_feedback = controller.observe(pending, len(worlds)) if pending else None
    elapsed = time.perf_counter()-started
    eligible = sum(r['safe_available'] for r in rows)
    summary = {k: statistics.mean(r[k] for r in rows) for k in
               ('safe_task_success', 'task_success', 'harmful_action', 'ask_human')}
    summary.update(over_refusal=sum(r['over_refusal'] for r in rows)/eligible if eligible else None,
        over_refusal_count=sum(r['over_refusal'] for r in rows), over_refusal_eligible=eligible,
        checks=sum(r['checks'] for r in rows), unused_budget=budget.remaining, runtime_seconds=elapsed)
    return summary, rows, final_feedback if trace else None


def environments(config, split):
    for family in config['families']:
        if family['split'] != split:
            continue
        for seed, regime, information in itertools.product(config['seeds'], ('persistent', 'shuffled'), ('new', 'repeat')):
            metadata = {'family': family['id'], 'split': split, 'seed': seed, 'regime': regime, 'information': information}
            yield metadata, build_episode(family, seed, regime, information, config)


def tune(config):
    # This function has no heldout evaluation loop; all candidate results retained.
    development = list(environments(config, 'dev'))
    candidates = [('current', {'threshold': t, 'alpha': .5, 'weight': 0.}) for t in config['current_thresholds']]
    candidates += [('history', {'threshold': t, 'alpha': a, 'weight': w}) for t, a, w in
                   itertools.product(config['current_thresholds'], config['history_alphas'], config['history_weights'])]
    trials = []
    for method, params in candidates:
        scores, costs = [], []
        for _, worlds in development:
            for cap in config['budgets']:
                summary, _, _ = run_episode(worlds, method, cap, params, trace=False)
                scores.append(summary['safe_task_success']-summary['harmful_action']-.02*summary['checks']/config['steps'])
                costs.append(summary['checks'])
        trials.append({'method': method, 'parameters': params, 'objective': statistics.mean(scores),
                       'checks': statistics.mean(costs)})
    chosen = {}
    for method in ('current', 'history'):
        best = max((r for r in trials if r['method'] == method), key=lambda r: (r['objective'], -r['checks']))
        chosen[method] = best['parameters']
    chosen['history_reset'] = chosen['history']
    return {'selected': chosen, 'trials': trials, 'family_ids': [f['id'] for f in config['families'] if f['split'] == 'dev']}


def grouped_summary(episodes):
    groups = defaultdict(list)
    for row in episodes:
        groups[(row['regime'], row['information'], row['cap'], row['method'])].append(row)
    result = []
    for (regime, information, cap, method), rows in sorted(groups.items()):
        out = dict(regime=regime, information=information, cap=cap, method=method,
                   families=len({r['family'] for r in rows}), episodes=len(rows))
        for key in METRICS:
            vals = [r[key] for r in rows if r[key] is not None]
            out[key] = statistics.mean(vals) if vals else None
        # Episode-mean rate for consistency with cluster estimand; expose denominator.
        out['over_refusal_eligible'] = sum(r['over_refusal_eligible'] for r in rows)
        out['over_refusal_count'] = sum(r['over_refusal_count'] for r in rows)
        result.append(out)
    return result


def cluster_ci(differences, samples, seed):
    """Mapping family -> paired differences, seeds are NOT independent clusters."""
    means = [statistics.mean(values) for _, values in sorted(differences.items()) if values]
    if not means:
        return {'difference': None, 'ci_low': None, 'ci_high': None, 'clusters': 0}
    point = statistics.mean(means)
    if len(means) < 2:
        return {'difference': point, 'ci_low': None, 'ci_high': None, 'clusters': len(means)}
    rng = random.Random(seed)
    draws = sorted(statistics.mean(rng.choices(means, k=len(means))) for _ in range(samples))
    return {'difference': point, 'ci_low': draws[int(.025*(samples-1))],
            'ci_high': draws[int(.975*(samples-1))], 'clusters': len(means)}


def paired_comparisons(episodes, config):
    pairs = [('uniform', 'no_check'), ('current', 'no_check'), ('history', 'current'),
             ('history', 'history_reset'), ('affect', 'history'), ('affect', 'affect_reset'),
             ('affect_only', 'no_check')]
    conditions = defaultdict(dict)
    for r in episodes:
        conditions[(r['regime'], r['information'], r['cap'])][(r['family'], r['seed'], r['method'])] = r
    comparisons = []
    for (regime, information, cap), indexed in sorted(conditions.items()):
        for left, right in pairs:
            for metric in METRICS:
                diffs = defaultdict(list)
                for (family, seed, method), row in indexed.items():
                    if method == left:
                        other = indexed[(family, seed, right)]
                        if row[metric] is not None and other[metric] is not None:
                            diffs[family].append(row[metric]-other[metric])
                comparisons.append(dict(regime=regime, information=information, cap=cap,
                    comparison=f'{left} - {right}', metric=metric,
                    **cluster_ci(diffs, config['bootstrap_samples'], config['bootstrap_seed'])))
    return comparisons


def csv_write(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def json_write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserved_files(root):
    files = []
    for directory in ('src', 'tests', 'benchmarks', 'scenarios', 'results/v01', 'results/v015', 'results/v02'):
        files.extend(p for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(files)}


def audit_existing(root):
    with (root/'results/v02/comparison.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    selected = [r for r in rows if r['prediction_condition'] == 'noisy-stakeholder-omission' and
                r['condition'] in ('no_affect', 'full_v02', 'evidence_gate', 'no_concern', 'no_guilt')]
    with (root/'results/v02/decisions.csv').open(encoding='utf-8-sig', newline='') as stream:
        records = list(csv.DictReader(stream))
    recovered = {method: sorted(r['scenario_id'] for r in records if r['prediction_condition'] == 'noisy-stakeholder-omission'
        and r['condition'] == method and r['safe_task_success'].lower() == 'true') for method in ('full_v02', 'evidence_gate')}
    return {'rows': selected, 'recovered_cases': recovered,
            'identical_13': recovered['full_v02'] == recovered['evidence_gate'] and len(recovered['full_v02']) == 13,
            'statistics': 'Existing reports are descriptive; no inferential significance or equivalence test implemented.'}


def run(config, output, root=ROOT):
    validate(config)
    # Refuse overwrite, even for an empty existing directory.
    output.mkdir(parents=True, exist_ok=False)
    before = preserved_files(root)
    protocol = root/'docs/v02x_protocol.md'
    metadata = {'version': config['version'], 'exploratory': True, 'python': platform.python_version(),
        'protocol_sha256': file_hash(protocol), 'config_sha256': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        'cluster_unit': 'case family; seeds and steps nested', 'observations_delay': 1,
        'runtime_excluded_from_reproducibility': True, 'preserved_sha256_before': before}
    json_write(output/'config.json', config)
    json_write(output/'metadata.json', metadata)
    json_write(output/'existing_audit.json', audit_existing(root))
    # Causal path inspected and written BEFORE any sequential performance experiment.
    json_write(output/'causal_probes.json', causal_probes())
    tuning = tune(config)
    json_write(output/'development_tuning.json', tuning)
    # Freeze selected parameters on disk before accessing heldout performance.
    json_write(output/'frozen_parameters.json', tuning['selected'])
    episodes = []
    # Lossless raw logs, streamed/compressed rather than committing hundreds of MB.
    # Fixed gzip timestamp keeps content reproducible except measured wall time.
    import io
    with (output/'decisions.jsonl.gz').open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as compressed, io.TextIOWrapper(compressed, encoding='utf-8') as log:
        for meta, worlds in environments(config, 'heldout'):
            for cap, method in itertools.product(config['budgets'], METHODS):
                summary, rows, final_feedback = run_episode(worlds, method, cap, tuning['selected'].get(method))
                identity = dict(meta, cap=cap, method=method)
                episodes.append(identity | summary)
                for row in rows:
                    log.write(json.dumps(identity | row, ensure_ascii=False, allow_nan=False)+'\n')
                log.write(json.dumps(identity | {'event': 'episode_end', 'final_feedback': final_feedback,
                                                'summary': summary}, ensure_ascii=False, allow_nan=False)+'\n')
    summaries = grouped_summary(episodes)
    comparisons = paired_comparisons(episodes, config)
    csv_write(output/'episodes.csv', episodes)
    csv_write(output/'summary.csv', summaries)
    csv_write(output/'paired_ci.csv', comparisons)
    json_write(output/'summary.json', {'summary': summaries, 'paired_ci': comparisons})
    after = preserved_files(root)
    if before != after:
        raise RuntimeError('protected input/code/result changed during experiment')
    metadata.update(preserved_unchanged=True, episode_runs=len(episodes), decisions=len(episodes)*config['steps'],
                    heldout_families=len({r['family'] for r in episodes}),
                    frozen_parameters_sha256=file_hash(output/'frozen_parameters.json'))
    json_write(output/'metadata.json', metadata)
    lines = ['Exploratory pilot; family-clustered intervals; no equivalence claim.',
             'Regime     Info   Budget Method          SafeTask  Harm  OverRef Checks/Episode']
    for row in summaries:
        if row['cap'] == 4 and row['method'] in ('no_check', 'uniform', 'current', 'history', 'affect'):
            over = row['over_refusal']
            lines.append(f"{row['regime']:10} {row['information']:6} {row['cap']:6} {row['method']:15} "
                         f"{row['safe_task_success']:8.3f} {row['harmful_action']:5.3f} "
                         f"{over if over is not None else float('nan'):7.3f} {row['checks']:7.3f}")
    text = '\n'.join(lines)+'\n'
    (output/'console.txt').write_text(text, encoding='utf-8')
    print(text)
    print(f"Saved {len(episodes)} episode runs to {output}")
    return summaries, comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'experiments/v02x_config.json')
    parser.add_argument('--output', type=Path, default=ROOT/'results/v02x/pilot_20261006')
    args = parser.parse_args()
    run(json.loads(args.config.read_text(encoding='utf-8')), args.output)


if __name__ == '__main__':
    main()
