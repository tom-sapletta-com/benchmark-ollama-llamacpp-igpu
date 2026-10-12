"""Measure three coding use cases on an existing Ollama server, without service changes."""
import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path
import random
import subprocess
import time

import requests
from quality_cases import CASES, prompt

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f'
SAFE_IMPORTS = {'__future__', 'json', 'decimal', 'collections', 'math', 'typing', 'dataclasses', 'copy', 'functools', 're'}
# Resource and network isolation is enforced by Docker. AST checks also reject
# process/file access and test-framework imports; they are not a security proof.
BOOTSTRAP = '''import json, pathlib, sys, unittest, signal, resource
signal.alarm(20)
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
payload = json.load(sys.stdin)
for name, code in payload['files'].items():
    pathlib.Path('/work', name).write_text(code)
sys.path.insert(0, '/work')
class Results(unittest.TestResult):
    def __init__(self):
        super().__init__(); self.rows = []; self.current = None
    def startTest(self, test):
        super().startTest(test); self.current = {'id': test.id(), 'passed': True, 'errors': []}
    def addError(self, test, err):
        super().addError(test, err); self.current['passed'] = False
        self.current['errors'].append(self._exc_info_to_string(err, test))
    def addFailure(self, test, err):
        super().addFailure(test, err); self.current['passed'] = False
        self.current['errors'].append(self._exc_info_to_string(err, test))
    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err:
            self.current['passed'] = False; self.current['errors'].append(self._exc_info_to_string(err, test))
    def stopTest(self, test):
        self.rows.append(self.current); super().stopTest(test)
namespace = {'__name__': 'withheld_tests'}
result = Results()
try:
    exec(compile(payload['tests'], '<withheld-tests>', 'exec'), namespace)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(namespace[group])
                               for group in ['Functional', 'Regression'])
    suite.run(result)
    output = {'tests': result.rows, 'status': 'complete'}
except BaseException as exc:
    output = {'tests': result.rows, 'status': 'candidate_error', 'error': type(exc).__name__ + ': ' + str(exc)}
print('QUALITY_RESULT:' + json.dumps(output))
'''


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def test_ids(case):
    tree = ast.parse(case['tests'])
    return [f'withheld_tests.{node.name}.{fn.name}' for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name in ('Functional', 'Regression')
            for fn in node.body if isinstance(fn, ast.FunctionDef) and fn.name.startswith('test_')]


def parse_files(content, case):
    value = json.loads(content)
    if not isinstance(value, dict) or set(value) != {'files'}:
        raise ValueError('Expected exactly the JSON key files')
    files = value['files']
    if not isinstance(files, dict) or set(files) != set(case['before']):
        raise ValueError('Required file set does not match; no extra or omitted paths permitted')
    if not all(isinstance(code, str) and 0 < len(code) <= 100_000 for code in files.values()):
        raise ValueError('Invalid or oversized source string')
    return files


def static_review(files):
    results, blocked = {}, []
    own_modules = {Path(name).stem for name in files}
    for name, code in files.items():
        tree = ast.parse(code, filename=name)
        nodes = list(ast.walk(tree))
        functions = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        alerts = []
        for n in nodes:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                modules = ([a.name.split('.')[0] for a in n.names] if isinstance(n, ast.Import)
                           else [(n.module or '').split('.')[0]])
                if any(module not in SAFE_IMPORTS | own_modules for module in modules):
                    blocked.append(name + ': prohibited import')
                if isinstance(n, ast.ImportFrom) and any(a.name == '*' for a in n.names):
                    alerts.append('wildcard import')
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {
                'eval', 'exec', 'open', 'compile', '__import__', 'breakpoint', 'globals', 'locals', 'getattr', 'setattr'}:
                blocked.append(name + ': prohibited call ' + n.func.id)
            if isinstance(n, ast.Attribute) and n.attr.startswith('__'):
                blocked.append(name + ': prohibited dunder attribute')
            if isinstance(n, ast.ExceptHandler) and (n.type is None or isinstance(n.type, ast.Name) and n.type.id in {'Exception', 'BaseException'}):
                alerts.append('broad exception handler')
        spans = [f.end_lineno - f.lineno + 1 for f in functions]
        if any(span > 40 for span in spans): alerts.append('function longer than 40 lines')
        results[name] = {
            'lines': len(code.splitlines()), 'functions': len(functions),
            'max_function_lines': max(spans, default=0),
            'branch_nodes': sum(isinstance(n, (ast.If, ast.For, ast.While, ast.Try, ast.BoolOp)) for n in nodes),
            'documented_functions': sum(ast.get_docstring(f) is not None for f in functions),
            'functions_with_any_annotation': sum(f.returns is not None or any(a.annotation is not None for a in f.args.args) for f in functions),
            'alerts': alerts,
        }
    return {'files': results, 'blocked': sorted(set(blocked))}


def sandbox(files, case):
    expected = test_ids(case)
    review = static_review(files)
    if review['blocked']:
        return {'status': 'policy_rejected', 'error': review['blocked'], 'tests': [], 'expected_tests': expected}
    command = ['docker', 'run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL',
               '--security-opt=no-new-privileges', '--user=65534:65534', '--pids-limit=64',
               '--memory=256m', '--memory-swap=256m', '--cpus=1',
               '--tmpfs=/work:rw,nosuid,nodev,noexec,size=16m,mode=1777',
               '--workdir=/work', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-i', IMAGE,
               'python', '-I', '-c', BOOTSTRAP]
    try:
        run = subprocess.run(command, input=json.dumps({'files': files, 'tests': case['tests']}),
                             text=True, capture_output=True, timeout=45)
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'tests': [], 'expected_tests': expected}
    if run.returncode in (125, 126, 127) or run.returncode and run.returncode < 128:
        raise RuntimeError('Sandbox infrastructure failed: ' + run.stderr[-3000:])
    if run.returncode:
        return {'status': 'resource_limit', 'error': 'Container exit ' + str(run.returncode),
                'tests': [], 'expected_tests': expected}
    lines = [line for line in run.stdout.splitlines() if line.startswith('QUALITY_RESULT:')]
    if not lines:
        return {'status': 'candidate_error', 'error': run.stdout[-3000:] + run.stderr[-3000:], 'tests': [], 'expected_tests': expected}
    result = json.loads(lines[-1].split(':', 1)[1])
    if result['status'] == 'complete' and sorted(r['id'] for r in result['tests']) != sorted(expected):
        result.update(status='candidate_error', error='Unexpected test coverage')
    result['expected_tests'] = expected
    return result


def totals(evaluation, group):
    expected = [name for name in evaluation['expected_tests'] if '.' + group + '.' in name]
    passed = sum(row['passed'] for row in evaluation['tests'] if row['id'] in expected)
    return {'passed': passed, 'total': len(expected)}


def generate(url, model, case, predict):
    request = {'model': model, 'messages': [{'role': 'user', 'content': prompt(case)}],
               'stream': True, 'think': 'low', 'format': 'json', 'keep_alive': -1,
               'options': {'temperature': 0, 'seed': 42, 'num_ctx': 16384, 'num_predict': predict,
                           'num_thread': 8, 'num_batch': 512, 'num_gpu': 999}}
    started = time.perf_counter()
    content, thinking, finish, first, chunks = [], [], None, None, 0
    with requests.post(url.rstrip('/') + '/api/chat', json=request, stream=True, timeout=(10, 300)) as response:
        response.raise_for_status()
        for raw in response.iter_lines():
            if not raw: continue
            part = json.loads(raw)
            if part.get('error'): raise RuntimeError(part['error'])
            chunks += 1
            message = part.get('message', {})
            content.append(message.get('content', ''))
            thinking.append(message.get('thinking', ''))
            if first is None and (message.get('content') or message.get('thinking')):
                first = time.perf_counter() - started
            if part.get('done'): finish = part
    if finish is None: raise RuntimeError('Stream ended without final event')
    return {'request': request, 'prompt_sha256': digest(prompt(case)), 'content': ''.join(content),
            'thinking': ''.join(thinking), 'final_event': finish, 'stream_chunks': chunks,
            'wall_seconds': time.perf_counter() - started, 'ttft_seconds': first,
            'truncated': finish.get('done_reason') == 'length',
            'generated_tokens': finish.get('eval_count'),
            'tokens_per_second': finish['eval_count'] / (finish['eval_duration'] / 1e9) if finish.get('eval_duration') else None}


def evaluate(row, case):
    try:
        files = parse_files(row['content'], case)
        row['files'] = files
        changed = [name for name in files if files[name] != case['before'][name]]
        row['scope'] = {'allowed_files': list(case['before']), 'changed_files': changed,
                        'passed': set(changed) == set(case['before'])}
        row['diff'] = ''.join(''.join(difflib.unified_diff(case['before'][name].splitlines(True),
                          code.splitlines(True), fromfile='before/' + name, tofile='after/' + name))
                          for name, code in files.items())
        row['static_review'] = static_review(files)
        row['evaluation'] = sandbox(files, case) if not row['truncated'] else {
            'status': 'truncated', 'tests': [], 'expected_tests': test_ids(case)}
    except SyntaxError as exc:
        row['syntax_error'] = str(exc)
        row['evaluation'] = {'status': 'syntax_error', 'error': str(exc), 'tests': [], 'expected_tests': test_ids(case)}
    except ValueError as exc:
        row['format_error'] = str(exc)
        row['scope'] = {'passed': False, 'allowed_files': list(case['before']), 'changed_files': []}
        row['evaluation'] = {'status': 'invalid_output', 'error': str(exc), 'tests': [], 'expected_tests': test_ids(case)}
    row['correctness'] = totals(row['evaluation'], 'Functional')
    row['regression'] = totals(row['evaluation'], 'Regression')
    row['passed'] = (not row['truncated'] and row['scope']['passed'] and row['evaluation']['status'] == 'complete'
                     and all(row[group]['passed'] == row[group]['total'] for group in ['correctness', 'regression']))


def save(report, output):
    report['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    report['summary'] = []
    for case in report['cases']:
        rows = [row for row in report['results'] if row['case'] == case['id']]
        report['summary'].append({
            'case': case['id'], 'title': case['title'], 'trials': len(rows), 'passed_trials': sum(row['passed'] for row in rows),
            'functional_passed': sum(row['correctness']['passed'] for row in rows),
            'functional_total': sum(row['correctness']['total'] for row in rows),
            'regression_passed': sum(row['regression']['passed'] for row in rows),
            'regression_total': sum(row['regression']['total'] for row in rows),
            'executed_test_methods': sum(len(row['evaluation']['tests']) for row in rows),
            'failed_test_ids': sorted({test['id'] for row in rows for test in row['evaluation']['tests'] if not test['passed']}),
            'nonexecuted_statuses': sorted({row['evaluation']['status'] for row in rows if row['evaluation']['status'] != 'complete'}),
        })
    target = output / 'results.json'
    temp = target.with_suffix('.tmp'); temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n'); temp.replace(target)
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=True)
    page = env.get_template('quality.html').render(report=report)
    temp = output / 'index.html.tmp'; temp.write_text(page); temp.replace(output / 'index.html')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--model', default='gpt-oss-minis-code:20b')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, choices=[1, 2, 3], default=3)
    parser.add_argument('--num-predict', type=int, default=8192)
    args = parser.parse_args(argv)
    if args.output.exists(): parser.error('Choose a new output directory; previous evidence is preserved')
    if not 1024 <= args.num_predict <= 8192: parser.error('num-predict must be between 1024 and 8192')
    args.output.mkdir(parents=True)
    snapshot = json.dumps(CASES, ensure_ascii=False, indent=2) + '\n'
    (args.output / 'cases.json').write_text(snapshot)
    report = {'schema': 'igpu-coding-quality/v1', 'status': 'running', 'model': args.model,
              'runtime': 'Ollama', 'cases_sha256': digest(snapshot), 'results': [], 'controls': [],
              'cases': [{'id': c['id'], 'title': c['title'], 'kind': c['kind'], 'files': list(c['before']), 'spec': c['spec']} for c in CASES],
              'settings': {'repeats': args.repeats, 'num_predict': args.num_predict, 'seed': 42, 'temperature': 0,
                           'think': 'low', 'num_ctx': 16384, 'sandbox_image': IMAGE},
              'method': 'One current production Ollama model; three fixed tasks, repeated without repair feedback. '
                        '8 withheld functional + 4 compatibility tests per task; subtests counted within their parent method. '
                        'No overall subjective quality score. Static metrics are indicators, not proof of maintainability. '
                        'Repeated deterministic prompts measure repeatability, not nine independent tasks. '
                        'Tests run in a resource-limited networkless container; no engine ranking or energy measurement.',
              'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    try:
        for route in ['version', 'ps']:
            response = requests.get(args.url.rstrip('/') + '/api/' + route, timeout=15)
            response.raise_for_status(); report['observed_' + route + '_before'] = response.json()
        show = requests.post(args.url.rstrip('/') + '/api/show', json={'model': args.model}, timeout=15)
        show.raise_for_status(); details = show.json()
        report['model_details'] = {key: details.get(key) for key in ['details', 'parameters', 'model_info']}
        save(report, args.output)
        for case in CASES:
            before, reference = sandbox(case['before'], case), sandbox(case['reference'], case)
            if any(not test['passed'] for test in reference['tests']) or reference['status'] != 'complete':
                raise RuntimeError('Reference control failed: ' + case['id'] + ': ' + json.dumps(reference))
            if all(test['passed'] for test in before['tests']) and before['status'] == 'complete':
                raise RuntimeError('Baseline unexpectedly passed: ' + case['id'])
            control = {'case': case['id'], 'baseline': before, 'reference': reference, 'ablations': []}
            if case['kind'] == 'three_file_fix':
                for name in case['before']:
                    files = dict(case['reference']); files[name] = case['before'][name]
                    evaluation = sandbox(files, case)
                    assert evaluation['status'] != 'complete' or not all(test['passed'] for test in evaluation['tests']), name
                    control['ablations'].append({'restored_buggy_file': name, 'evaluation': evaluation})
            report['controls'].append(control); save(report, args.output)
            print('CONTROLS PASS', case['id'], flush=True)
        for repeat in range(1, args.repeats + 1):
            cases = list(CASES); random.Random(42 + repeat).shuffle(cases)
            for case in cases:
                row = generate(args.url, args.model, case, args.num_predict)
                row.update(case=case['id'], repeat=repeat)
                evaluate(row, case)
                report['results'].append(row); save(report, args.output)
                print(case['id'], repeat, 'PASS' if row['passed'] else 'FAIL', row['correctness'], row['regression'], flush=True)
        response = requests.get(args.url.rstrip('/') + '/api/ps', timeout=15)
        response.raise_for_status(); report['observed_ps_after'] = response.json()
        report['status'] = 'complete'
    except BaseException as exc:
        report.update(status='interrupted', error=str(exc))
        raise
    finally:
        save(report, args.output)
    # A complete benchmark may contain model failures: do not discard them.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
