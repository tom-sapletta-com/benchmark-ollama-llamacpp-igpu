"""Streaming adapter extracted without changes from the measured driver."""
import hashlib
import json
import re
import time
import requests
BASE = "http://127.0.0.1:11434"
MODEL = "gpt-oss-minis-code:20b"
SESSION = requests.Session()
SESSION.trust_env = False

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
