"""Additional Q8 parity cohort, after the original Latin-square cohort."""
import importlib.util
import json
import pathlib
import random
import shutil
import time

STATE = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location('runtime_compare', STATE/'runtime_compare.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
MODEL = 'gpt-oss-minis-ab-q8:20b'
NAME = 'Ollama / MXFP4 + Q8'


def main():
    report = json.loads((STATE/'report/results.json').read_text())
    assert report['status']=='complete' and len(report['results'])==54
    assert len(report['context_results'])==9
    shutil.copy2(STATE/'report/results.json',STATE/'three-profile-final-results.json')
    parity = json.loads((STATE/'ollama-q8-model-verification.json').read_text())
    assert parity['tensor_parity_with_production_q8'] and parity['tensor_count']==459
    m.MODEL = MODEL
    m.PROFILES['ollama_q8']={'name':NAME,'quantization':'MXFP4 experts + Q8_0 attention/output/embedding',
                            'runtime':'Ollama 0.35.1 Vulkan'}
    report['models'][NAME]={'profile':'ollama_q8','runtime':'Ollama 0.35.1 Vulkan',
        'think':'low','speculative_decoding':False,
        'details':{'quantization_level':m.PROFILES['ollama_q8']['quantization']},
        'loaded':{},'memory_warning':'Driver VRAM and GTT measured separately.',
        'tensor_parity_with_llamacpp_q8':parity}
    report['status']='running';report['planned']=72
    report['method'] += ' Additional Ollama Q8 cohort was measured afterwards, with three separate reloads; it was not part of the original balanced three-profile runtime order.'
    report['additional_cohort_started_at']=time.time()
    prompts=json.loads((STATE/'raw-prompts.json').read_text())
    tasks=report['tasks']
    m.render(report)
    try:
        for rep in range(1,4):
            switch=m.switch('ollama');version=m.ready('ollama')
            idle=m.remote("import pathlib;print(pathlib.Path('/home/tom/.local/state/minis-llamacpp-ab-20261009/latest-idle-memory.json').read_text())")
            warm=m.generate('ollama',prompts['1/unique_ordered']['prompt'].replace(tasks[0]['prompt'],'Odpowiedz wyłącznie OK.'),128)
            if warm['error'] or not warm['completed']:
                raise RuntimeError('Ollama Q8 warm-up failed: '+str(warm['error']))
            ps=m.SESSION.get(m.BASE+'/api/ps',timeout=30).json()['models']
            assert len(ps)==1 and ps[0]['name']==MODEL
            assert ps[0]['context_length']==16384 and ps[0]['size_vram']>=ps[0]['size']*0.98
            report['loads'].append({'round':rep,'profile':'ollama_q8','switch':switch,
                'version':version,'warmup':warm,'idle_memory':idle,'ollama_ps':ps,
                'memory_after_load':m.observation()})
            ordered=list(tasks);random.Random(42+rep).shuffle(ordered)
            for task in ordered:
                prompt=prompts[str(rep)+'/'+task['id']]
                row=m.generate('ollama',prompt['prompt'])
                row.update(model=NAME,profile='ollama_q8',task=task['id'],repeat=rep,
                    expected_prompt_tokens=prompt['expected_prompt_tokens'],idle_memory=idle,
                    memory_after=m.observation())
                code=m.CodeEvaluator().extract_python_code(row['content'])
                check=m.functional_check(code,task['tests']) if row['valid_answer'] else {
                    'passed':False,'status':'failed','output':'Incomplete or empty answer'}
                if check['status']=='infra_error':
                    row['original_infra_evaluation']=check;check=m.functional_check(code,task['tests'])
                row.update(code=code,evaluation=check,passed=check['passed'])
                report['results'].append(row);m.render(report)
                print(f"{len(report['results'])}/72 OllamaQ8 round={rep} {task['id']} pass={row['passed']} wall={row['wall_s']:.2f}s rate={row['tokens_per_second']}",flush=True)
                if row['error'] or check['status']=='infra_error':
                    raise RuntimeError('Ollama Q8 transport/evaluation error')
            prompt=prompts[str(rep)+'/context_4k'];row=m.generate('ollama',prompt['prompt'],128)
            row.update(model=NAME,profile='ollama_q8',task='context_4k',repeat=rep,
                expected_prompt_tokens=prompt['expected_prompt_tokens'],idle_memory=idle,
                memory_after=m.observation(),passed=row['valid_answer'] and row['content'].strip()=='GOTOWE')
            report['context_results'].append(row);m.render(report)
            print(f"CONTEXT OllamaQ8 round={rep} ttft={row['first_token_s']} wall={row['wall_s']:.2f}s pass={row['passed']}",flush=True)
            if row['error']:raise RuntimeError('Ollama Q8 context transport error')
        report['status']='complete'
    except BaseException as e:
        report['status']='interrupted';report['error']=str(e)
        raise
    finally:
        try:report['restoration']=m.switch('restore')
        finally:m.render(report)
    print('Q8 PARITY COHORT COMPLETE; LLAMA.CPP RESTORED',flush=True)


if __name__=='__main__':main()
