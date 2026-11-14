import json, os, sys, time, urllib.request, urllib.parse, hashlib
MAN, OUT = sys.argv[1], sys.argv[2]
H = {'User-Agent':'research-client'}
# 5 investigations excluded: no usable documents at all
SKIP = {'PSI-62','PSI-60','PSI-106','PSI-21','PSI-142'}
man = json.load(open(MAN))
log = open(os.path.join(OUT,'_download_log.txt'),'w',encoding='utf-8')
def say(s):
    print(s, flush=True); log.write(s+'\n'); log.flush()
ok=fail=skip=0; done=[]
targets=[(a,v) for a,v in man.items() if a not in SKIP]
total=sum(len(v['files']) for _,v in targets)
say(f"{len(targets)} investigations, {total} files")
for acc, inv in targets:
    d = os.path.join(OUT, acc)
    os.makedirs(d, exist_ok=True)
    for f in inv['files']:
        safe = f['name'].replace('/','_')
        dest = os.path.join(d, safe)
        if os.path.exists(dest) and os.path.getsize(dest) > 0 and abs(os.path.getsize(dest)-f['size'])<2:
            skip+=1; continue
        url = ("https://psi.nasa.gov/geode-py/ws/studies/%s/download?file=%s&version=%s&redirect=false"
               % (acc, urllib.parse.quote(f['name']), f['ver']))
        for attempt in range(3):
            try:
                s3 = urllib.request.urlopen(urllib.request.Request(url,headers=H),timeout=120).read().decode().strip()
                if not s3.startswith('http'): raise ValueError('no url: '+s3[:80])
                data = urllib.request.urlopen(urllib.request.Request(s3,headers=H),timeout=600).read()
                open(dest,'wb').write(data)
                ok+=1
                done.append({'acc':acc,'cat':f['cat'],'name':safe,'bytes':len(data),
                             'sha1':hashlib.sha1(data).hexdigest(),
                             'psi_key':f['key'],'version':f['ver']})
                say(f"  OK   {acc:9} {len(data)/1048576:7.2f}MB  {safe[:72]}")
                break
            except Exception as e:
                if attempt==2:
                    fail+=1; say(f"  FAIL {acc:9} {safe[:60]} -> {e}")
                else: time.sleep(2)
json.dump(done, open(os.path.join(OUT,'_manifest_downloaded.json'),'w'), indent=1)
say(f"\nDONE ok={ok} failed={fail} already={skip}")
