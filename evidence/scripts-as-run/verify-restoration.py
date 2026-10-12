import datetime
import json
import pathlib
import subprocess
import time

import requests

root = pathlib.Path(__file__).parent
code = '''import pathlib,json,hashlib,subprocess
s=pathlib.Path('/home/tom/.local/state/minis-llamacpp-ab-20261009')
before=json.loads((s/'before-runtime-effects.json').read_text())
def state(verb,name):return subprocess.run(['systemctl',verb,name],capture_output=True,text=True).stdout.strip()
r={'production_active':state('is-active','llamacpp-gpt-oss.service'),
 'production_enabled':state('is-enabled','llamacpp-gpt-oss.service'),
 'ollama_active':state('is-active','ollama.service'),
 'ollama_enabled':state('is-enabled','ollama.service'),
 'benchmark_active':state('is-active','llamacpp-ab-runtime.service'),
 'production_unit_sha256':hashlib.sha256(pathlib.Path('/etc/systemd/system/llamacpp-gpt-oss.service').read_bytes()).hexdigest(),
 'temporary_dropin_exists':pathlib.Path('/run/systemd/system/ollama.service.d/zz-minis-ab-benchmark.conf').exists(),
 'temporary_unit_exists':pathlib.Path('/run/systemd/system/llamacpp-ab-runtime.service').exists(),
 'ollama_processes':subprocess.run(['pgrep','-a','-x','ollama'],capture_output=True,text=True).stdout.strip()}
assert r['production_active']=='active' and r['production_enabled']=='enabled'
assert r['ollama_active']=='inactive' and r['ollama_enabled']=='disabled'
assert r['benchmark_active']=='inactive'
assert r['production_unit_sha256']==before['before']['production_unit_sha256']
assert not r['temporary_dropin_exists'] and not r['temporary_unit_exists'] and not r['ollama_processes']
print(json.dumps(r))
'''
r = subprocess.run(['ssh', 'tom@192.168.188.170', 'python3', '-'], input=code,
                   text=True, capture_output=True, check=True, timeout=40)
receipt = json.loads(r.stdout)
session = requests.Session()
session.trust_env = False
for _ in range(60):
    health = session.get('http://minis:11434/health', timeout=3)
    if health.ok and health.json().get('status') == 'ok':
        break
    time.sleep(1)
else:
    raise RuntimeError('Restored model not ready')
for base in ['http://minis:11434', 'http://127.0.0.1:11435']:
    models = session.get(base + '/v1/models', timeout=10)
    models.raise_for_status()
    assert models.json()['data'][0]['id'] == 'gpt-oss-minis-code:20b'
payload = {'model': 'gpt-oss-minis-code:20b', 'messages': [{'role': 'user', 'content': 'Oblicz 2+2. Odpowiedz tylko cyfrą.'}],
           'temperature': 0, 'max_tokens': 128, 'reasoning_effort': 'low', 'stream': False}
response = session.post('http://127.0.0.1:11435/v1/chat/completions', json=payload, timeout=60)
response.raise_for_status()
reply = response.json()
assert reply['choices'][0]['message']['content'].strip() == '4', reply
receipt['smoke_prompt'] = payload
receipt['smoke_response'] = reply
receipt['production_tunnel_verified'] = True
for url in ['http://minis:11434/', 'http://minis:3000/', 'http://minis:3001/llamacpp-vs-ollama-20261009/']:
    page = session.get(url, timeout=15)
    assert page.status_code == 200, (url, page.status_code)
receipt['web_interfaces_http200'] = True
receipt['verified_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
(root / 'restoration-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
