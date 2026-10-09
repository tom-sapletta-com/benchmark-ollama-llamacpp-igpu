import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import tempfile
import time
import urllib.request

STATE = pathlib.Path('/home/tom/.local/state/minis-ollama-q8-publish-20261009')
MODEL = 'gpt-oss-minis-code:20b'
BACKUP = 'gpt-oss-minis-bf16-backup-20261009:20b'
Q8 = 'gpt-oss-minis-ab-q8:20b'
EXPECTED = 'sha256:214b01ff392ec0d991c766ceccba11948c1208c3aa8272b63a5170d802c1866e'
DROPIN = pathlib.Path('/etc/systemd/system/ollama.service.d/zz-minis-q8.conf')
CONTENT = '''[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_VULKAN=1"
Environment="OLLAMA_IGPU_ENABLE=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_CONTEXT_LENGTH=16384"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=f16"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_NO_CLOUD=1"
Environment="OLLAMA_NOPRUNE=1"
SupplementaryGroups=render video
'''


def command(*args):
    return subprocess.run(args, text=True, capture_output=True, check=True, timeout=80)


def api(path, payload=None):
    req = urllib.request.Request('http://127.0.0.1:11434' + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as response:
        body = response.read()
        return json.loads(body) if body else {}


def atomic(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(descriptor, 'w') as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def configure(values):
    with sqlite3.connect('/var/lib/docker/volumes/open-webui-auth/_data/webui.db') as conn:
        for key, value in values.items():
            if conn.execute('SELECT 1 FROM config WHERE key=?', (key,)).fetchone():
                conn.execute('UPDATE config SET value=?,updated_at=? WHERE key=?',
                             (json.dumps(value), int(time.time()), key))
            else:
                conn.execute('INSERT INTO config(key,value,updated_at) VALUES (?,?,?)',
                             (key, json.dumps(value), int(time.time())))


def model_manifest(name):
    return pathlib.Path('/usr/share/ollama/.ollama/models/manifests/registry.ollama.ai/library') / name.split(':')[0] / name.split(':')[1]


before = json.loads((STATE / 'before-production-switch.json').read_text())
assert not DROPIN.exists(), 'Unknown existing permanent profile; preserve it'
for name in ['ollama.service', 'llamacpp-gpt-oss.service']:
    p = pathlib.Path('/etc/systemd/system') / name
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before['units'][name]['sha256']
for name, manifest in before['model_manifests'].items():
    assert json.loads(model_manifest(name + ':20b').read_text()) == manifest
assert not model_manifest(BACKUP).exists()
assert any(layer['digest'] == EXPECTED for layer in before['model_manifests']['gpt-oss-minis-ab-q8']['layers'])
atomic(STATE / 'deployment-checkpoint.json', json.dumps({'ticket': 'PLF-17296',
    'phase': 'before permanent Ollama Q8 switch', 'manifest_digest': EXPECTED,
    'next_action': 'install bounded profile, backup original alias, create Q8 chat alias, route UI and verify'}, indent=2), 0o600)
switched = False
try:
    atomic(DROPIN, CONTENT)
    command('systemctl', 'disable', '--now', 'llamacpp-gpt-oss.service')
    command('systemctl', 'daemon-reload')
    command('systemctl', 'enable', '--now', 'ollama.service')
    for _ in range(40):
        try:
            api('/api/version')
            break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError('Ollama readiness timeout')
    show = api('/api/show', {'model': MODEL})
    assert show.get('template') and 'tools' in show.get('capabilities', [])
    api('/api/copy', {'source': MODEL, 'destination': BACKUP})
    switched = True
    original = before['model_manifests']['gpt-oss-minis-code']
    licenses = [pathlib.Path('/usr/share/ollama/.ollama/models/blobs', layer['digest'].replace(':', '-')).read_text()
                for layer in original['layers'] if layer['mediaType'].endswith('.license')]
    payload = {'model': MODEL, 'from': Q8, 'template': show['template'],
        'parameters': {'num_ctx': 16384, 'num_predict': 2048, 'num_thread': 8,
                       'num_batch': 512, 'num_gpu': 999, 'temperature': 0,
                       'repeat_penalty': 1.0}, 'stream': False}
    if licenses:
        payload['license'] = licenses
    result = api('/api/create', payload)
    assert result.get('status') == 'success', result
    new = json.loads(model_manifest(MODEL).read_text())
    assert any(layer['digest'] == EXPECTED for layer in new['layers'])
    assert show['template'] == api('/api/show', {'model': MODEL})['template']
    response = api('/api/chat', {'model': MODEL, 'messages': [{'role': 'user',
        'content': 'Reply with exactly MINIS_OLLAMA_Q8_OK, nothing else.'}],
        'think': 'low', 'stream': False, 'options': {'num_predict': 128}})
    assert response['message']['content'].strip() == 'MINIS_OLLAMA_Q8_OK', response
    ps = api('/api/ps')['models']
    assert len(ps) == 1 and ps[0]['name'] == MODEL and ps[0]['context_length'] == 16384
    assert ps[0]['size_vram'] >= ps[0]['size'] * .98, ps
    configure({'ollama.enable': True, 'ollama.base_urls': ['http://host.docker.internal:11434'],
               'openai.enable': False, 'ui.default_models': MODEL})
    command('docker', 'restart', 'open-webui')
    receipt = {'ticket': 'PLF-17296', 'alias': MODEL, 'q8_model_digest': EXPECTED,
        'legacy_alias': BACKUP, 'legacy_manifest_preserved': json.loads(model_manifest(BACKUP).read_text()) == original,
        'production_manifest': new, 'template_sha256': hashlib.sha256(show['template'].encode()).hexdigest(),
        'model_create': result, 'chat_smoke': response, 'full_gpu': ps,
        'ollama_active': command('systemctl', 'is-active', 'ollama.service').stdout.strip(),
        'ollama_enabled': command('systemctl', 'is-enabled', 'ollama.service').stdout.strip(),
        'llamacpp_disabled': subprocess.run(['systemctl', 'is-enabled', 'llamacpp-gpt-oss.service'], capture_output=True, text=True).stdout.strip()}
    with sqlite3.connect('/var/lib/docker/volumes/open-webui-auth/_data/webui.db') as conn:
        receipt['users'] = conn.execute('SELECT count(*) FROM user').fetchone()[0]
        receipt['chats'] = conn.execute('SELECT count(*) FROM chat').fetchone()[0]
    assert receipt['users'] == before['user_count'] and receipt['chats'] == before['chat_count']
    atomic(STATE / 'production-deployment-verification.json', json.dumps(receipt, indent=2) + '\n', 0o644)
    print(json.dumps(receipt, indent=2), flush=True)
except BaseException:
    configure(before['webui_config'])
    if switched:
        try:
            api('/api/copy', {'source': BACKUP, 'destination': MODEL})
        except Exception:
            atomic(model_manifest(MODEL), json.dumps(before['model_manifests']['gpt-oss-minis-code']))
    command('systemctl', 'disable', '--now', 'ollama.service')
    if DROPIN.exists() and DROPIN.read_text() == CONTENT:
        DROPIN.unlink()
    command('systemctl', 'daemon-reload')
    command('systemctl', 'enable', '--now', 'llamacpp-gpt-oss.service')
    command('docker', 'restart', 'open-webui')
    raise
