"""Reassess saved model outputs after evaluator correction; no inference or service control."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from quality_benchmark import evaluate, save, sandbox
from quality_cases import CASES, prompt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists(): parser.error('Choose a fresh output directory')
    source_bytes = (args.input / 'results.json').read_bytes()
    original = json.loads(source_bytes)
    if original['status'] != 'complete': parser.error('Source benchmark is not complete')
    cases = {case['id']: case for case in CASES}
    for row in original['results']:
        if row['request']['messages'] != [{'role': 'user', 'content': prompt(cases[row['case']])}]:
            parser.error('Prompt changed; stored inference cannot be reused')
    args.output.mkdir(parents=True)
    snapshot = json.dumps(CASES, ensure_ascii=False, indent=2) + '\n'
    (args.output / 'cases.json').write_text(snapshot)
    report = copy.deepcopy(original)
    report.update(status='running', results=[], controls=[], cases_sha256=hashlib.sha256(snapshot.encode()).hexdigest())
    report['reassessment'] = {
        'source_report': 'results/coding-quality-initial-20261009/results.json',
        'source_report_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'source_cases_sha256': original['cases_sha256'],
        'initial_evaluator': 'evidence/scripts-as-run/quality-benchmark-initial.py',
        'reason': 'Poprawiono oceniający skrypt: legalny import __future__ nie jest blokowany, '
                  'numer linii jest akceptowany niezależnie od wielkości liter, a błąd składni '
                  'jest oddzielony od poprawności zakresu plików. Nie poprawiano odpowiedzi modelu.',
        'generated_new_answers': False,
    }
    try:
        for case in CASES:
            control = {'case': case['id'], 'baseline': sandbox(case['before'], case),
                       'reference': sandbox(case['reference'], case), 'ablations': []}
            if case['kind'] == 'three_file_fix':
                for name in case['before']:
                    files = dict(case['reference']); files[name] = case['before'][name]
                    control['ablations'].append({'restored_buggy_file': name, 'evaluation': sandbox(files, case)})
            assert control['reference']['status'] == 'complete'
            assert all(t['passed'] for t in control['reference']['tests'])
            assert control['baseline']['status'] != 'complete' or not all(t['passed'] for t in control['baseline']['tests'])
            for ablation in control['ablations']:
                assert ablation['evaluation']['status'] != 'complete' or not all(t['passed'] for t in ablation['evaluation']['tests'])
            report['controls'].append(control)
            save(report, args.output)
        derived = {'files', 'static_review', 'scope', 'diff', 'evaluation', 'correctness', 'regression',
                   'passed', 'format_error', 'syntax_error'}
        for original_row in original['results']:
            row = {key: value for key, value in original_row.items() if key not in derived}
            evaluate(row, cases[row['case']])
            report['results'].append(row); save(report, args.output)
            print(row['case'], row['repeat'], 'PASS' if row['passed'] else 'FAIL',
                  row['evaluation']['status'], row['correctness'], row['regression'], flush=True)
        report['status'] = 'complete'
    except BaseException as exc:
        report.update(status='interrupted', error=str(exc)); raise
    finally:
        save(report, args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
