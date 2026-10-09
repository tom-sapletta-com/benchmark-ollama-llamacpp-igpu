"""Operational A/B profile using immutable Allama's tasks, evaluator and report.

No repository writer or expired lease takeover. All mutations are confined to
this request's external profile, owned benchmark units and new report directory.
"""
import hashlib
import json
import os
import pathlib
import random
import re
import statistics
import subprocess
import sys
import time

import requests
from jinja2 import ChoiceLoader, FileSystemLoader

STATE = pathlib.Path(__file__).parent
SOURCE = STATE / 'allama-source'
sys.path.insert(0, str(SOURCE))
from allama.benchmark import functional_check, summarize
from allama.evaluator import CodeEvaluator
from allama.report_generator import ReportGenerator

REMOTE = 'tom@192.168.188.170'
BASE = 'http://127.0.0.1:11437'
MODEL = 'gpt-oss-minis-code:20b'
OUTPUT = STATE / 'report'
PROFILES = {
    'q8': {'name': 'llama.cpp / MXFP4 + Q8', 'quantization': 'MXFP4 experts + Q8_0 attention/embedding', 'runtime': 'llama.cpp b11429 Vulkan'},
    'bf16': {'name': 'llama.cpp / MXFP4 + BF16', 'quantization': 'MXFP4 experts + BF16 attention/embedding', 'runtime': 'llama.cpp b11429 Vulkan'},
    'ollama': {'name': 'Ollama / MXFP4 + BF16', 'quantization': 'MXFP4 experts + BF16 attention/embedding', 'runtime': 'Ollama 0.35.1 Vulkan'},
}
SESSION = requests.Session()
SESSION.trust_env = False


def remote(code):
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', REMOTE, 'python3', '-'],
                            input=code, capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise RuntimeError('Remote probe failed: ' + result.stderr[-1200:])
    return json.loads(result.stdout)


def observation():
    return remote("""import pathlib,json,subprocess,time
d=pathlib.Path('/sys/class/drm/card1/device')
r={k:int((d/k).read_text()) for k in ['mem_info_vram_used','mem_info_gtt_used','gpu_busy_percent']}
r['time']=time.time();r['loadavg']=pathlib.Path('/proc/loadavg').read_text().strip()
r['cpu_temperature_c']=None
for p in pathlib.Path('/sys/class/hwmon').glob('hwmon*'):
 if (p/'name').exists() and (p/'name').read_text().strip()=='k10temp':
  r['cpu_temperature_c']=int((p/'temp1_input').read_text())/1000
r['production_state']=subprocess.run(['systemctl','is-active','llamacpp-gpt-oss.service'],capture_output=True,text=True).stdout.strip()
r['benchmark_state']=subprocess.run(['systemctl','is-active','llamacpp-ab-runtime.service'],capture_output=True,text=True).stdout.strip()
r['ollama_state']=subprocess.run(['systemctl','is-active','ollama.service'],capture_output=True,text=True).stdout.strip()
print(json.dumps(r))
""")


def switch(profile):
    t = time.perf_counter()
    cmd = ['ssh', '-o', 'BatchMode=yes', REMOTE, 'sudo', '/usr/bin/python3',
           '/usr/local/lib/minis-llamacpp-ab-20261009/switch.py', profile]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError('Runtime switch failed: ' + r.stderr[-1200:])
    return {'profile': profile, 'seconds': time.perf_counter()-t,
            'stdout': r.stdout, 'stderr': r.stderr}


def ready(profile):
    path = '/api/version' if profile == 'ollama' else '/health'
    for _ in range(90):
        try:
            r = SESSION.get(BASE + path, timeout=2)
            if r.ok and (profile == 'ollama' or r.json().get('status') == 'ok'):
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError('Runtime did not become ready: ' + profile)


def split_answer(raw, thinking=''):
    final = '<|channel|>final<|message|>'
    if final in raw:
        analysis, answer = raw.rsplit(final, 1)
        return re.sub(r'<\|[^|]*\|>', '', answer).strip(), analysis
    if '<|channel|>analysis' in raw or raw.lstrip().startswith('<|'):
        return '', raw
    return re.sub(r'<\|[^|]*\|>', '', raw).strip(), thinking


def generate(profile, prompt, limit=1024):
    common = {'temperature': 0, 'seed': 42, 'top_k': 40, 'top_p': 0.95,
              'min_p': 0, 'repeat_penalty': 1.0, 'repeat_last_n': 64}
    if profile == 'ollama':
        data = {'model': MODEL, 'prompt': prompt, 'raw': True, 'stream': True,
                'keep_alive': '30m', 'options': {**common, 'num_ctx': 16384,
                'num_predict': limit, 'num_thread': 8, 'num_batch': 512, 'num_gpu': 999}}
        endpoint = '/api/generate'
    else:
        data = {**common, 'prompt': prompt, 'n_predict': limit, 'stream': True,
                'cache_prompt': False, 'return_tokens': True}
        endpoint = '/completion'
    result = {'raw_content': '', 'content': '', 'thinking': '', 'first_token_s': None,
              'first_answer_s': None, 'completed': False, 'error': None,
              'tokens_per_second': None, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
              'request': data}
    start = time.perf_counter()
    final_chunk = {}
    try:
        with SESSION.post(BASE + endpoint, json=data, stream=True, timeout=(10, 180)) as response:
            response.raise_for_status()
            for line in response.iter_lines(chunk_size=1):
                if time.perf_counter() - start > 180:
                    raise TimeoutError('Total request deadline exceeded')
                if not line or line.startswith(b':'):
                    continue
                if profile != 'ollama':
                    if not line.startswith(b'data: '):
                        continue
                    line = line[6:]
                    if line == b'[DONE]':
                        break
                chunk = json.loads(line)
                if chunk.get('error'):
                    raise RuntimeError(str(chunk['error']))
                text = chunk.get('response', '') if profile == 'ollama' else chunk.get('content', '')
                thought = chunk.get('thinking', '') if profile == 'ollama' else ''
                elapsed = time.perf_counter() - start
                if (text or thought) and result['first_token_s'] is None:
                    result['first_token_s'] = elapsed
                result['raw_content'] += text
                result['thinking'] += thought
                answer, _ = split_answer(result['raw_content'], result['thinking'])
                if answer and result['first_answer_s'] is None:
                    # Native completion emits channel markers first. Do not count
                    # partial metadata as a user-visible final answer.
                    if profile == 'ollama' or '<|channel|>final<|message|>' in result['raw_content']:
                        result['first_answer_s'] = elapsed
                if chunk.get('done') if profile == 'ollama' else chunk.get('stop'):
                    result['completed'] = True
                    final_chunk = chunk
                    break
        if not result['completed']:
            raise RuntimeError('Stream ended without a completion marker')
        result['content'], result['thinking'] = split_answer(result['raw_content'], result['thinking'])
        if profile == 'ollama':
            for k in ['eval_count', 'eval_duration', 'prompt_eval_count', 'prompt_eval_duration',
                      'load_duration', 'total_duration', 'done_reason']:
                result[k] = final_chunk.get(k)
            if final_chunk.get('eval_duration', 0):
                result['tokens_per_second'] = final_chunk['eval_count'] * 1e9 / final_chunk['eval_duration']
            result['truncated'] = result.get('done_reason') == 'length'
            context = final_chunk.get('context')
            if context is not None:
                result['returned_context_sha256'] = hashlib.sha256(json.dumps(context).encode()).hexdigest()
        else:
            timings = final_chunk.get('timings', {})
            result.update(timings=timings, eval_count=timings.get('predicted_n'),
                          eval_duration=timings.get('predicted_ms', 0)*1e6,
                          prompt_eval_count=timings.get('prompt_n'),
                          prompt_eval_duration=timings.get('prompt_ms', 0)*1e6,
                          tokens_per_second=timings.get('predicted_per_second'),
                          done_reason=final_chunk.get('stop_type'),
                          truncated=final_chunk.get('stop_type') == 'limit' or bool(final_chunk.get('truncated')))
            result['tokens_cached'] = final_chunk.get('tokens_cached')
        result['final_chunk'] = final_chunk
    except (requests.RequestException, ValueError, RuntimeError, TimeoutError) as exc:
        result['error'] = str(exc)
    result['wall_s'] = time.perf_counter() - start
    result['valid_answer'] = (result['completed'] and not result['error'] and not result.get('truncated')
                              and bool(result['content'].strip()))
    return result


def render(report):
    OUTPUT.mkdir(exist_ok=True)
    report['summary'] = summarize(report['results'], report['models'])
    for summary in report['summary']:
        rows = [x for x in report['results'] if x['model'] == summary['model'] and x['valid_answer']]
        summary['first_token_s'] = statistics.median(x['first_token_s'] for x in rows) if rows else None
        vrams = [(x['memory_after']['mem_info_vram_used'] - x['idle_memory']['mem_info_vram_used'])/1024**3
                 for x in rows]
        summary['vram_gib'] = statistics.median(vrams) if vrams else None
        summary['gtt_gib'] = statistics.median((x['memory_after']['mem_info_gtt_used'] -
            x['idle_memory']['mem_info_gtt_used'])/1024**3 for x in rows) if rows else None
    report['context_summary'] = []
    for profile in PROFILES.values():
        rows = [x for x in report['context_results'] if x['model'] == profile['name'] and x['valid_answer']]
        def median(k):
            return statistics.median(x[k] for x in rows) if rows else None
        report['context_summary'].append({'model': profile['name'], 'attempts': len(rows),
            'first_token_s': median('first_token_s'), 'wall_s': median('wall_s'),
            'prompt_tokens': median('expected_prompt_tokens'), 'passed': sum(x['passed'] for x in rows)})
    perfect = [x for x in report['summary'] if x['attempts']==18 and x['passed']==18]
    report['fastest_complete'] = min(perfect,key=lambda x:x['wall_s']) if perfect and report['status']=='complete' else None
    report['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    temporary = OUTPUT / 'results.json.tmp'
    temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(OUTPUT/'results.json')
    generator = ReportGenerator({})
    generator.env.loader = ChoiceLoader([FileSystemLoader(STATE/'templates'),generator.env.loader])
    generator.generate_benchmark_report(report,OUTPUT/'index.html')


def main():
    tasks_path = SOURCE/'allama/benchmark_tasks.json'
    tasks = json.loads(tasks_path.read_text())
    prompts = json.loads((STATE/'raw-prompts.json').read_text())
    report = {'schema':'allama.runtime-comparison/v1','status':'running',
        'started_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'host':'minis · Ryzen 9 7940HS · Radeon 780M · 64GB RAM / 16GiB iGPU',
        'ollama_version':{'version':'0.35.1'},'url':BASE,'models':{},'results':[],
        'context_results':[],'loads':[],'tasks':tasks,'planned':54,
        'settings':{'context':16384,'limit':1024,'temperature':0,'repeats':3,'seed':42,
            'threads':8,'batch_size':512,'llamacpp_ubatch_size':128,'thinking':'low',
            'ollama_kv_type':'f16','llamacpp_kv_type':'f16','parallel':1},
        'tasks_sha256':hashlib.sha256(tasks_path.read_bytes()).hexdigest(),
        'provenance':{'ticket':'PLF-17295','allama_head':'4e3578ae9e4b616cc1900c5ffd872954c12dcb77',
            'tensor_parity_control':json.loads((STATE/'control-model-verification.json').read_text()),
            'source_writer':None,'adapter_scope':'external operational profile; frozen source preserved'},
        'method':'Same raw Harmony bytes and low reasoning, seeded greedy sampling, no overlapping requests; three Latin-square runtime orders. Q8 vs BF16 compares deployed profiles; BF16 vs BF16 controls all tensor bytes. Engine-internal kernel/microbatch and floating point implementations still differ. Long-context timings are kept separate. No energy measurement.'}
    for profile, meta in PROFILES.items():
        report['models'][meta['name']]={'profile':profile,'runtime':meta['runtime'],'think':'low',
            'speculative_decoding':False,'details':{'quantization_level':meta['quantization']},
            'loaded':{},'memory_warning':'GPU column is driver VRAM increase over unloaded baseline; GTT is reported separately. File size is not total RAM use.'}
    if (OUTPUT/'results.json').exists():
        saved=json.loads((OUTPUT/'results.json').read_text())
        assert saved['status']=='interrupted', 'Only a stopped interrupted profile may resume'
        for key in ['settings','tasks_sha256','planned','schema']:
            assert saved[key]==report[key], 'Resume configuration changed: '+key
        assert list(saved['models'])==list(report['models']), 'Resume profile list changed'
        ids=[(x['profile'],x['task'],x['repeat']) for x in saved['results']]
        assert len(ids)==len(set(ids)), 'Duplicate trial identities'
        saved.setdefault('resumes',[]).append({'at':time.time(),'previous_error':saved.pop('error',None),
            'reason':'Temporary Ollama dropin precedence fixed; original prompts and inference settings unchanged',
            'previous_restoration':saved.pop('restoration',None)})
        report=saved;report['status']='running'
    completed={(x['profile'],x['task'],x['repeat']) for x in report['results']}
    completed_context={(x['profile'],x['repeat']) for x in report['context_results']}
    render(report)
    started=time.perf_counter()
    try:
        for rep, order in enumerate([['q8','bf16','ollama'],['ollama','q8','bf16'],['bf16','ollama','q8']],1):
            ordered=list(tasks);random.Random(42+rep).shuffle(ordered)
            for profile in order:
                if all((profile,t['id'],rep) in completed for t in tasks) and (profile,rep) in completed_context:
                    continue
                if time.perf_counter()-started > 32*60:
                    raise RuntimeError('Bounded benchmark elapsed-time limit reached')
                switch_result=switch(profile)
                version=ready(profile)
                idle=remote("""import pathlib,json
p=pathlib.Path('/home/tom/.local/state/minis-llamacpp-ab-20261009/latest-idle-memory.json');print(p.read_text())
""")
                warm=generate(profile,prompts['1/unique_ordered']['prompt'].replace(tasks[0]['prompt'],'Odpowiedz wyłącznie OK.'),128)
                if warm['error'] or not warm['completed']:
                    raise RuntimeError('Warm-up failed: '+str(warm['error']))
                load={'round':rep,'profile':profile,'switch':switch_result,'version':version,
                      'warmup':warm,'idle_memory':idle,'memory_after_load':observation()}
                if profile=='ollama':
                    ps=SESSION.get(BASE+'/api/ps',timeout=20).json()['models']
                    assert len(ps)==1 and ps[0]['name']==MODEL,ps
                    assert ps[0].get('context_length')==16384,ps
                    assert ps[0].get('size_vram',0) >= ps[0].get('size',1)*0.98, 'Ollama partial CPU offload: '+str(ps)
                    load['ollama_ps']=ps
                    show=SESSION.post(BASE+'/api/show',json={'model':MODEL},timeout=30).json()
                    load['ollama_parameters']=show.get('parameters');load['ollama_capabilities']=show.get('capabilities')
                report['loads'].append(load)
                for task in ordered:
                    if (profile,task['id'],rep) in completed:
                        continue
                    prompt=prompts[str(rep)+'/'+task['id']]
                    row=generate(profile,prompt['prompt'])
                    row.update(model=PROFILES[profile]['name'],profile=profile,task=task['id'],repeat=rep,
                               expected_prompt_tokens=prompt['expected_prompt_tokens'],idle_memory=idle,
                               memory_after=observation())
                    code=CodeEvaluator().extract_python_code(row['content'])
                    check=functional_check(code,task['tests']) if row['valid_answer'] else {
                        'passed':False,'status':'failed','output':'Incomplete or empty answer'}
                    if check['status']=='infra_error':
                        row['original_infra_evaluation']=check;check=functional_check(code,task['tests'])
                    row.update(code=code,evaluation=check,passed=check['passed'])
                    report['results'].append(row);render(report)
                    print(f"{len(report['results'])}/54 round={rep} {profile} {task['id']} pass={row['passed']} wall={row['wall_s']:.2f}s rate={row['tokens_per_second']}",flush=True)
                    if row['error'] or check['status']=='infra_error':
                        raise RuntimeError('Transport/evaluation infrastructure failure; original evidence preserved')
                prompt=prompts[str(rep)+'/context_4k'];row=generate(profile,prompt['prompt'],128)
                row.update(model=PROFILES[profile]['name'],profile=profile,task='context_4k',repeat=rep,
                           expected_prompt_tokens=prompt['expected_prompt_tokens'],idle_memory=idle,
                           memory_after=observation(),passed=row['valid_answer'] and row['content'].strip()=='GOTOWE')
                report['context_results'].append(row);render(report)
                print(f"CONTEXT round={rep} {profile} tokens={row['expected_prompt_tokens']} ttft={row['first_token_s']} wall={row['wall_s']:.2f}s pass={row['passed']}",flush=True)
                if row['error']:
                    raise RuntimeError('Long-context transport failure')
        report['status']='complete'
    except BaseException as exc:
        report['status']='interrupted';report['error']=str(exc)
        raise
    finally:
        try:
            report['restoration']=switch('restore')
        finally:
            render(report)
    print('BENCHMARK COMPLETE; LLAMA.CPP RESTORED',flush=True)


if __name__=='__main__':
    main()
