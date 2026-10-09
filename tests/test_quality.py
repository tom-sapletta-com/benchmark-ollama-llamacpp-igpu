import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from quality_benchmark import evaluate, parse_files, static_review, test_ids as case_test_ids
from quality_cases import CASES, prompt
from verify_quality import verify


def test_case_contracts_and_prompt_has_no_reference_or_tests():
    assert [len(c['before']) for c in CASES] == [1, 1, 3]
    for case in CASES:
        assert len(case_test_ids(case)) == 12
        assert len([name for name in case_test_ids(case) if '.Functional.' in name]) == 8
        assert case['tests'] not in prompt(case)
        assert case['reference'] != case['before']
        for code in case['before'].values(): assert code in prompt(case)


@pytest.mark.parametrize('value', [
    {'files': {'../invoice_summary.py': 'x=1'}},
    {'files': {'invoice_summary.py': 'x=1', 'tests.py': 'x=1'}},
    {'files': {}}, {'files': {'invoice_summary.py': 12}},
    {'files': {'invoice_summary.py': 'x=1'}, 'explanation': 'hi'},
])
def test_reject_unrequested_files_or_schema(value):
    with pytest.raises(ValueError): parse_files(json.dumps(value), CASES[0])


def test_reference_static_review():
    for case in CASES: assert not static_review(case['reference'])['blocked']
    assert not static_review({'a.py': 'from __future__ import annotations\n'})['blocked']


def test_syntax_and_scope_are_separate():
    row = {'content': json.dumps({'files': {'invoice_summary.py': 'def broken(:\n'}}), 'truncated': False}
    evaluate(row, CASES[0])
    assert row['scope']['passed'] and not row['passed']
    assert row['evaluation']['status'] == 'syntax_error'


def test_no_host_execution_and_static_rejects_dangerous_access():
    assert static_review({'a.py': 'import subprocess\n'})['blocked']
    assert static_review({'a.py': 'open("/etc/passwd")\n'})['blocked']
    row = {'content': '{"files": {"../wrong.py": "print(42)"}}', 'truncated': False}
    evaluate(row, CASES[0])
    assert not row['passed'] and row['evaluation']['status'] == 'invalid_output'


def test_line_number_contract_accepts_case_variation():
    assert "r'(?i)line 3\\b'" in CASES[0]['tests']


def test_candidate_resource_failure_is_not_transport_failure(monkeypatch):
    import quality_benchmark
    from types import SimpleNamespace
    monkeypatch.setattr(quality_benchmark.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=137, stdout='', stderr=''))
    assert quality_benchmark.sandbox(CASES[0]['reference'], CASES[0])['status'] == 'resource_limit'


def test_truncation_never_passes():
    row = {'content': json.dumps({'files': CASES[0]['reference']}), 'truncated': True}
    evaluate(row, CASES[0])
    assert not row['passed'] and row['evaluation']['status'] == 'truncated'


def test_quality_evidence():
    result = verify()
    assert result['cases'] == 3 and result['trials'] == 9
    # Model failures are retained, so this test deliberately checks consistency.
    assert 0 <= result['passed_trials'] <= result['trials']
