"""Offline verification of historical Koru/OpenCode comparison evidence."""
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify():
    directory = ROOT/'results/opencode-koru-20261009'
    report = json.loads((directory/'results.json').read_text())
    pin = json.loads((directory/'provenance.json').read_text())
    assert report['status'] == 'complete' and report['schema'] == 'igpu-opencode-koru/v1'
    assert pin['planfile_ticket'] == report['task'] == 'STARTER-614'
    for name, digest in pin['files'].items():
        assert hashlib.sha256((directory/'fixture'/name).read_bytes()).hexdigest() == digest, name
    assert hashlib.sha256((directory/'fixture/test_stream_regression.initial.py').read_bytes()).hexdigest() == pin['initial_withheld_tests_sha256']
    initial = json.loads((directory/'controller-results.json').read_text())
    assert initial['status'] == 'complete'
    initial_rows = {row['trial']: row for row in initial['results']}
    reassessed = json.loads((directory/'reassessment.json').read_text())
    for control in ['baseline', 'reference']:
        assert report[control] == reassessed[control]
    for control in ['baseline', 'reference']:
        row = report[control]
        assert row['test_summary']['passed'] == row['test_summary']['total'] == 24
        assert row['test_exit'] == 0 and row['syntax_passed'] and row['lint_passed']
    assert not report['baseline']['complexity_passed'] and report['reference']['complexity_passed']
    expected_ids = {test['nodeid'] for test in report['reference']['tests']}
    assert len(expected_ids) == 24
    assert Counter((r['model'],r['repeat']) for r in report['results']) == {
        (name,rep):1 for name in ['gemma4:12b','gpt-oss:20b'] for rep in range(1,report['settings']['repeats']+1)}
    baseline = (directory/'fixture/dashboard_logs.py').read_text()
    for row in report['results']:
        original = initial_rows[row['trial']]
        for field in ['source', 'diff', 'events', 'wall_seconds', 'changed_files', 'memory_samples']:
            assert row[field] == original[field], (row['trial'], field)
        assert row['evaluation'] == reassessed[row['trial']]
        assert row['configuration']['enabled_providers'] == ['local-benchmark']
        assert row['configuration']['model'] == 'local-benchmark/'+row['model']
        assert row['configuration']['agent']['benchmark']['steps'] == report['settings']['steps']
        assert row['baseline_file_hashes']['src/koruapi/dashboard_logs.py'] == pin['files']['dashboard_logs.py']
        assert row['baseline_file_hashes']['tests/test_dashboard_logs.py'] == pin['files']['test_dashboard_logs.py']
        assert row['scope_passed'] == (row['changed_files'] == ['src/koruapi/dashboard_logs.py'])
        assert row['diff'] == ''.join(difflib.unified_diff(baseline.splitlines(True),row['source'].splitlines(True),
                                  fromfile='before/src/koruapi/dashboard_logs.py',tofile='after/src/koruapi/dashboard_logs.py'))
        evaluation = row['evaluation']
        if evaluation['test_exit'] == 0:
            assert {test['nodeid'] for test in evaluation['tests']} == expected_ids
            assert all(t['outcome'] == 'passed' for t in evaluation['tests'])
        assert row['passed'] == (row['scope_passed'] and not row['timed_out'] and evaluation['test_exit']==0
                                and evaluation['complexity_passed'] and evaluation['lint_passed'] and evaluation['syntax_passed'])
        assert row['memory_samples'] and row['wall_seconds'] > 0
        for call in row['api_calls']:
            assert call['trial'] == row['trial'] and call['request']['model'] == row['model']
            assert call['request']['temperature'] == 0 and call['request']['seed'] == 42
            assert call['request']['max_tokens'] <= 4096
    restored = report['production_ps_restored']['models']
    assert len(restored)==1 and restored[0]['name']=='gpt-oss-minis-code:20b'
    assert restored[0]['context_length']==16384 and restored[0]['size_vram']==restored[0]['size']
    return {'task':'STARTER-614','trials':len(report['results']),'model_passes':dict(Counter(r['model'] for r in report['results'] if r['passed'])),
            'baseline_tests':24,'withheld_tests':8,'production_restored':'Ollama Q8 full GPU'}


if __name__ == '__main__':
    print(json.dumps(verify(),indent=2))
