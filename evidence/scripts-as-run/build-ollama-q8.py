import pathlib,json,struct,math,hashlib,time,os
s=pathlib.Path('/home/tom/.local/state/minis-llamacpp-ab-20261009');d=json.loads((s/'control-model-headers.json').read_text());srcinfo={t['name']:t for t in d['official']['tensors']};source=pathlib.Path('/home/tom/.local/share/llama.cpp/models/gpt-oss-20b-official-MXFP4.gguf');headerfile=pathlib.Path('/usr/share/ollama/.ollama/models/blobs/sha256-e7b273f9636059a689e3ddcab3716e4f65abe0143ac978e46673ad0e52d09efb');started=time.monotonic();h=hashlib.sha256()
with open(source,'rb') as f:
 while b:=f.read(8*1024*1024):h.update(b)
assert h.hexdigest()=='27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901'
with open(headerfile,'rb') as f:header=bytearray(f.read(d['ollama']['data_start']))
plan=[];offset=0
for t in d['ollama']['tensors']:
 name=t['name'].replace('.attn_out.','.attn_output.').replace('.ffn_norm.','.post_attention_norm.')
 if name.endswith('.attn_sinks'):name+='.weight'
 o=srcinfo[name];assert o['dims']==t['dims'];n=math.prod(o['dims']);assert o['type'] in [0,8,39];size=n*4 if o['type']==0 else n//32*34 if o['type']==8 else n//32*17
 offset=(offset+31)//32*32;struct.pack_into('<I',header,t['type_pos'],o['type']);struct.pack_into('<Q',header,t['offset_pos'],offset);plan.append((t,o,offset,size));offset+=size
final=pathlib.Path('/home/tom/.local/share/llama.cpp/models/gpt-oss-20b-ollama-layout-q8.gguf');dst=final.with_suffix('.partial');assert not dst.exists() and not final.exists();records=[]
expected={x['name']:x['sha256'] for x in json.loads(pathlib.Path('/home/tom/.local/state/minis-llamacpp-20261009/official-model-verification.json').read_text())['tensor_hashes']}
with open(source,'rb') as src,open(dst,'x+b') as out:
 out.truncate(d['ollama']['data_start']+offset);out.write(header)
 for t,o,target,size in plan:
  src.seek(d['official']['data_start']+o['offset']);out.seek(d['ollama']['data_start']+target);remaining=size;h=hashlib.sha256()
  while remaining:
   b=src.read(min(8*1024*1024,remaining));assert b;out.write(b);h.update(b);remaining-=len(b)
  assert h.hexdigest()==expected[o['name']]
  records.append({'ollama_name':t['name'],'llamacpp_name':o['name'],'sha256':h.hexdigest(),'type':o['type'],'dims':o['dims']})
 out.flush();os.fsync(out.fileno())
h=hashlib.sha256()
with open(dst,'rb') as f:
 while b:=f.read(8*1024*1024):h.update(b)
os.replace(dst,final)
r={'path':str(final),'sha256':h.hexdigest(),'size':final.stat().st_size,'tensor_parity_with_production_q8':True,'tensor_count':len(records),'tensors':records,'elapsed_seconds':round(time.monotonic()-started,2)};(s/'ollama-q8-model-verification.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({k:v for k,v in r.items() if k!='tensors'},indent=2),flush=True)
