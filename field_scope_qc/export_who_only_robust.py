#!/usr/bin/env python3
import csv, hashlib, json, re, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UA='SRMA-Bangladesh-WHO-IRIS/2.0'
OUT=Path('who_iris_robust'); OUT.mkdir(exist_ok=True)
QUERIES=[
 'Bangladesh immunization','Bangladesh vaccination','Bangladesh EPI',
 'Bangladesh coverage evaluation survey','Bangladesh child immunization',
 'Bangladesh zero-dose','Bangladesh dropout immunization',
 'Bangladesh timeliness vaccination','Bangladesh missed opportunities vaccination'
]
BASE='https://iris.who.int/server/api/discover/search/objects'

def get_json(url):
    req=Request(url,headers={'User-Agent':UA,'Accept':'application/hal+json, application/json'})
    with urlopen(req,timeout=60) as r:
        return json.loads(r.read().decode('utf-8')), r.geturl()

def find_pages(obj,path='root'):
    out=[]
    if isinstance(obj,dict):
        if 'totalElements' in obj and any(k in obj for k in ('number','size','totalPages')):
            out.append((path,obj))
        for k,v in obj.items(): out.extend(find_pages(v,path+'.'+k))
    elif isinstance(obj,list):
        for i,v in enumerate(obj): out.extend(find_pages(v,f'{path}[{i}]'))
    return out

def collect_indexables(obj):
    found=[]
    if isinstance(obj,dict):
        io=obj.get('indexableObject')
        if isinstance(io,dict): found.append(io)
        for v in obj.values(): found.extend(collect_indexables(v))
    elif isinstance(obj,list):
        for v in obj: found.extend(collect_indexables(v))
    return found

def mdvals(md,key):
    vals=md.get(key) or []
    return [x.get('value','') for x in vals if isinstance(x,dict) and x.get('value')]

def normalize_item(idx):
    md=idx.get('metadata') or {}
    title=(mdvals(md,'dc.title') or mdvals(md,'dc.title.alternative') or [idx.get('name','') or ''])[0]
    uri=(mdvals(md,'dc.identifier.uri') or [''])[0]
    date=(mdvals(md,'dc.date.issued') or mdvals(md,'dc.date.available') or [''])[0]
    return {'uuid':idx.get('uuid',''),'name':idx.get('name',''),'title':title,'type':idx.get('type',''),'uri':uri,'date':date}

def search(q,size=100):
    first=BASE+'?'+urlencode({'query':q,'page':0,'size':size})
    data,final=get_json(first)
    (OUT/f'raw_{re.sub(r"[^a-z0-9]+","_",q.lower()).strip("_")}_p0.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    pages=find_pages(data)
    totals=[int(p.get('totalElements',0) or 0) for _,p in pages]
    total=max(totals) if totals else None
    raw_items=collect_indexables(data)
    items=[]; seen=set()
    def add_all(xs):
        for x in xs:
            y=normalize_item(x); key=y['uuid'] or y['uri'] or y['title'].lower()
            if key and key not in seen: seen.add(key); items.append(y)
    add_all(raw_items)
    if total is None:
        # Fallback: page until empty/repeated, capped safely.
        max_pages=20
    else:
        max_pages=max(1,(total+size-1)//size)
    for page in range(1,max_pages):
        url=BASE+'?'+urlencode({'query':q,'page':page,'size':size})
        d,_=get_json(url)
        xs=collect_indexables(d)
        before=len(items); add_all(xs)
        if not xs or len(items)==before: break
        time.sleep(0.15)
    return {'query':q,'native_hit_count':total if total is not None else len(items),'retrieved_unique':len(items),'first_url':final,'page_nodes':' | '.join(f'{path}:{p.get("totalElements")}' for path,p in pages)},items

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    logs=[]; union={}
    for q in QUERIES:
        try:
            log,items=search(q); log['status']='OK'; log['error']=''; logs.append(log)
            for it in items:
                key=it['uuid'] or it['uri'] or it['title'].lower()
                if key not in union: union[key]={**it,'queries':[q]}
                elif q not in union[key]['queries']: union[key]['queries'].append(q)
        except Exception as e:
            logs.append({'query':q,'status':'FAILED','error':repr(e)})
    qpath=OUT/'WHO_IRIS_Native_Query_Log_ROBUST_2026-09-02.csv'
    fields=['query','native_hit_count','retrieved_unique','first_url','page_nodes','status','error']
    with qpath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader();
        for r in logs: w.writerow({k:r.get(k,'') for k in fields})
    upath=OUT/'WHO_IRIS_Native_Union_ROBUST_2026-09-02.csv'
    fields2=['uuid','title','name','type','uri','date','queries']
    with upath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields2); w.writeheader()
        for r in sorted(union.values(),key=lambda x:(x.get('title') or '').lower()):
            x={k:r.get(k,'') for k in fields2}; x['queries']=' | '.join(r.get('queries',[])); w.writerow(x)
    summary={'successful_queries':sum(r.get('status')=='OK' for r in logs),'failed_queries':sum(r.get('status')=='FAILED' for r in logs),'union_unique':len(union),'query_log_sha256':sha(qpath),'union_sha256':sha(upath)}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    for r in logs: print(json.dumps(r,ensure_ascii=False))

if __name__=='__main__': main()
