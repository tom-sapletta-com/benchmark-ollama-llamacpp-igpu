import pathlib,json,struct,math,hashlib,time,os
from pathlib import Path
s=pathlib.Path('/home/tom/.local/state/minis-llamacpp-ab-20261009');d=json.loads((s/'control-model-headers.json').read_text());old={t['name']:t for t in d['ollama']['tensors']}
source=pathlib.Path('/usr/share/ollama/.ollama/models/blobs/sha256-e7b273f9636059a689e3ddcab3716e4f65abe0143ac978e46673ad0e52d09efb');h=hashlib.sha256();started=time.monotonic()
with open(source,'rb') as f:
 while b:=f.read(8*1024*1024):h.update(b)
assert h.hexdigest()==source.name.removeprefix('sha256-')
for k,v in d['ollama']['model_metadata'].items():assert d['official']['model_metadata'][k.replace('gptoss.','gpt-oss.')]==v,(k,v)
header=bytearray(Path('/home/tom/.local/state/minis-llamacpp-20261009/official-header-4m.bin').read_bytes()[:d['official']['data_start']]);plan=[];offset=0
for t in d['official']['tensors']:
 name=t['name'].replace('.attn_output.','.attn_out.').replace('.post_attention_norm.','.ffn_norm.').replace('.attn_sinks.weight','.attn_sinks');o=old[name];assert t['dims']==o['dims'];n=math.prod(o['dims']);assert o['type'] in [0,30,39]
 size=n*4 if o['type']==0 else n*2 if o['type']==30 else n//32*17
 offset=(offset+31)//32*32;struct.pack_into('<I',header,t['type_pos'],o['type']);struct.pack_into('<Q',header,t['offset_pos'],offset)
 plan.append((t,o,offset,size));offset+=size
final=Path('/home/tom/.local/share/llama.cpp/models/gpt-oss-20b-ollama-equivalent-bf16-attn.gguf');dst=final.with_suffix('.partial');assert not final.exists() and not dst.exists()
records=[]
with open(source,'rb') as src,open(dst,'x+b') as out:
 out.truncate(d['official']['data_start']+offset);out.write(header)
 for t,o,target,size in plan:
  src.seek(d['ollama']['data_start']+o['offset']);out.seek(d['official']['data_start']+target);remaining=size;h=hashlib.sha256()
  while remaining:
   b=src.read(min(8*1024*1024,remaining));assert b;out.write(b);h.update(b);remaining-=len(b)
  records.append({'llamacpp_name':t['name'],'ollama_name':o['name'],'dims':o['dims'],'type':o['type'],'bytes':size,'identical_source_tensor_sha256':h.hexdigest()})
 out.flush();os.fsync(out.fileno())
h=hashlib.sha256()
with open(dst,'rb') as f:
 while b:=f.read(8*1024*1024):h.update(b)
os.replace(dst,final)
record={'path':str(final),'sha256':h.hexdigest(),'size':final.stat().st_size,'ollama_source_sha256':source.name.removeprefix('sha256-'),'tensor_parity':True,'tensors':records,'common_model_metadata_matches':True,'metadata_note':'Upstream GGUF metadata adds explicit YaRN beta/type; same shared original model settings, all tensor bytes unchanged','elapsed_seconds':round(time.monotonic()-started,2)}
(s/'control-model-verification.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:v for k,v in record.items() if k!='tensors'},indent=2),flush=True)
