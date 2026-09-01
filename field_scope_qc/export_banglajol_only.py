#!/usr/bin/env python3
import csv, hashlib, json, re, time
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

UA='SRMA-Bangladesh-BanglaJOL/2.0'
OUT=Path('banglajol_native'); OUT.mkdir(exist_ok=True)
QUERIES=[
 'Bangladesh immunization child','Bangladesh vaccination coverage','EPI Bangladesh child',
 'zero-dose Bangladesh','vaccination dropout Bangladesh','vaccination timeliness Bangladesh'
]
BASE='https://www.banglajol.info/index.php/index/search/search'

def get(url):
    last=None
    for i in range(2):
        try:
            req=Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml'})
            with urlopen(req,timeout=25) as r: return r.read().decode('utf-8','replace'),r.geturl()
        except (HTTPError,URLError,TimeoutError) as e:
            last=e
            if i==0: time.sleep(1)
    raise last

def clean(s): return re.sub(r'\s+',' ',unescape(re.sub(r'<[^>]+>',' ',s or ''))).strip()

def search(q,max_pages=50):
    rows=[]; seen=set(); archived=0; first=''; stopped=''
    for page in range(1,max_pages+1):
        url=BASE+'?'+urlencode({'query':q,'page':page})
        html,final=get(url)
        if page==1: first=final
        safe=re.sub(r'[^a-z0-9]+','_',q.lower()).strip('_')
        (OUT/f'{safe}_page_{page:03d}.html').write_text(html,encoding='utf-8'); archived+=1
        found=0
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']*/article/view/[^"\']+)["\'][^>]*>(.*?)</a>',html,re.I|re.S):
            href=urljoin(final,m.group(1)).split('?')[0].rstrip('/'); title=clean(m.group(2))
            if not title or href in seen: continue
            seen.add(href); rows.append({'query':q,'title':title,'url':href}); found+=1
        # OJS next page patterns
        has_next=bool(re.search(r'rel=["\']next["\']',html,re.I)) or bool(re.search(r'class=["\'][^"\']*next[^"\']*["\']',html,re.I))
        if not has_next:
            stopped='NO_NEXT'; break
        if found==0 and page>1:
            stopped='NO_NEW_RESULTS'; break
        time.sleep(0.1)
    else: stopped='MAX_PAGES'
    return rows,{'query':q,'retrieved_unique_article_links':len(rows),'pages_archived':archived,'first_url':first,'stop_reason':stopped,'status':'OK'}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    logs=[]; union={}
    for q in QUERIES:
        try:
            rows,log=search(q); logs.append(log)
            for r in rows:
                key=r['url']
                if key not in union: union[key]={'title':r['title'],'url':key,'queries':[q]}
                elif q not in union[key]['queries']: union[key]['queries'].append(q)
        except Exception as e:
            logs.append({'query':q,'status':'FAILED','error':repr(e)})
    qpath=OUT/'BanglaJOL_Native_6_Search_Log_2026-09-02.csv'
    fields=['query','retrieved_unique_article_links','pages_archived','first_url','stop_reason','status','error']
    with qpath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in logs: w.writerow({k:r.get(k,'') for k in fields})
    upath=OUT/'BanglaJOL_Native_6_Search_Union_2026-09-02.csv'
    with upath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['title','url','queries']); w.writeheader()
        for r in sorted(union.values(),key=lambda x:x['title'].lower()): w.writerow({'title':r['title'],'url':r['url'],'queries':' | '.join(r['queries'])})
    summary={'successful_queries':sum(r.get('status')=='OK' for r in logs),'failed_queries':sum(r.get('status')=='FAILED' for r in logs),'union_unique':len(union),'query_log_sha256':sha(qpath),'union_sha256':sha(upath)}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2)); [print(json.dumps(r,ensure_ascii=False)) for r in logs]

if __name__=='__main__': main()
