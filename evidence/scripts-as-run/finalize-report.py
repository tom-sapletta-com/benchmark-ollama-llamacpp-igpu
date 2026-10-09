import hashlib
import importlib.util
import json
import pathlib
import statistics
from collections import Counter

root = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location('runtime_compare', root / 'runtime_compare.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.PROFILES['ollama_q8'] = {'name': 'Ollama / MXFP4 + Q8'}
report = json.loads((root / 'report/results.json').read_text())
assert report['status'] == 'complete', report.get('error')
assert len(report['results']) == 72 and len(report['context_results']) == 12
prompts = json.loads((root / 'raw-prompts.json').read_text())
assert len(prompts) == 21
keys = Counter()
for row in report['results'] + report['context_results']:
    keys[(row['profile'], row['task'], row['repeat'])] += 1
    expected = prompts[str(row['repeat']) + '/' + row['task']]
    assert row['request']['prompt'] == expected['prompt']
    assert hashlib.sha256(row['request']['prompt'].encode()).hexdigest() == row['prompt_sha256'] == expected['sha256']
    assert row['passed'] and row['valid_answer'] and row['completed']
    assert not row['error'] and not row['truncated']
    if row['task'] != 'context_4k':
        assert row['evaluation']['status'] == 'passed'
        assert row['evaluation']['passed']
    assert 0 <= expected['expected_prompt_tokens'] - row['prompt_eval_count'] <= 8
    row['stream_decode_tokens_per_second'] = (row['eval_count'] - 1) / (row['wall_s'] - row['first_token_s'])
assert all(n == 1 for n in keys.values())
assert Counter(r['profile'] for r in report['results']) == dict.fromkeys(['q8', 'bf16', 'ollama', 'ollama_q8'], 18)
assert Counter(r['profile'] for r in report['context_results']) == dict.fromkeys(['q8', 'bf16', 'ollama', 'ollama_q8'], 3)
assert all(len(load['ollama_ps']) == 1 and load['ollama_ps'][0]['context_length'] == 16384
           and load['ollama_ps'][0]['size_vram'] >= load['ollama_ps'][0]['size'] * .98
           for load in report['loads'] if load['profile'].startswith('ollama'))
parity = json.loads((root / 'ollama-q8-model-verification.json').read_text())
assert parity['tensor_count'] == 459 and parity['tensor_parity_with_production_q8']
report['method'] = ('Identyczne bajty promptów Harmony, ten sam tokenizer, tryb rozumowania low, '
                    'temperatura 0 i brak równoległych zapytań. Pierwsze trzy profile wykonano '
                    'w trzech zmiennych kolejnościach, a dodatkowy Ollama Q8 po nich. '
                    'Porównania BF16/BF16 oraz Q8/Q8 zachowują wszystkie bajty tensorów. '
                    'Format metadanych i implementacje kerneli oraz wewnętrznych batchy różnią się. '
                    'Dodatkowy profil wykonany później nie stanowi zrównoważonego porządku czterech silników.')
report['independent_validation'] = {'coding_trials': 72, 'coding_passed': 72, 'context_trials': 12,
    'context_passed': 12, 'unique_trials': len(keys), 'identical_paired_raw_prompts': True,
    'same_tokenizer': True, 'full_gpu_ollama_loads_verified': True,
    'q8_tensor_parity': 459, 'transport_errors': 0, 'truncations': 0,
    'stream_decode_medians': {name: statistics.median(r['stream_decode_tokens_per_second']
        for r in report['results'] if r['model'] == name) for name in report['models']}}
report['conclusion'] = ('Wszystkie 72 rozwiązania przeszły testy kodu (6 zadań × 3 powtórzenia × 4 profile), '
                        'a 12 prób dłuższego wejścia zwróciło poprawną odpowiedź. '
                        'Q8 daje około 40% więcej tokenów/s niż BF16. '
                        'Przy identycznych wagach oba silniki generują z podobną szybkością; '
                        'Ollama w tym pomiarze szybciej przetwarza dłuższe wejście. '
                        'Wyniki dotyczą tych ustawień oraz małego zestawu, nie wszystkich projektów. '
                        'Po benchmarku przywrócono llama.cpp, a Ollama została zatrzymana i wyłączona z autostartu.')
m.render(report)
(root / 'final-validation.json').write_text(json.dumps(report['independent_validation'], indent=2) + '\n')
print(json.dumps({'summary': report['summary'], 'context': report['context_summary'],
                 'validation': report['independent_validation']}, indent=2))
