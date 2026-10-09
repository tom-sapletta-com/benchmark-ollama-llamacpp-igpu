"""Offline consistency checks for quality evidence; model failures remain valid evidence."""
import ast
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path

from quality_cases import CASES, prompt

ROOT = Path(__file__).resolve().parents[1]


def expected_tests(case):
    tree = ast.parse(case['tests'])
    return {f'withheld_tests.{node.name}.{fn.name}' for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name in ('Functional', 'Regression')
            for fn in node.body if isinstance(fn, ast.FunctionDef) and fn.name.startswith('test_')}


def verify_evaluation(evaluation, case):
    expected = expected_tests(case)
    assert set(evaluation['expected_tests']) == expected
    rows = evaluation['tests']
    assert len({r['id'] for r in rows}) == len(rows)
    assert all(r['id'] in expected and isinstance(r['passed'], bool) for r in rows)
    if evaluation['status'] == 'complete':
        assert {r['id'] for r in rows} == expected
    return {group: {'passed': sum(r['passed'] for r in rows if '.' + group + '.' in r['id']),
                    'total': sum('.' + group + '.' in name for name in expected)}
            for group in ['Functional', 'Regression']}


def verify(directory=None):
    directory = directory or ROOT / 'results/coding-quality-20261009'
    report = json.loads((directory / 'results.json').read_text())
    cases_bytes = (directory / 'cases.json').read_bytes()
    assert hashlib.sha256(cases_bytes).hexdigest() == report['cases_sha256']
    assert json.loads(cases_bytes) == CASES, 'Fixture drift from measured cases'
    cases = {case['id']: case for case in CASES}
    assert report['schema'] == 'igpu-coding-quality/v1' and report['status'] == 'complete'
    repeats = report['settings']['repeats']
    assert len(report['results']) == 3 * repeats
    assert Counter((r['case'], r['repeat']) for r in report['results']) == {
        (case, repeat): 1 for case in cases for repeat in range(1, repeats + 1)}
    assert len(report['controls']) == 3
    assert {c['case'] for c in report['controls']} == set(cases)
    for control in report['controls']:
        case = cases[control['case']]
        reference = verify_evaluation(control['reference'], case)
        assert control['reference']['status'] == 'complete'
        assert all(g['passed'] == g['total'] for g in reference.values())
        baseline = verify_evaluation(control['baseline'], case)
        assert any(g['passed'] < g['total'] for g in baseline.values())
        if case['kind'] == 'three_file_fix':
            assert {a['restored_buggy_file'] for a in control['ablations']} == set(case['before'])
            for ablation in control['ablations']:
                groups = verify_evaluation(ablation['evaluation'], case)
                assert any(g['passed'] < g['total'] for g in groups.values())
    for row in report['results']:
        case = cases[row['case']]
        assert row['request']['messages'] == [{'role': 'user', 'content': prompt(case)}]
        assert row['prompt_sha256'] == hashlib.sha256(prompt(case).encode()).hexdigest()
        assert row['request']['options']['temperature'] == 0
        assert row['request']['options']['seed'] == 42
        assert row['request']['think'] == 'low' and row['request']['format'] == 'json'
        assert row['final_event']['done']
        assert row['truncated'] == (row['final_event'].get('done_reason') == 'length')
        assert row['wall_seconds'] > 0 and row['generated_tokens'] == row['final_event']['eval_count']
        groups = verify_evaluation(row['evaluation'], case)
        assert row['correctness'] == groups['Functional'] and row['regression'] == groups['Regression']
        if 'files' in row:
            files = row['files']
            assert json.loads(row['content']) == {'files': files}
            assert set(files) == set(case['before'])
            changed = [name for name in files if files[name] != case['before'][name]]
            assert row['scope']['changed_files'] == changed
            assert row['scope']['passed'] == (set(changed) == set(case['before']))
            assert row['diff'] == ''.join(''.join(difflib.unified_diff(case['before'][name].splitlines(True),
                                    code.splitlines(True), fromfile='before/' + name, tofile='after/' + name))
                                    for name, code in files.items())
        expected_pass = (not row['truncated'] and row['scope']['passed'] and row['evaluation']['status'] == 'complete'
                         and all(g['passed'] == g['total'] for g in groups.values()))
        assert row['passed'] == expected_pass
    if 'reassessment' in report:
        receipt = report['reassessment']
        initial_bytes = (ROOT / receipt['source_report']).read_bytes()
        assert hashlib.sha256(initial_bytes).hexdigest() == receipt['source_report_sha256']
        initial = json.loads(initial_bytes)
        assert initial['cases_sha256'] == receipt['source_cases_sha256']
        assert receipt['generated_new_answers'] is False
        old_rows = {(r['case'], r['repeat']): r for r in initial['results']}
        for row in report['results']:
            old = old_rows[row['case'], row['repeat']]
            for key in ['request', 'content', 'thinking', 'final_event', 'prompt_sha256',
                        'wall_seconds', 'ttft_seconds', 'generated_tokens', 'tokens_per_second', 'truncated']:
                assert row[key] == old[key], (row['case'], row['repeat'], key)
    return {'cases': 3, 'trials': len(report['results']), 'passed_trials': sum(r['passed'] for r in report['results']),
            'functional_passed': sum(r['correctness']['passed'] for r in report['results']),
            'compatibility_passed': sum(r['regression']['passed'] for r in report['results']),
            'reference_controls': 3, 'three_file_ablations': 3}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
