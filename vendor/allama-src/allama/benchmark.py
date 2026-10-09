"""Reproducible native Ollama profile for Allama: timings and functional checks.

Run: allama benchmark --url http://minis:11434 --models gpt-oss:20b ...
Generated code is executed only in a resource-limited, networkless container.
"""
import argparse
import hashlib
import json
import os
import random
import re
import statistics
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from allama.evaluator import CodeEvaluator
from allama.report_generator import ReportGenerator

IMAGE = 'python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f'
SYSTEM = 'Zwróć wyłącznie kompletny kod Python 3.12 w jednym bloku ```python```. Używaj wyłącznie biblioteki standardowej. Bez przykładów użycia i bez testów.'


def thinking_mode(show):
    """Choose lowest overhead advertised mode; preserve absent metadata."""
    values = show.get('thinking', {}).get('values', []) if show.get('thinking') else []
    if False in values:
        return False
    if 'low' in values:
        return 'low'
    return None


def speculative_configured(show):
    """Report configured MTP, including an embedded draft without DRAFT line."""
    count = re.search(r'^draft_num_predict\s+(\d+)\s*$', show.get('parameters') or '', re.MULTILINE)
    if count:
        return int(count.group(1)) > 0
    return any(line.startswith('DRAFT ') for line in show.get('modelfile', '').splitlines())


def payload(model, prompt, think, context=8192, limit=1024, seed=42):
    data = {'model': model, 'messages': [{'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': prompt}], 'stream': True, 'keep_alive': '30m',
            'options': {'num_ctx': context, 'num_predict': limit, 'temperature': 0, 'seed': seed}}
    if think is not None:
        data['think'] = think
    return data


def generate(session, url, data, timeout=240):
    start = time.perf_counter()
    result = {'content': '', 'thinking': '', 'first_token_s': None, 'first_answer_s': None,
              'completed': False, 'error': None, 'tokens_per_second': None}
    try:
        with session.post(url + '/api/chat', json=data, stream=True, timeout=(10, timeout)) as response:
            response.raise_for_status()
            for line in response.iter_lines(chunk_size=1):
                if time.perf_counter() - start > timeout:
                    raise TimeoutError('Total request deadline exceeded')
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get('error'):
                    raise RuntimeError(chunk['error'])
                message = chunk.get('message', {})
                content, thinking = message.get('content', ''), message.get('thinking', '')
                elapsed = time.perf_counter() - start
                if (content or thinking) and result['first_token_s'] is None:
                    result['first_token_s'] = elapsed
                if content and result['first_answer_s'] is None:
                    result['first_answer_s'] = elapsed
                result['content'] += content
                result['thinking'] += thinking
                if chunk.get('done'):
                    result['completed'] = True
                    for key in ('done_reason', 'eval_count', 'eval_duration', 'prompt_eval_count',
                                'prompt_eval_duration', 'load_duration', 'total_duration'):
                        result[key] = chunk.get(key)
                    if chunk.get('eval_duration', 0) > 0:
                        result['tokens_per_second'] = chunk.get('eval_count', 0) * 1e9 / chunk['eval_duration']
                    break
        if not result['completed']:
            result['error'] = 'Stream ended without done=true'
    except (requests.RequestException, ValueError, RuntimeError, TimeoutError) as exc:
        result['error'] = str(exc)
        result['transport_error'] = isinstance(exc, (requests.ConnectionError, requests.Timeout))
    result['wall_s'] = time.perf_counter() - start
    result['truncated'] = result.get('done_reason') == 'length'
    result['valid_answer'] = (result['completed'] and not result['error'] and
                              not result['truncated'] and bool(result['content'].strip()))
    return result


def functional_check(code, tests, image=IMAGE, timeout=60, execution_timeout=10):
    """Completion marker prevents sys.exit(0) from being mistaken for passing."""
    if not code.strip() or not CodeEvaluator().check_syntax(code):
        return {'passed': False, 'status': 'failed', 'output': 'Empty response or invalid Python syntax'}
    marker = 'ALLAMA_PASS_' + uuid.uuid4().hex
    ready = 'ALLAMA_READY_' + uuid.uuid4().hex
    name = 'allama-eval-' + uuid.uuid4().hex
    script = ('import signal, linecache, traceback\nsignal.alarm(' + repr(execution_timeout) + ')\n'
              'print(' + repr(ready) + ', flush=True)\nscope = {}\n'
              "linecache.cache['candidate.py'] = (" + repr(len(code)) + ', None, ' +
              repr(code.splitlines(keepends=True)) + ", 'candidate.py')\n"
              "linecache.cache['checks.py'] = (" + repr(len(tests)) + ', None, ' +
              repr(tests.splitlines(keepends=True)) + ", 'checks.py')\n"
              'try:\n    exec(compile(' + repr(code) + ", 'candidate.py', 'exec'), scope)\n"
              '    exec(compile(' + repr(tests) + ", 'checks.py', 'exec'), scope)\n"
              'except BaseException:\n    traceback.print_exc()\n    raise SystemExit(1)\n'
              'print(' + repr(marker) + ', flush=True)\n')
    command = ['docker', 'run', '--rm', '--name', name, '--network=none', '--read-only',
               '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=32',
               '--memory=128m', '--memory-swap=128m', '--cpus=1', '--user=65534:65534',
               '--ulimit', 'nofile=64:64', '-i', image, 'python', '-I', '-B', '-']
    try:
        proc = subprocess.run(command, input=script, text=True, capture_output=True, timeout=timeout)
        passed = proc.returncode == 0 and marker in proc.stdout.splitlines()
        started = ready in proc.stdout.splitlines()
        output = (proc.stdout.replace(marker, '').replace(ready, '') + proc.stderr).strip()
        if not passed and not output:
            output = f'Code exited with status {proc.returncode} without completing assertions'
        return {'passed': passed, 'status': 'passed' if passed else 'failed' if started else 'infra_error',
                'output': output[-4000:]}
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or b''
        if isinstance(output, bytes):
            output = output.decode(errors='replace')
        return {'passed': False, 'status': 'failed' if ready in output else 'infra_error',
                'output': 'Evaluation timeout after code started' if ready in output else 'Container startup timeout'}
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10)


def summarize(rows, metadata):
    summary = []
    for model, meta in metadata.items():
        items = [r for r in rows if r['model'] == model]
        def median(key):
            values = [r[key] for r in items if r.get(key) is not None and r.get('valid_answer')]
            return statistics.median(values) if values else None
        memory = meta.get('loaded', {})
        infra_errors = sum(r.get('evaluation', {}).get('status') == 'infra_error' for r in items)
        summary.append({'model': model, 'attempts': len(items),
                        'evaluated': len(items) - infra_errors,
                        'passed': sum(r['passed'] for r in items),
                        'errors': sum(bool(r.get('error')) for r in items),
                        'infra_errors': infra_errors,
                        'truncated': sum(r.get('truncated', False) for r in items),
                        'wall_s': median('wall_s'), 'first_answer_s': median('first_answer_s'),
                        'tokens_per_second': median('tokens_per_second'),
                        'vram_gib': memory.get('size_vram', 0) / 1024**3,
                        'size_gib': memory.get('size', 0) / 1024**3,
                        'memory_warning': meta.get('memory_warning'),
                        'driver_memory_gib': meta.get('driver_memory', {}).get('delta_gib'),
                        'speculative_decoding': meta.get('speculative_decoding', False),
                        'think': meta.get('think'),
                        'quantization': meta.get('details', {}).get('quantization_level', '?')})
    return summary


def save_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    report['summary'] = summarize(report['results'], report['models'])
    expected = len(report['tasks']) * report['settings']['repeats']
    perfect = [s for s in report['summary'] if expected and s['passed'] == expected
               and s['attempts'] == expected and s['wall_s'] is not None]
    report['fastest_complete'] = (min(perfect, key=lambda s: s['wall_s'])
                                  if perfect and report['status'] == 'complete' else None)
    report['updated_at'] = datetime.now(timezone.utc).isoformat()
    target = directory / 'results.json'
    temporary = directory / 'results.json.tmp'
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    temporary.replace(target)
    ReportGenerator({}).generate_benchmark_report(report, directory / 'index.html')


def reevaluate(directory):
    """Recheck saved answers without new inference; retain original evidence."""
    directory = Path(directory)
    report = json.loads((directory / 'results.json').read_text())
    if report['status'] == 'running':
        raise ValueError('Cannot reevaluate a running benchmark')
    tasks = {t['id']: t for t in report['tasks']}
    for row in report['results']:
        row.setdefault('original_evaluation', row['evaluation'])
        if row['valid_answer']:
            check = functional_check(row['code'], tasks[row['task']]['tests'])
            if check['status'] == 'infra_error':
                check = functional_check(row['code'], tasks[row['task']]['tests'])
            row['evaluation'] = check
            row['passed'] = check['passed']
    report['reevaluated_at'] = datetime.now(timezone.utc).isoformat()
    report['evaluation_runtime'] = os.environ.get('DOCKER_HOST', 'local Docker')
    save_report(report, directory)
    return report


def resume_report(saved, expected, tags):
    """Keep completed attempts and audit retryable connection failures."""
    for key in ('settings', 'tasks_sha256', 'planned'):
        if saved[key] != expected[key]:
            raise ValueError('Resume configuration changed: ' + key)
    if saved.get('planned_models', expected['planned_models']) != expected['planned_models']:
        raise ValueError('Resume model list changed')
    if saved.get('ollama_version') != expected.get('ollama_version'):
        raise ValueError('Resume Ollama version changed')
    for model, meta in saved['models'].items():
        if model not in expected['planned_models'] or model not in tags or meta['digest'] != tags[model]['digest']:
            raise ValueError('Resume model digest changed: ' + model)
    keys = [(r['model'], r['task'], r['repeat']) for r in saved['results']]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate trial identities in saved results')
    keep = []
    for row in saved['results']:
        if row.get('isolation_ok') is False:
            saved.setdefault('superseded_interference_attempts', []).append(row)
        elif row.get('transport_error') or 'NameResolutionError' in (row.get('error') or ''):
            saved.setdefault('superseded_transport_attempts', []).append(row)
        else:
            keep.append(row)
    saved['results'] = keep
    saved.setdefault('resumes', []).append({'at': datetime.now(timezone.utc).isoformat(),
                                           'previous_url': saved['url'], 'url': expected['url'],
                                           'previous_error': saved.pop('error', None)})
    saved.update(status='running', url=expected['url'], planned_models=expected['planned_models'])
    return saved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:11434')
    parser.add_argument('--models', nargs='+')
    parser.add_argument('--reevaluate', type=Path, help='Recheck saved answers in a finished report directory')
    parser.add_argument('--resume', action='store_true', help='Resume matching saved results; audit/retry connection errors')
    parser.add_argument('--tasks', type=Path, default=Path(__file__).with_name('benchmark_tasks.json'))
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--context', type=int, default=8192)
    parser.add_argument('--limit', type=int, default=1024)
    parser.add_argument('--output', type=Path, default=Path('benchmark-results'))
    parser.add_argument('--host-label', default='Ollama host')
    parser.add_argument('--unload-existing', action='store_true', help='Unload resident models before each model group')
    args = parser.parse_args(argv)
    if args.reevaluate:
        reevaluate(args.reevaluate)
        return
    if not args.models:
        parser.error('--models is required for inference')
    if len(args.models) != len(set(args.models)):
        parser.error('--models must not contain duplicates')
    if args.repeats < 1 or args.context < 128 or args.limit < 1:
        parser.error('repeats and limit must be positive; context >=128')
    if (args.output / 'results.json').exists() and not args.resume:
        parser.error('Output already contains results.json; use a new directory to preserve evidence')
    tasks = json.loads(args.tasks.read_text())
    if not tasks or len({t['id'] for t in tasks}) != len(tasks):
        parser.error('Tasks must be non-empty with unique ids')
    # Fail before inference if the evaluation runtime is unavailable.
    probe = functional_check('def answer(): return 42', 'assert answer() == 42')
    if not probe['passed']:
        raise RuntimeError('Docker evaluator unavailable: ' + probe['output'])
    session = requests.Session()
    session.trust_env = False
    url = args.url.rstrip('/')
    def get(path):
        response = session.get(url + path, timeout=30); response.raise_for_status(); return response.json()
    def post(path, data):
        response = session.post(url + path, json=data, timeout=120); response.raise_for_status(); return response.json()
    tags = {m['name']: m for m in get('/api/tags')['models']}
    missing = [m for m in args.models if m not in tags]
    if missing:
        parser.error('Models not installed: ' + ', '.join(missing))
    report = {'schema': 'allama.ollama-benchmark/v1', 'status': 'running',
              'started_at': datetime.now(timezone.utc).isoformat(), 'host': args.host_label,
              'ollama_version': get('/api/version'), 'url': url, 'models': {}, 'results': [],
              'planned': len(args.models) * len(tasks) * args.repeats,
              'planned_models': args.models,
              'settings': {'context': args.context, 'limit': args.limit, 'temperature': 0,
                           'repeats': args.repeats, 'seed': 42, 'image': IMAGE, 'system': SYSTEM},
              'tasks_sha256': hashlib.sha256(args.tasks.read_bytes()).hexdigest(), 'tasks': tasks}
    if args.resume:
        saved = json.loads((args.output / 'results.json').read_text())
        if saved['status'] == 'running':
            raise ValueError('Refusing to resume a report still marked running')
        report = resume_report(saved, report, tags)
    completed = {(r['model'], r['task'], r['repeat']) for r in report['results']}
    save_report(report, args.output)
    try:
        for model in args.models:
            if all((model, task['id'], repeat + 1) in completed
                   for task in tasks for repeat in range(args.repeats)):
                continue
            resident = get('/api/ps')['models']
            if resident and not args.unload_existing:
                raise RuntimeError('Resident models found; use --unload-existing for isolated measurements')
            for active in resident:
                post('/api/generate', {'model': active['name'], 'keep_alive': 0})
            show = post('/api/show', {'model': model})
            think = thinking_mode(show)
            meta = {'digest': tags[model]['digest'], 'details': show['details'], 'think': think,
                    'parameters': show.get('parameters'),
                    'speculative_decoding': speculative_configured(show),
                    'thinking_metadata': show.get('thinking'), 'capabilities': show.get('capabilities')}
            if model in report['models']:
                meta['previous_loads'] = [report['models'][model]]
            report['models'][model] = meta
            print(f'Loading {model}, think={think!r}', flush=True)
            warm = generate(session, url, payload(model, 'Odpowiedz: OK', think, args.context, 32))
            meta['warmup'] = warm
            if not warm['completed'] or warm['error']:
                raise RuntimeError('Warm-up failed: ' + str(warm['error']))
            loaded = get('/api/ps')['models']
            if len(loaded) != 1 or loaded[0]['name'] != model:
                raise RuntimeError('Model isolation failed: ' + str([m['name'] for m in loaded]))
            meta['loaded'] = loaded[0]
            if meta['speculative_decoding'] and loaded[0].get('size', 0) < tags[model]['size'] / 2:
                meta['memory_warning'] = 'Ollama reports less than half the model file size with a draft model active; verify server buffer logs before comparing memory.'
            for repeat in range(args.repeats):
                ordered = list(tasks)
                random.Random(42 + repeat).shuffle(ordered)
                for task in ordered:
                    if (model, task['id'], repeat + 1) in completed:
                        continue
                    before = get('/api/ps')['models']
                    if [m['name'] for m in before] != [model]:
                        raise RuntimeError('Other resident models detected before trial; wait for an idle server and resume')
                    data = payload(model, task['prompt'], think, args.context, args.limit)
                    row = generate(session, url, data)
                    after = get('/api/ps')['models']
                    row['resident_before'] = [m['name'] for m in before]
                    row['resident_after'] = [m['name'] for m in after]
                    row['isolation_ok'] = row['resident_after'] == [model]
                    row.update(model=model, task=task['id'], repeat=repeat + 1, request=data)
                    code = CodeEvaluator().extract_python_code(row['content'])
                    check = functional_check(code, task['tests']) if row['valid_answer'] else {'passed': False, 'output': 'Incomplete or empty answer'}
                    row.update(passed=check['passed'], evaluation=check, code=code)
                    report['results'].append(row)
                    save_report(report, args.output)
                    print(f"{len(report['results'])}/{report['planned']} {model} {task['id']} "
                          f"pass={row['passed']} time={row['wall_s']:.2f}s rate={row['tokens_per_second']}", flush=True)
                    if row.get('transport_error'):
                        raise RuntimeError('Connection failed; results saved. Restore endpoint and use --resume.')
                    if not row['isolation_ok']:
                        raise RuntimeError('Other models loaded during trial; attempt retained for audit. Wait and resume.')
            post('/api/generate', {'model': model, 'keep_alive': 0})
        report['status'] = 'complete'
    except BaseException as exc:
        report['status'] = 'interrupted'
        report['error'] = str(exc)
        raise
    finally:
        save_report(report, args.output)
    print('Report: ' + str(args.output / 'index.html'))


if __name__ == '__main__':
    main()
