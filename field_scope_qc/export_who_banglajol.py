#!/usr/bin/env python3
import csv, hashlib, json, re, time
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, quote_plus, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

UA='SRMA-Bangladesh-NativeLogs/1.0 (systematic review evidence archive)'
OUT=Path('native_source_exports'); OUT.mkdir(exist_ok=True)

def sha256(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def get(url, attempts=5, accept='*/*'):
    last=None
    for i in range(attempts):
        try:
            req=Request(url,headers={'User-Agent':UA,'Accept':accept})
            with urlopen(req,timeout=120) as r: return r.read(),r.geturl(),dict(r.headers)
        except (HTTPError,URLError,TimeoutError) as e:
            last=e
            if i+1<attempts: time.sleep(2*(i+1))
    raise last

def textclean(s):
    return re.sub(r'\s+',' ',unescape(re.sub(r'<[^>]+>',' ',s or ''))).strip()

# ---- WHO IRIS DSpace 7 REST ----
WHO_QUERIES=[
 'Bangladesh immunization',
 'Bangladesh vaccination',
 'Bangladesh EPI',
 'Bangladesh coverage evaluation survey',
 'Bangladesh child immunization',
 'Bangladesh zero-dose',
 'Bangladesh dropout immunization',
 'Bangladesh timeliness vaccination',
 'Bangladesh missed opportunities vaccination',
]

def who_search(q,size=100):
    base='https://iris.who.int/server/api/discover/search/objects'
    page=0; rows=[]; total=None; first_url=None
    while True:
        url=base+'?'+urlencode({'query':q,'page':page,'size':size})
        raw,final,_=get(url,accept='application/hal+json, application/json')
        if first_url is None: first_url=final
        data=json.loads(raw.decode('utf-8'))
        if total is None:
            total=int((data.get('page') or {}).get('totalElements',0) or 0)
        embedded=data.get('_embedded') or {}
        objs=embedded.get('searchResult') or embedded.get('searchResultPage') or []
        if isinstance(objs,dict):
            objs=(objs.get('_embedded') or {}).get('searchResult',[]) or []
        if not objs: break
        for o in objs:
            idx=o.get('_embedded',{}).get('indexableObject',{}) or {}
            md=idx.get('metadata',{}) or {}
            def vals(key): return [x.get('value','') for x in (md.get(key) or []) if x.get('value')]
            title=(vals('dc.title') or vals('dc.title.alternative') or [''])[0]
            rows.append({'query':q,'uuid':idx.get('uuid',''),'name':idx.get('name',''),'title':title,'type':idx.get('type',''),'handle':(vals('dc.identifier.uri') or [''])[0]})
        page+=1
        if page*size>=total: break
        time.sleep(0.2)
    return total,rows,first_url

def export_who():
    qlog=[]; allrows=[]
    for q in WHO_QUERIES:
        try:
            total,rows,url=who_search(q)
            qlog.append({'query':q,'native_hit_count':total,'retrieved':len(rows),'first_url':url,'status':'OK'})
            allrows.extend(rows)
        except Exception as e:
            qlog.append({'query':q,'status':'FAILED','error':repr(e)})
    qpath=OUT/'WHO_IRIS_Native_Query_Log_2026-09-01.csv'
    with qpath.open('w',encoding='utf-8-sig',newline='') as f:
        fields=['query','native_hit_count','retrieved','first_url','status','error']; w=csv.DictWriter(f,fieldnames=fields); w.writeheader();
        for r in qlog: w.writerow({k:r.get(k,'') for k in fields})
    # union dedup by uuid (fallback title/name)
    uniq={}
    for r in allrows:
        key=r.get('uuid') or (r.get('title') or r.get('name')).lower()
        if not key: continue
        if key not in uniq:
            x=dict(r); x['queries']=[r['query']]; uniq[key]=x
        elif r['query'] not in uniq[key]['queries']: uniq[key]['queries'].append(r['query'])
    upath=OUT/'WHO_IRIS_Native_Union_2026-09-01.csv'
    fields=['uuid','title','name','type','handle','queries']
    with upath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in sorted(uniq.values(), key=lambda x:(x.get('title') or x.get('name') or '').lower()):
            x={k:r.get(k,'') for k in fields}; x['queries']=' | '.join(r.get('queries',[])); w.writerow(x)
    return {'source':'WHO IRIS','query_count':len(WHO_QUERIES),'successful_queries':sum(x.get('status')=='OK' for x in qlog),'union_unique':len(uniq),'query_log':str(qpath),'query_log_sha256':sha256(qpath),'union_export':str(upath),'union_sha256':sha256(upath)}

# ---- BanglaJOL OJS site search ----
BJ_QUERIES=[
 'Bangladesh immunization child',
 'Bangladesh vaccination coverage',
 'EPI Bangladesh child',
 'zero-dose Bangladesh',
 'vaccination dropout Bangladesh',
 'vaccination timeliness Bangladesh',
]

def bj_search(q,max_pages=200):
    base='https://www.banglajol.info/index.php/index/search/search'
    seen=set(); rows=[]; raw_pages=[]; page=1
    while page<=max_pages:
        url=base+'?'+urlencode({'query':q,'page':page})
        raw,final,_=get(url,accept='text/html')
        html=raw.decode('utf-8','replace'); raw_pages.append((page,html,final))
        # OJS result title anchors normally point to /article/view/<id>
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']*/article/view/[^"\']+)["\'][^>]*>(.*?)</a>',html,re.I|re.S):
            href=urljoin(final,m.group(1)); title=textclean(m.group(2))
            if not title: continue
            key=href.split('?')[0].rstrip('/')
            if key in seen: continue
            seen.add(key); rows.append({'query':q,'title':title,'url':href})
        # Stop when there is no visible next page link. OJS uses rel="next" or pagination next.
        has_next=bool(re.search(r'rel=["\']next["\']',html,re.I)) or bool(re.search(r'class=["\'][^"\']*next[^"\']*["\']',html,re.I))
        if not has_next: break
        page+=1; time.sleep(0.2)
    return rows,raw_pages

def export_bj():
    qlog=[]; allrows=[]
    rawdir=OUT/'BanglaJOL_raw_pages'; rawdir.mkdir(exist_ok=True)
    for qi,q in enumerate(BJ_QUERIES,1):
        try:
            rows,pages=bj_search(q)
            allrows.extend(rows)
            for pg,html,url in pages:
                (rawdir/f'Q{qi:02d}_page{pg:03d}.html').write_text(html,encoding='utf-8')
            qlog.append({'search_no':qi,'query':q,'retrieved_unique_article_links':len(rows),'pages_archived':len(pages),'status':'OK','first_url':pages[0][2] if pages else ''})
        except Exception as e:
            qlog.append({'search_no':qi,'query':q,'status':'FAILED','error':repr(e)})
    qpath=OUT/'BanglaJOL_Native_6_Search_Log_2026-09-01.csv'
    fields=['search_no','query','retrieved_unique_article_links','pages_archived','status','first_url','error']
    with qpath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); [w.writerow({k:r.get(k,'') for k in fields}) for r in qlog]
    uniq={}
    for r in allrows:
        key=r['url'].split('?')[0].rstrip('/')
        if key not in uniq:
            x=dict(r); x['queries']=[r['query']]; uniq[key]=x
        elif r['query'] not in uniq[key]['queries']: uniq[key]['queries'].append(r['query'])
    upath=OUT/'BanglaJOL_Native_6_Search_Union_2026-09-01.csv'
    with upath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['title','url','queries']); w.writeheader()
        for r in sorted(uniq.values(),key=lambda x:x['title'].lower()): w.writerow({'title':r['title'],'url':r['url'],'queries':' | '.join(r['queries'])})
    return {'source':'BanglaJOL','query_count':len(BJ_QUERIES),'successful_queries':sum(x.get('status')=='OK' for x in qlog),'union_unique_article_links':len(uniq),'query_log':str(qpath),'query_log_sha256':sha256(qpath),'union_export':str(upath),'union_sha256':sha256(upath),'raw_pages_dir':str(rawdir)}

def main():
    ss=[]
    for name,fn in [('WHO IRIS',export_who),('BanglaJOL',export_bj)]:
        try:
            s=fn(); ss.append(s); print(json.dumps(s,indent=2,ensure_ascii=False))
        except Exception as e:
            x={'source':name,'status':'FAILED','error':repr(e)}; ss.append(x); print(json.dumps(x,indent=2))
    p=OUT/'native_source_summary.json'; p.write_text(json.dumps(ss,indent=2,ensure_ascii=False),encoding='utf-8')
    return 0 if all(x.get('status')!='FAILED' for x in ss) else 2

if __name__=='__main__': raise SystemExit(main())
