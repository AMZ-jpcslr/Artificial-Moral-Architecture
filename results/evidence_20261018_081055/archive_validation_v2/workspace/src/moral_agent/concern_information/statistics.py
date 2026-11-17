"""Episode averages and paired family-cluster bootstrap for an exploratory pilot.

Rates (including over-refusal and escalation recall) are means of defined
episode rates, not pooled decision counts. Missing-denominator rates stay None.
Seeds/decisions are nested within families and never independent bootstrap units.
Intervals are descriptive, unadjusted for multiplicity; no equivalence is tested.
"""
from collections import defaultdict
import hashlib
import random
from statistics import mean


KEYS = ('experiment', 'mode', 'accuracy', 'budget', 'variant')
METRICS = ('safe_task_success', 'task_success', 'harmful_action', 'over_refusal',
           'ask_human', 'appropriate_escalation', 'escalation_recall',
           'safe_recovery', 'checks', 'query_cost', 'additional_predictions',
           'alternative_searches', 'stakeholder_checks', 'runtime_seconds',
           'direct_safe_delta', 'direct_harm_delta', 'concern_changed_source', 'concern_changed_decision')


def summarize(episodes):
    """Return one descriptive row per condition, keeping dataset splits apart."""
    groups = defaultdict(list)
    for row in episodes:
        groups[(row.get('split', 'unspecified'), *(row[k] for k in KEYS))].append(row)
    result = []
    for key, rows in sorted(groups.items(), key=lambda item: repr(item[0])):
        record = dict(zip(('split', *KEYS), key))
        record.update(episodes=len(rows), families=len({r['family'] for r in rows}),
                      aggregation='mean of defined episode rates; no pooled denominators')
        for metric in METRICS:
            values = [r[metric] for r in rows if r.get(metric) is not None]
            record[metric] = mean(values) if values else None
            record[metric + '_defined_episodes'] = len(values)
        result.append(record)
    return result


def _index(rows):
    index = {}
    for row in rows:
        key = (row['family'], row['seed'])
        if key in index:
            raise ValueError('Duplicate episode identity within condition: ' + repr(key))
        index[key] = row
    return index


def _estimate(left, right, metric, bootstrap, seed):
    grouped = defaultdict(list)
    common = left.keys() & right.keys()
    for key in sorted(common, key=repr):
        a, b = left[key].get(metric), right[key].get(metric)
        if a is not None and b is not None:
            grouped[key[0]].append(a-b)
    family_effects = {f: mean(v) for f, v in sorted(grouped.items())}
    values = list(family_effects.values())
    n = len(values)
    point = mean(values) if values else None
    loo = [{'omitted_family': f, 'difference': mean(v for k, v in family_effects.items() if k != f)}
           for f in family_effects] if n > 1 else []
    low = high = None
    if n > 1:
        rng = random.Random(seed)
        draws = sorted(sum(rng.choices(values, k=n))/n for _ in range(bootstrap))
        low, high = draws[int(.025*(bootstrap-1))], draws[int(.975*(bootstrap-1))]
    return dict(difference=point, ci_low=low, ci_high=high, clusters=n,
                paired_episodes=sum(map(len, grouped.values())),
                matched_episode_identities=len(common),
                unmatched_left=len(left.keys()-right.keys()),
                unmatched_right=len(right.keys()-left.keys()),
                family_effects=family_effects,
                leave_one_family_out_min=min((r['difference'] for r in loo), default=None),
                leave_one_family_out_max=max((r['difference'] for r in loo), default=None),
                leave_one_family_out=loo,
                estimand='equal-family mean of within-family paired episode differences; defined pairs only')


def comparisons(episodes, bootstrap=1000, seed=19):
    """Paired contrasts; absent conditions are skipped, missing pairs disclosed.

    Includes same-cost variant comparisons, Experiment I information contrasts,
    and randomized source assignment against no query. No-query is allowed at
    budget zero and is labelled as a different-cost comparison explicitly.
    """
    if type(bootstrap) is not int or bootstrap < 2:
        raise ValueError('bootstrap must be an integer >= 2')
    groups = defaultdict(list)
    for row in episodes:
        groups[(row.get('split', 'unspecified'), *(row[k] for k in KEYS))].append(row)
    indexed = {k: _index(v) for k, v in groups.items()}
    planned = []
    seen = set()

    def add(left, right, kind):
        if left in indexed and right in indexed and (left, right) not in seen:
            seen.add((left, right))
            planned.append((left, right, kind))

    for key in sorted(indexed, key=repr):
        split, experiment, mode, accuracy, budget, variant = key
        prefix = key[:-1]
        tag = str(experiment).lower()
        if tag in ('i', '1', 'information'):
            for a, b in (('state', 'off'), ('final', 'off')):
                add((*prefix, a), (*prefix, b), 'same_information_concern')
            if mode == 'relevant' and variant in ('off', 'final'):
                add(key, (split, experiment, 'repeat', accuracy, budget, variant), 'information_value')
                add(key, (split, experiment, 'irrelevant', accuracy, budget, variant), 'information_relevance')
                other = (split, experiment, 'none', accuracy, budget, variant)
                if other not in indexed:
                    other = (split, experiment, 'none', accuracy, 0, variant)
                add(key, other, 'information_value_vs_no_query_different_cost')
        elif tag in ('ii', '2', 'selection'):
            for a, b in (('select', 'history'), ('both', 'final'), ('final', 'history'),
                         ('both', 'select'), ('history', 'uniform'), ('history', 'current'),
                         ('state', 'history'), ('select', 'uniform'), ('both', 'uniform')):
                add((*prefix, a), (*prefix, b), 'concern_path_or_policy')
        elif tag == 'assignment' and mode != 'none' and variant == 'off':
            other = (split, experiment, 'none', accuracy, budget, variant)
            if other not in indexed:
                other = (split, experiment, 'none', accuracy, 0, variant)
            add(key, other, 'assigned_source_vs_no_query_different_cost')

    result = []
    for left, right, kind in planned:
        identity = repr((left, right)).encode('utf-8')
        paired_seed = seed + int.from_bytes(hashlib.sha256(identity).digest()[:8], 'big')
        for metric in METRICS:
            record = dict(zip(('split', *KEYS), left))
            record.update(comparison=f'{left[-1]}[{left[2]}] - {right[-1]}[{right[2]}]',
                          contrast_kind=kind, metric=metric, left_variant=left[-1],
                          right_variant=right[-1], left_mode=left[2], right_mode=right[2],
                          left_budget=left[4], right_budget=right[4],
                          cost_comparison='actual checks and query_cost must be examined; upper bounds are not equal cost',
                          bootstrap_samples=bootstrap, interval='95% percentile family bootstrap; exploratory, unadjusted')
            record.update(_estimate(indexed[left], indexed[right], metric, bootstrap, paired_seed))
            result.append(record)
    return result
