"""Post-evaluation descriptive extraction; never changes the frozen experiment."""
import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    args = parser.parse_args()
    root = args.results
    data = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
    summaries = data['summary']
    metrics = ('safe_task_success', 'harmful_action', 'over_refusal', 'ask_human',
               'escalation_recall', 'safe_recovery', 'direct_safe_delta', 'direct_harm_delta')
    extracted = {
        'primary': [r for r in summaries if r['accuracy'] == 'medium' and r['budget'] == 4],
        'primary_contrasts': [r for r in data['contrasts'] if r['accuracy'] == 'medium'
                              and r['budget'] == 4 and r['metric'] in metrics],
        'accuracy_and_cost': [r for r in summaries if r['experiment'] == 'II'
                              and r['variant'] in ('uniform', 'history', 'select', 'both')],
    }
    # Audit every recorded decision, not only aggregate equality. Concern state
    # is intentionally excluded; behavior and all other affect values are not.
    signatures = {}
    counts = defaultdict(int)
    with gzip.open(root / 'decisions.jsonl.gz', 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row.get('event'):
                continue
            counts['decisions'] += 1
            if row['experiment'] not in ('I', 'II'):
                continue
            control = 'off' if row['experiment'] == 'I' else 'history'
            if row['variant'] not in ('state', control):
                continue
            key = (row['experiment'], row['mode'], row['accuracy'], row['budget'],
                   row['family'], row['seed'], row['step'])
            state = dict(row['concern_trace']['after'])
            state.pop('concern', None)
            payload = {k: row[k] for k in ('decision', 'selected_action', 'channel',
                                          'obtained_information', 'updated_prediction')}
            payload['other_affects'] = state
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            entry = signatures.setdefault(key, {})
            entry[row['variant']] = digest
    mismatches = []
    for key, values in signatures.items():
        counts['state_only_pairs'] += 1
        if len(values) != 2 or len(set(values.values())) != 1:
            mismatches.append(key)
    extracted['state_only_audit'] = dict(counts) | {'mismatches': mismatches}
    target = root / 'descriptive_audit.json'
    if target.exists():
        raise FileExistsError('Refusing to overwrite ' + str(target))
    target.write_text(json.dumps(extracted, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(extracted['state_only_audit']))
    print(target)


if __name__ == '__main__':
    main()
