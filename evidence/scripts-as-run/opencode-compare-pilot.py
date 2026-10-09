"""Sequential, bounded OpenCode trials in disposable containers on minis.

Run from an explicitly prepared operational directory, never a Koru checkout.
The controller restores the production Q8 model in a finally block.
"""
import argparse
import datetime
import difflib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--repeats', type=int, choices=[1, 2], default=2)
args = parser.parse_args()
ROOT = args.root.resolve()
IMAGE = 'minis-opencode-benchmark:20261009'
API = 'http://127.0.0.1:11434'
PRODUCTION = 'gpt-oss-minis-code:20b'
CURRENT = None
CALLS = []


def api(path, payload=None):
    request = urllib.request.Request(API + path, data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.load(response)


class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *values): pass
    def do_POST(self):
        request_body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        # Providers use the same declared generation budget and seed. Only the
        # model changes; every effective request is archived without headers.
        request_body.update(temperature=0, seed=42)
        request_body['max_tokens'] = min(request_body.get('max_tokens', 4096), 4096)
        request_body['stream_options'] = {'include_usage': True}
        if request_body['model'].startswith('gpt-oss'):
            request_body['reasoning_effort'] = 'low'
        record = {'trial': CURRENT, 'path': self.path, 'request': request_body,
                  'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        started = time.perf_counter(); first = None; lines = []
        try:
            request = urllib.request.Request(API + self.path, data=json.dumps(request_body).encode(),
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=240) as response:
                record['http_status'] = response.status
                self.send_response(response.status)
                self.send_header('Content-Type', response.headers.get('Content-Type', 'text/event-stream'))
                self.send_header('Connection', 'close'); self.end_headers()
                for line in response:
                    if first is None: first = time.perf_counter() - started
                    lines.append(line.decode()); self.wfile.write(line); self.wfile.flush()
        except Exception as exc:
            record['error'] = str(exc)
            if 'http_status' not in record:
                self.send_error(502, str(exc))
        finally:
            record.update(wall_seconds=time.perf_counter()-started, ttft_seconds=first, response=''.join(lines))
            CALLS.append(record)
            if record['trial']:
                path = ROOT / 'trials' / record['trial'] / 'api-calls.json'
                path.write_text(json.dumps([r for r in CALLS if r['trial']==record['trial']], indent=2)+'\n')
            self.close_connection = True


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def memory():
    gpu = Path('/sys/class/drm/card1/device')
    values = {name: int((gpu / name).read_text()) for name in ['mem_info_vram_used', 'mem_info_gtt_used', 'gpu_busy_percent']}
    available = [line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')][0]
    values['mem_available_bytes'] = int(available.split()[1])*1024
    values['timestamp'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return values


def workspace(path, reference=False):
    path.mkdir(parents=True)
    (path/'src/koruapi').mkdir(parents=True)
    (path/'tests').mkdir()
    (path/'src/koruapi/__init__.py').write_text('')
    shutil.copyfile(ROOT/'fixture'/('reference_dashboard_logs.py' if reference else 'dashboard_logs.py'), path/'src/koruapi/dashboard_logs.py')
    shutil.copyfile(ROOT/'fixture/test_dashboard_logs.py', path/'tests/test_dashboard_logs.py')


def verify(path):
    command = ['docker','run','--rm','--network=none','--read-only','--cap-drop=ALL',
               '--security-opt=no-new-privileges','--pids-limit=128','--memory=512m','--cpus=2',
               '--tmpfs=/tmp:rw,nosuid,nodev,size=64m,mode=1777',
               '-e','PYTEST_DISABLE_PLUGIN_AUTOLOAD=1','-e','RUFF_CACHE_DIR=/tmp/ruff',
               '-v',str(path)+':/workspace:ro', '-v',str(ROOT/'fixture/test_stream_regression.py')+':/checks/test_stream_regression.py:ro',
               '-v',str(ROOT/'opencode_verify.py')+':/checks/verify.py:ro',IMAGE,'python','/checks/verify.py']
    run = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if run.returncode: raise RuntimeError('Sandbox failed: '+run.stderr[-2000:])
    return json.loads(run.stdout)


PROMPT = '''Execute the real Koru Planfile programming task STARTER-614:
Reduce cyclomatic complexity of koruapi.dashboard_logs.sse_log_stream to <=15
by extracting clear helpers (ticket reported code2llm CC25, current Ruff reports19).
Preserve ALL existing behavior and public
signatures. All functions in this module must meet the <=15 threshold.
Only edit src/koruapi/dashboard_logs.py. Tests and other files are read-only.
This is an isolated historical task replay; the owner has prepared scope and
baseline. Read the module, implement the refactor using OpenCode file tools,
run the visible regression tests and complexity check, and explain the result.
Commands permitted:
python -m pytest tests/test_dashboard_logs.py -k "TestParseNfoLine or TestParseAutonomousLogLine or TestReadRecentLogs or TestSseLogStream" -q -p no:cacheprovider
ruff check src/koruapi/dashboard_logs.py --select C901 --config lint.mccabe.max-complexity=15 --no-cache
Do not install dependencies or create commits. The controller runs additional
withheld tests after you finish. You have 8 assistant steps and 480 seconds.
'''


def config(model):
    return {'$schema':'https://opencode.ai/config.json','enabled_providers':['local-benchmark'],
            'model':'local-benchmark/'+model,'small_model':'local-benchmark/'+model,
            'share':'disabled','autoupdate':False,
            'permission':{'*':'deny','read':'allow','glob':'allow','grep':'allow',
                          'edit':{'*':'deny','/workspace/src/koruapi/dashboard_logs.py':'allow','src/koruapi/dashboard_logs.py':'allow'},
                          'bash':{'*':'deny','python -m pytest tests/test_dashboard_logs.py*':'allow',
                                  'ruff check src/koruapi/dashboard_logs.py*':'allow'}},
            'agent':{'benchmark':{'mode':'primary','description':'Bounded isolated coding task benchmark',
                                  'steps':8,'temperature':0,'prompt':'You are a coding agent using OpenCode tools. Follow the provided bounded task and preserve behavior. Work only in the permitted source file.'}},
            'provider':{'local-benchmark':{'npm':'@ai-sdk/openai-compatible','name':'minis Ollama benchmark',
                                         'options':{'baseURL':'http://host.docker.internal:11436/v1'},
                                         'models':{model:{'name':model,'tool_call':True,'limit':{'context':16384,'output':4096}}}}}}


report = {'schema':'igpu-opencode-koru/v1','status':'running','results':[], 'settings':{
    'models':['gemma4:12b','gpt-oss:20b'],'repeats':args.repeats,'order':'ABBA for two repeats',
    'steps':8,'timeout_seconds':480,'context':16384,'max_tokens':4096,'temperature':0,'seed':42,
    'inference':'Ollama /v1/chat/completions; gpt-oss reasoning_effort low; Gemma server default thinking behavior',
    'agent_image':subprocess.check_output(['docker','image','inspect',IMAGE,'--format','{{.Id}}'],text=True).strip()},
    'prompt':PROMPT,'task':'STARTER-614','method':'Historical real task replay, selected module and scoped tests, not full Koru acceptance. '
    'One fresh container/session per trial; provider limited to one local model, permissions bounded to one source file. '
    'Baseline/reference controls plus withheld behavior tests, real edits, no outside repair feedback. '
    'API and GPU/memory samples archived; not an energy measurement or general model ranking.'}


def save():
    (ROOT/'results.json').write_text(json.dumps(report,indent=2)+'\n')


server = ThreadingHTTPServer(('0.0.0.0',11436),Proxy)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    report['ollama_version']=api('/api/version');report['tags']=api('/api/tags')
    for name,ref in [('baseline',False),('reference',True)]:
        path=ROOT/'controls'/name;workspace(path,ref);result=verify(path)
        (ROOT/'controls'/ (name+'.json')).write_text(json.dumps(result,indent=2)+'\n')
        report[name]=result
        assert result['test_exit']==0 and result['syntax_passed'],(name,result)
        assert result['complexity_passed']==ref,(name,result)
        print('CONTROL PASS',name,result['test_summary'],flush=True)
    save()
    order=[('gemma4:12b',1),('gpt-oss:20b',1)]
    if args.repeats==2:order += [('gpt-oss:20b',2),('gemma4:12b',2)]
    for model,repeat in order:
        trial=model.replace(':','-')+'-'+str(repeat);CURRENT=trial
        path=ROOT/'trials'/trial;path.mkdir(parents=True);work=path/'workspace';workspace(work)
        for p in work.rglob('*'):
            if p.is_dir():p.chmod(0o777)
            else:p.chmod(0o666)
        before={str(p.relative_to(work)):sha(p) for p in work.rglob('*') if p.is_file()}
        configuration=config(model);(path/'opencode.json').write_text(json.dumps(configuration,indent=2)+'\n')
        row={'model':model,'repeat':repeat,'trial':trial,'configuration':configuration,'baseline_file_hashes':before}
        row['memory_before_load']=memory()
        for item in api('/api/ps')['models']:
            api('/api/generate',{'model':item['name'],'keep_alive':0})
        row['show']=api('/api/show',{'model':model})
        row['warmup']=api('/api/chat',{'model':model,'messages':[{'role':'user','content':'Reply OK.'}],
                                       'stream':False,'think':'low' if model.startswith('gpt-oss') else False,'keep_alive':-1,
                                       'options':{'num_ctx':16384,'num_predict':32,'num_gpu':999,'num_thread':8,'num_batch':512,'temperature':0}})
        row['ps_after_warmup']=api('/api/ps');row['memory_after_load']=memory()
        samples=[];stopped=threading.Event()
        def monitor():
            while not stopped.is_set(): samples.append(memory());stopped.wait(.5)
        threading.Thread(target=monitor,daemon=True).start()
        name='minis-opencode-'+trial
        command=['docker','run','--rm','--name',name,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
                 '--pids-limit=256','--memory=2g','--cpus=2','--add-host=host.docker.internal:host-gateway',
                 '--tmpfs=/tmp:rw,exec,nosuid,nodev,size=512m,mode=1777',
                 '-e','XDG_CONFIG_HOME=/tmp/config','-e','XDG_DATA_HOME=/tmp/data','-e','XDG_CACHE_HOME=/tmp/cache',
                 '-e','XDG_STATE_HOME=/tmp/state','-e','OPENCODE_CONFIG=/config/opencode.json',
                 '-e','OPENCODE_CONFIG_CONTENT='+json.dumps(configuration),'-e','RUFF_CACHE_DIR=/tmp/ruff',
                 '-v',str(work)+':/workspace:rw','-v',str(path/'opencode.json')+':/config/opencode.json:ro',
                 IMAGE,'opencode','run','--pure','--agent','benchmark','--model','local-benchmark/'+model,
                 '--format','json','--title','Koru STARTER614 benchmark',PROMPT]
        started=time.perf_counter()
        with (path/'events.jsonl').open('w') as out,(path/'stderr.log').open('w') as err:
            child=subprocess.Popen(command,stdout=out,stderr=err)
            try:row['exit_code']=child.wait(timeout=480);row['timed_out']=False
            except subprocess.TimeoutExpired:
                row['timed_out']=True;subprocess.run(['docker','kill',name],capture_output=True);row['exit_code']=child.wait(timeout=20)
        row['wall_seconds']=time.perf_counter()-started;stopped.set();row['memory_samples']=samples
        row['ps_after_run']=api('/api/ps')
        after={str(p.relative_to(work)):sha(p) for p in work.rglob('*') if p.is_file()}
        changed=sorted(name for name in set(before)|set(after) if before.get(name)!=after.get(name))
        row['changed_files']=changed;row['scope_passed']=changed==['src/koruapi/dashboard_logs.py']
        code=(work/'src/koruapi/dashboard_logs.py').read_text();row['source']=code
        row['diff']=''.join(difflib.unified_diff((ROOT/'fixture/dashboard_logs.py').read_text().splitlines(True),
                        code.splitlines(True),fromfile='before/src/koruapi/dashboard_logs.py',tofile='after/src/koruapi/dashboard_logs.py'))
        row['evaluation']=verify(work)
        row['passed']=row['scope_passed'] and not row['timed_out'] and row['evaluation']['test_exit']==0 and row['evaluation']['complexity_passed'] and row['evaluation']['lint_passed'] and row['evaluation']['syntax_passed']
        row['api_calls']=[r for r in CALLS if r['trial']==trial]
        row['events']=[json.loads(line) for line in (path/'events.jsonl').read_text().splitlines() if line.startswith('{')]
        (path/'result.json').write_text(json.dumps(row,indent=2)+'\n');report['results'].append(row);save()
        print('TRIAL',trial,'PASS' if row['passed'] else 'FAIL',round(row['wall_seconds'],1),row['evaluation']['test_summary'],len(row['api_calls']),flush=True)
    report['status']='complete'
except BaseException as exc:
    report.update(status='interrupted',error=str(exc));raise
finally:
    CURRENT=None
    for item in api('/api/ps')['models']:
        if item['name']!=PRODUCTION:api('/api/generate',{'model':item['name'],'keep_alive':0})
    report['production_restore']=api('/api/chat',{'model':PRODUCTION,'messages':[{'role':'user','content':'Reply Q8_RESTORED.'}],
                                               'stream':False,'think':'low','keep_alive':-1,'options':{'num_predict':64,'num_ctx':16384}})
    report['production_ps_restored']=api('/api/ps');save();server.shutdown()
