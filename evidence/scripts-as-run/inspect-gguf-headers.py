import struct,pathlib,json,collections
S=pathlib.Path('/home/tom/.local/state/minis-llamacpp-20261009')
def parse(b):
 pos=0
 def take(fmt):
  nonlocal pos
  v=struct.unpack_from('<'+fmt,b,pos);pos+=struct.calcsize('<'+fmt);return v[0] if len(v)==1 else v
 def string():
  nonlocal pos
  n=take('Q');v=b[pos:pos+n];pos+=n;assert pos<=len(b);return v.decode()
 def val(t):
  nonlocal pos
  fmt={0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
  if t in fmt:return take(fmt[t])
  if t==8:return string()
  if t==9:
   subtype=take('I');n=take('Q');return [val(subtype) for _ in range(n)]
  raise ValueError(t)
 assert b[:4]==b'GGUF';pos=4;version=take('I');nt=take('Q');nk=take('Q');kv={}
 for _ in range(nk):key=string();kv[key]=val(take('I'))
 tensors=[]
 for _ in range(nt):
  name=string();nd=take('I');dims=[take('Q') for _ in range(nd)];typ=take('I');off=take('Q');tensors.append({'name':name,'dims':dims,'type':typ,'offset':off})
 alignment=kv.get('general.alignment',32);start=(pos+alignment-1)//alignment*alignment
 return {'version':version,'architecture':kv.get('general.architecture'),'header_end':pos,'data_start':start,'tensors':tensors,'alignment':alignment}
def main():
 a=parse((S/'official-header-4m.bin').read_bytes())
 with open('/usr/share/ollama/.ollama/models/blobs/sha256-e7b273f9636059a689e3ddcab3716e4f65abe0143ac978e46673ad0e52d09efb','rb') as f:b=parse(f.read(16*1024*1024))
 (S/'gguf-header-comparison.json').write_text(json.dumps({'official':a,'ollama':b},indent=2)+'\n')
 print(json.dumps({'official':{k:v for k,v in a.items() if k!='tensors'},'ollama':{k:v for k,v in b.items() if k!='tensors'},'official_first':a['tensors'][:8],'ollama_first':b['tensors'][:8],'tensor_counts':[len(a['tensors']),len(b['tensors'])]},indent=2))
if __name__=='__main__':main()
