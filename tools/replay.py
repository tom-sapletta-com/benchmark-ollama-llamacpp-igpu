"""Replay archived prompts against one manually prepared runtime; no service changes."""
import argparse
import json
import pathlib
import random
import socket
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/allama-src'))
from allama.benchmark import functional_check, summarize
from allama.evaluator import CodeEvaluator
from allama.report_generator import ReportGenerator
from jinja2 import ChoiceLoader, FileSystemLoader
import native_stream


def save(report, output):
    output.mkdir(parents=True, exist_ok=True)
    report['summary'] = summarize(report['results'], report['models'])
    report['context_summary'] = []
    report['fastest_complete'] = None
    report['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    target = output / 'results.json'
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(target)
    # Replay reports intentionally have their own simple presentation, without
    # copying the archived claim that all four profiles were measured here.
    generator = ReportGenerator({})
    generator.env.loader = ChoiceLoader([FileSystemLoader(ROOT / 'templates'), generator.env.loader])
    text = generator.env.overlay(autoescape=True).get_template('replay.html').render(report=report)
    page = output / 'index.html.tmp'
    page.write_text(text)
    page.replace(output / 'index.html')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, choices=['llama', 'ollama'])
    parser.add_argument('--variant', required=True, choices=['q8', 'bf16'])
    parser.add_argument('--url', required=True)
    parser.add_argument('--model', required=True, help='Actual server alias; no model is created or downloaded')
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--repeats', type=int, choices=[1, 2, 3], default=3)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Output already exists; choose a new directory to preserve earlier evidence')
    args.output.mkdir(parents=True, exist_ok=False)
    native_stream.BASE = args.url.rstrip('/')
    native_stream.MODEL = args.model
    prompts = json.loads((ROOT / 'results/minis-20261009/raw-prompts.json').read_text())
    original = json.loads((ROOT / 'results/minis-20261009/results.json').read_text())
    name = args.runtime + ' / MXFP4 + ' + args.variant.upper()
    report = {'schema': 'igpu-replay/v1', 'status': 'running', 'results': [], 'context_results': [],
        'models': {name: {'details': {'quantization_level': args.variant.upper()}, 'loaded': {},
                         'think': 'low', 'speculative_decoding': False}},
        'host': socket.gethostname() + ' (replay; hardware and weights not independently observed)',
        'ollama_version': {'version': 'not observed'}, 'tasks': original['tasks'],
        'settings': {**original['settings'], 'repeats': args.repeats},
        'planned': 6 * args.repeats, 'tasks_sha256': original['tasks_sha256'],
        'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'method': 'One manually prepared runtime. Archived prompts and sandboxed tests reused. '
                  'Model variant declared by caller; weights, GPU allocation, reload order and '
                  'other GPU workloads are not verified by this replay. No service control.'}
    endpoint = 'ollama' if args.runtime == 'ollama' else 'q8'
    try:
        warm_prompt = prompts['1/unique_ordered']['prompt'].replace(original['tasks'][0]['prompt'], 'Odpowiedz wyłącznie OK.')
        warm = native_stream.generate(endpoint, warm_prompt, 128)
        if not warm['valid_answer']:
            raise RuntimeError('Warm-up failed: ' + str(warm['error']))
        report['warmup'] = warm
        for rep in range(1, args.repeats + 1):
            tasks = list(original['tasks'])
            random.Random(42 + rep).shuffle(tasks)
            for task in tasks:
                row = native_stream.generate(endpoint, prompts[str(rep) + '/' + task['id']]['prompt'])
                row.update(model=name, profile=args.runtime + '_' + args.variant, task=task['id'], repeat=rep)
                row['code'] = CodeEvaluator().extract_python_code(row['content'])
                row['evaluation'] = functional_check(row['code'], task['tests']) if row['valid_answer'] else {
                    'passed': False, 'status': 'failed', 'output': 'Incomplete answer'}
                row['passed'] = row['evaluation']['passed']
                report['results'].append(row)
                save(report, args.output)
                print(task['id'], 'PASS' if row['passed'] else 'FAIL', flush=True)
                if row['error'] or row['evaluation']['status'] == 'infra_error':
                    raise RuntimeError('Transport or sandbox infrastructure failure: ' + str(row['error'] or row['evaluation']))
            row = native_stream.generate(endpoint, prompts[str(rep) + '/context_4k']['prompt'], 128)
            row.update(model=name, profile=args.runtime + '_' + args.variant, task='context_4k', repeat=rep,
                       passed=row['valid_answer'] and row['content'].strip() == 'GOTOWE')
            report['context_results'].append(row)
            if row['error']:
                raise RuntimeError(row['error'])
        report['status'] = 'complete'
    except BaseException as exc:
        report['status'] = 'interrupted'
        report['error'] = str(exc)
        raise
    finally:
        save(report, args.output)
    return 0 if all(row['passed'] for row in report['results'] + report['context_results']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
