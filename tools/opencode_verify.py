"""Controller-side verification inside a networkless, read-only candidate container."""
import ast
import json
from pathlib import Path
import subprocess

source = Path('/workspace/src/koruapi/dashboard_logs.py')
try:
    tree = ast.parse(source.read_text())
    syntax = True
except SyntaxError:
    syntax = False
    tree = ast.Module(body=[], type_ignores=[])
command = ['python', '-m', 'pytest', '-p', 'pytest_jsonreport.plugin', '-p', 'pytest_timeout',
           '-p', 'no:cacheprovider',
           *['tests/test_dashboard_logs.py::' + name for name in
             ['TestParseNfoLine', 'TestParseAutonomousLogLine', 'TestReadRecentLogs', 'TestSseLogStream']],
           '/checks/test_stream_regression.py',
           '--timeout=5', '--json-report', '--json-report-file=/tmp/test-report.json', '-q']
run = subprocess.run(command, capture_output=True, text=True, timeout=60)
path = Path('/tmp/test-report.json')
tests = json.loads(path.read_text()) if path.exists() else {}
ruff = subprocess.run(['ruff', 'check', str(source), '--select', 'C901', '--config', 'lint.mccabe.max-complexity=15',
                       '--output-format=json', '--no-cache'], capture_output=True, text=True, timeout=10)
style = subprocess.run(['ruff', 'check', str(source), '--select', 'E9,F63,F7,F82', '--output-format=json', '--no-cache'],
                        capture_output=True, text=True, timeout=10)
functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
print(json.dumps({'syntax_passed': syntax, 'test_exit': run.returncode, 'test_summary': tests.get('summary'),
                  'tests': [{'nodeid': t['nodeid'], 'outcome': t['outcome'], 'call': t.get('call', {})} for t in tests.get('tests', [])],
                  'test_output': run.stdout + run.stderr, 'complexity_passed': ruff.returncode == 0,
                  'complexity_findings': json.loads(ruff.stdout) if ruff.stdout.startswith('[') else ruff.stdout,
                  'lint_passed': style.returncode == 0, 'lint_findings': json.loads(style.stdout) if style.stdout.startswith('[') else style.stdout,
                  'static_metrics': {'functions': len(functions), 'documented_functions': sum(ast.get_docstring(n) is not None for n in functions),
                                     'max_function_lines': max((n.end_lineno-n.lineno+1 for n in functions), default=0)}}))
