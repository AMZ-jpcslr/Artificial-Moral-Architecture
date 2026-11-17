"""Post-run descriptive diagnostics; never changes controllers or fitted settings."""
import argparse
from collections import defaultdict
import csv
import gzip
import json
from pathlib import Path
import statistics


def analyze(directory):
    with (directory/'episodes.csv').open(encoding='utf-8', newline='') as stream:
        episodes = list(csv.DictReader(stream))
    grouped = defaultdict(dict)
    for r in episodes:
        if r['information'] == 'new' and r['cap'] == '4':
            grouped[(r['regime'], r['family'], r['seed'])][r['method']] = r
    families = defaultdict(list)
    for (regime, family, _), methods in grouped.items():
        families[regime, family].append({
            'history_minus_current': float(methods['history']['safe_task_success'])-float(methods['current']['safe_task_success']),
            'affect_minus_history': float(methods['affect']['safe_task_success'])-float(methods['history']['safe_task_success'])})
    family_rows = [{'regime': regime, 'family': family,
                    **{k: statistics.mean(r[k] for r in rows) for k in rows[0]}}
                   for (regime, family), rows in families.items()]
    # Only retain a few methods for paired descriptive failure analysis.
    decisions = defaultdict(dict)
    with gzip.open(directory/'decisions.jsonl.gz', 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if 'event' in row or row['cap'] != 4 or row['information'] != 'new':
                continue
            if row['method'] in ('history', 'affect', 'affect_reset'):
                key = row['regime'], row['family'], row['seed'], row['step']
                decisions[key][row['method']] = row
    counts, examples = defaultdict(int), {}
    for key, methods in decisions.items():
        a, c, reset = methods['affect'], methods['history'], methods['affect_reset']
        flags = {
            'affect_introduced_harm_vs_history': a['harmful_action'] and not c['harmful_action'],
            'affect_avoided_harm_vs_history': c['harmful_action'] and not a['harmful_action'],
            'affect_lost_safe_success_vs_history': c['safe_task_success'] and not a['safe_task_success'],
            'affect_gained_safe_success_vs_history': a['safe_task_success'] and not c['safe_task_success'],
            'persistence_introduced_overrefusal_vs_reset': a['over_refusal'] and not reset['over_refusal'],
            'persistence_avoided_harm_vs_reset': reset['harmful_action'] and not a['harmful_action'],
        }
        for flag, active in flags.items():
            if active:
                counts[key[0]+'/'+flag] += 1
                examples.setdefault(key[0]+'/'+flag, {'identity': key, 'affect': a, 'history': c, 'affect_reset': reset})
    return {'posthoc_descriptive_only': True, 'family_differences': family_rows,
            'paired_step_counts_not_independent_samples': dict(counts), 'examples': examples}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path('results/v02x/pilot_20261006'))
    args = parser.parse_args()
    diagnostics = analyze(args.results)
    with (args.results/'diagnostics.json').open('x', encoding='utf-8') as stream:
        json.dump(diagnostics, stream, ensure_ascii=False, indent=2)
    print(json.dumps(diagnostics['paired_step_counts_not_independent_samples'], indent=2))
