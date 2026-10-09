"""Verify archived hashes, paired prompts, tensor receipts and trial coverage offline."""
import hashlib
import json
import pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(relative):
    return json.loads((ROOT / relative).read_text())


def verify():
    checked = set()
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = ROOT / name
        assert path.resolve().is_relative_to(ROOT), name
        assert name not in checked, name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
        checked.add(name)
    assert checked, 'Empty checksum manifest'
    result = load('results/minis-20261009/results.json')
    prompts = load('results/minis-20261009/raw-prompts.json')
    assert result['status'] == 'complete'
    assert len(result['results']) == 72 and len(result['context_results']) == 12
    assert len(prompts) == 21
    assert Counter(r['profile'] for r in result['results']) == dict.fromkeys(['q8', 'bf16', 'ollama', 'ollama_q8'], 18)
    assert Counter(r['profile'] for r in result['context_results']) == dict.fromkeys(['q8', 'bf16', 'ollama', 'ollama_q8'], 3)
    keys = set()
    for row in result['results'] + result['context_results']:
        key = row['profile'], row['task'], row['repeat']
        assert key not in keys, key
        keys.add(key)
        expected = prompts[str(row['repeat']) + '/' + row['task']]
        assert row['request']['prompt'] == expected['prompt']
        assert hashlib.sha256(expected['prompt'].encode()).hexdigest() == row['prompt_sha256'] == expected['sha256']
        assert row['passed'] and row['valid_answer'] and row['completed']
        assert not row['error'] and not row['truncated']
        assert 0 <= expected['expected_prompt_tokens'] - row['prompt_eval_count'] <= 8
        if row['task'] != 'context_4k':
            assert row['evaluation']['passed'] and row['evaluation']['status'] == 'passed'
    task_bytes = (ROOT / 'vendor/allama-src/allama/benchmark_tasks.json').read_bytes()
    assert hashlib.sha256(task_bytes).hexdigest() == result['tasks_sha256']
    original = load('evidence/model-parity/official-model-verification.json')
    q8 = load('evidence/model-parity/ollama-q8-model-verification.json')
    bf16 = load('evidence/model-parity/control-model-verification.json')
    assert q8['tensor_parity_with_production_q8'] and q8['tensor_count'] == 459
    assert bf16['tensor_parity'] and bf16['common_model_metadata_matches']
    hashes = {r['name']: r['sha256'] for r in original['tensor_hashes']}
    assert len(hashes) == len(q8['tensors']) == len(bf16['tensors']) == 459
    assert all(hashes[r['llamacpp_name']] == r['sha256'] for r in q8['tensors'])
    assert Counter(r['type'] for r in q8['tensors']) == {0: 289, 8: 98, 39: 72}
    assert Counter(r['type'] for r in bf16['tensors']) == {0: 289, 30: 98, 39: 72}
    assert all(hashes[r['llamacpp_name']] == r['identical_source_tensor_sha256']
               for r in bf16['tensors'] if r['type'] in [0, 39])
    for item in result['loads']:
        if item['profile'].startswith('ollama'):
            models = item['ollama_ps']
            assert len(models) == 1 and models[0]['context_length'] == 16384
            assert models[0]['size_vram'] >= .98 * models[0]['size']
    prior = load('results/minis-20261008/results.json')
    interrupted = load('results/minis-20261009/interrupted-port-precedence-results.json')
    deployment = load('evidence/deployment/20261009-ollama-q8.json')
    assert deployment['ollama_active'] == 'active' and deployment['ollama_enabled'] == 'enabled'
    assert deployment['llamacpp_disabled'] == 'disabled'
    assert deployment['legacy_manifest_preserved']
    assert any(layer['digest'] == 'sha256:' + q8['sha256'] for layer in deployment['production_manifest']['layers'])
    replay = load('results/production-replay-20261009/results.json')
    assert replay['status'] == 'complete' and len(replay['results']) == 6 and len(replay['context_results']) == 1
    assert all(row['passed'] for row in replay['results'] + replay['context_results'])
    rechecked = load('evidence/validation/recheck72.json')
    assert len(rechecked) == 72 and all(row['passed'] for row in rechecked)
    return {'checksum_files': len(checked), 'coding_passed': 72, 'long_input_passed': 12,
            'paired_prompts': 21, 'q8_matching_tensors': 459,
            'prior_report_trials': len(prior['results']),
            'interrupted_preserved_trials': len(interrupted['results']),
            'saved_code_rechecked': 72, 'production_replay_coding': 6, 'production_replay_context': 1,
            'deployment': 'Ollama Q8 enabled; llama.cpp disabled (historical deployment receipt)'}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
