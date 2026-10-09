import sys,pathlib,subprocess,json,hashlib,time
PROFILE=sys.argv[1] if len(sys.argv)>1 else 'restore'
assert PROFILE in ['q8','bf16','ollama','restore']
STATE=pathlib.Path('/home/tom/.local/state/minis-llamacpp-ab-20261009')
DROP=pathlib.Path('/run/systemd/system/ollama.service.d/zz-minis-ab-benchmark.conf')
DROP_CONTENT='[Service]\nEnvironment="OLLAMA_HOST=127.0.0.1:11437"\nEnvironment="OLLAMA_NUM_PARALLEL=1"\nEnvironment="OLLAMA_MAX_LOADED_MODELS=1"\nEnvironment="OLLAMA_FLASH_ATTENTION=1"\nEnvironment="OLLAMA_KV_CACHE_TYPE=f16"\nEnvironment="OLLAMA_NO_CLOUD=1"\nEnvironment="OLLAMA_NOPRUNE=1"\nSupplementaryGroups=render video\n'
UNIT=pathlib.Path('/run/systemd/system/llamacpp-ab-runtime.service')
BIN='/home/tom/.local/lib/llama.cpp/releases/b11429/llama-b11429'
MODELS={'q8':'/home/tom/.local/share/llama.cpp/models/gpt-oss-20b-official-MXFP4.gguf','bf16':'/home/tom/.local/share/llama.cpp/models/gpt-oss-20b-ollama-equivalent-bf16-attn.gguf'}
def run(*cmd):subprocess.run(list(cmd),check=True)
def stop(*services):run('systemctl','stop',*services)
if PROFILE=='restore':
 stop('ollama.service')
 if UNIT.exists():
  assert 'Description=Minis PLF-17295 isolated benchmark runtime' in UNIT.read_text();stop('llamacpp-ab-runtime.service');UNIT.unlink()
 if DROP.exists():assert DROP.read_text()==DROP_CONTENT;DROP.unlink()
 run('systemctl','disable','ollama.service');run('systemctl','daemon-reload');run('systemctl','enable','--now','llamacpp-gpt-oss.service')
else:
 stop('llamacpp-gpt-oss.service','ollama.service')
 if UNIT.exists():
  assert 'Description=Minis PLF-17295 isolated benchmark runtime' in UNIT.read_text();stop('llamacpp-ab-runtime.service')
 time.sleep(1)
 dev=pathlib.Path('/sys/class/drm/card1/device')
 (STATE/'latest-idle-memory.json').write_text(json.dumps({k:int((dev/k).read_text()) for k in ['mem_info_vram_used','mem_info_gtt_used','gpu_busy_percent']})+'\n')
 if PROFILE=='ollama':
  DROP.parent.mkdir(parents=True,exist_ok=True)
  if DROP.exists():assert DROP.read_text()==DROP_CONTENT
  DROP.write_text(DROP_CONTENT);DROP.chmod(0o644);run('systemctl','daemon-reload');run('systemctl','start','ollama.service')
 else:
  model=MODELS[PROFILE];assert pathlib.Path(model).is_file()
  content='[Unit]\nDescription=Minis PLF-17295 isolated benchmark runtime\nAfter=network.target\n\n[Service]\nType=simple\nUser=tom\nSupplementaryGroups=render video\nWorkingDirectory='+BIN+'\nExecStart='+BIN+'/llama-server --model '+model+' --host 127.0.0.1 --port 11437 --alias gpt-oss-minis-code:20b --parallel 1 --ctx-size 16384 --n-predict 2048 --batch-size 512 --ubatch-size 128 --n-gpu-layers all --fit off --flash-attn on --jinja --reasoning-format auto --reasoning-effort low --threads 8 --threads-batch 8 --offline\nRestart=no\nTimeoutStopSec=60\nNoNewPrivileges=true\nUMask=0077\n'
  UNIT.write_text(content);UNIT.chmod(0o644);run('systemctl','daemon-reload');run('systemctl','start','llamacpp-ab-runtime.service')
print(json.dumps({'profile':PROFILE,'benchmark_port':11437,'production_unchanged':True}))
