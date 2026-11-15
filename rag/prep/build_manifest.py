import json, urllib.request, sys, collections
B="https://psi.nasa.gov/geode-py/ws"
H={'User-Agent':'research-client'}
# 24 combustion-relevant (PSI-181 solder, PSI-108 surface-tension excluded as off-topic)
ACC=['PSI-26','PSI-25','PSI-98','PSI-99','PSI-100','PSI-69','PSI-68','PSI-39','PSI-159',
     'PSI-102','PSI-101','PSI-47','PSI-107','PSI-106','PSI-10','PSI-20','PSI-21','PSI-22',
     'PSI-23','PSI-117','PSI-142','PSI-62','PSI-60','PSI-115']
WANT={'Science Documents','Reports','Presentations','Experimental table'}
DOCEXT={'pdf','docx','doc','pptx','ppt','rtf','txt','csv','xls','xlsx'}
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=120))
def post(u,b):
    r=urllib.request.Request(u,data=json.dumps(b).encode(),headers={**H,'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(r,timeout=180))
def walk(ns,cat,out):
    for n in ns or []:
        if n.get('directory') is False and n.get('key'):
            out.append({'key':n['key'],'size':n.get('bytes_size') or 0,'cat':cat,
                        'ver':n.get('version'),'name':n['key'].split('/')[-1]})
        if n.get('files'): walk(n['files'],cat,out)
    return out
man={}
for a in ACC:
    det=get(f"{B}/repo/investigations/{a}")
    v=det.get('version')
    j=post(f"{B}/files/v2",{"folder":f"psi-data/{a}/","fileType":"study","studyId":a,"version":v,"obfuscationcode":""})
    picked=[]
    for c in j.get('files',[]):
        dn=c.get('displayName')
        if dn in WANT: picked+=walk(c.get('files'),dn,[])
    picked=[f for f in picked if (f['name'].rsplit('.',1)[-1].lower() in DOCEXT)]
    man[a]={'ver':v,'acr':det.get('investigationAcronym') or '',
            'title':det.get('title'),'files':picked,
            'mb':round(sum(f['size'] for f in picked)/1048576,2)}
    print(f"{a:9} v{v} {len(picked):3d} files {man[a]['mb']:8.2f} MB", flush=True)
json.dump(man,open(sys.argv[1],'w'),indent=1)
tot=sum(len(v['files']) for v in man.values()); mb=sum(v['mb'] for v in man.values())
print(f"\nTOTAL {tot} files, {mb:.1f} MB")
print(collections.Counter(f['cat'] for v in man.values() for f in v['files']))
