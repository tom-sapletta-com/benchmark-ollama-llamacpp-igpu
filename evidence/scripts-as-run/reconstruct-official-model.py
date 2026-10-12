import ctypes,json,pathlib,numpy as np,hashlib,os,time,math
s=pathlib.Path('/home/tom/.local/state/minis-llamacpp-20261009');pin=json.loads((s/'official-model-pin.json').read_text());d=json.loads((s/'gguf-header-comparison.json').read_text());old={t['name']:t for t in d['ollama']['tensors']}
assert json.loads((s/'native-q8-reconstruction-sample.json').read_text())['native_q8_0_sample_matches_official']
assert all(x['identical'] for x in json.loads((s/'gguf-reuse-sample-verification.json').read_text()))
lib=ctypes.CDLL('/home/tom/.local/lib/llama.cpp/releases/b11429/llama-b11429/libggml-base.so');q=lib.ggml_quantize_chunk;q.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int64,ctypes.c_int64,ctypes.c_int64,ctypes.c_void_p];q.restype=ctypes.c_size_t
source='/usr/share/ollama/.ollama/models/blobs/sha256-e7b273f9636059a689e3ddcab3716e4f65abe0143ac978e46673ad0e52d09efb'
final=pathlib.Path('/home/tom/.local/share/llama.cpp/models/gpt-oss-20b-official-MXFP4.gguf');dst=final.with_suffix('.reconstruction-candidate')
if dst.exists() or final.exists():raise RuntimeError('Preserve existing reconstruction/final output, inspect first')
started=time.monotonic();counts={'reused_bytes':0,'native_quantized_bytes':0};records=[]
with open(source,'rb') as src,open(dst,'x+b') as out:
 out.truncate(pin['size']);out.write((s/'official-header-4m.bin').read_bytes()[:d['official']['data_start']])
 for i,t in enumerate(d['official']['tensors']):
  name=t['name'].replace('.attn_output.','.attn_out.').replace('.post_attention_norm.','.ffn_norm.').replace('.attn_sinks.weight','.attn_sinks');o=old[name];assert t['dims']==o['dims'],(t,o)
  n=math.prod(t['dims']);src.seek(d['ollama']['data_start']+o['offset']);out.seek(d['official']['data_start']+t['offset']);h=hashlib.sha256()
  if t['type']==o['type']:
   assert t['type'] in [0,39];remaining=n*4 if t['type']==0 else n//32*17
   counts['reused_bytes']+=remaining
   while remaining:
    b=src.read(min(8*1024*1024,remaining));assert b;out.write(b);h.update(b);remaining-=len(b)
  else:
   assert t['type']==8 and o['type']==30
   width=t['dims'][0];rows=n//width
   for row in range(0,rows,2048):
    nr=min(2048,rows-row);data=src.read(nr*width*2);assert len(data)==nr*width*2
    x=np.frombuffer(data,dtype='<u2').astype(np.uint32);x<<=16;x=x.view(np.float32);z=np.empty(nr*width//32*34,dtype=np.uint8);written=q(8,x.ctypes.data,z.ctypes.data,0,nr,width,None);assert written==z.size
    b=z.tobytes();out.write(b);h.update(b);counts['native_quantized_bytes']+=len(b)
  records.append({'name':t['name'],'sha256':h.hexdigest()})
  if i%30==0:print('Reconstructed tensors',i+1,'/',len(d['official']['tensors']),flush=True)
 out.flush();os.fsync(out.fileno())
h=hashlib.sha256()
with open(dst,'rb') as f:
 while b:=f.read(8*1024*1024):h.update(b)
result={**pin,'path':str(final),'candidate_path':str(dst),'sha256_actual':h.hexdigest(),'verified':h.hexdigest()==pin['sha256'],'transport':'official header + verified existing Ollama weights + official native Q8_0 quantizer','elapsed_seconds':round(time.monotonic()-started,2),**counts,'tensor_hashes':records}
(s/'official-model-reconstruction-result.json').write_text(json.dumps(result,indent=2)+'\n')
if not result['verified']:raise RuntimeError('Reconstructed model differs from official full SHA256, do not deploy')
os.replace(dst,final);(s/'official-model-verification.json').write_text(json.dumps(result,indent=2)+'\n');print('MODEL VERIFIED: exact official SHA256',h.hexdigest(),flush=True)
