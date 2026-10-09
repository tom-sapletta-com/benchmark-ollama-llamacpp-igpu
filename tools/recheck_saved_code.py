"""Rerun saved coding answers in the original networkless Docker sandbox."""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/allama-src'))
from allama.benchmark import functional_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists')
    report = json.loads((ROOT / 'results/minis-20261009/results.json').read_text())
    tests = {task['id']: task['tests'] for task in report['tasks']}
    evidence = []
    for row in report['results']:
        check = functional_check(row['code'], tests[row['task']])
        evidence.append({'profile': row['profile'], 'task': row['task'], 'repeat': row['repeat'], **check})
        args.output.write_text(json.dumps(evidence, indent=2) + '\n')
        print(len(evidence), row['profile'], row['task'], check['status'], flush=True)
        if check['status'] == 'infra_error':
            return 2
    return 0 if all(item['passed'] for item in evidence) else 1


if __name__ == '__main__':
    raise SystemExit(main())
