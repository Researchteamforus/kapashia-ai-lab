#!/usr/bin/env python3
import hashlib, json, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

UA='SRMA-Bangladesh-FieldScope-Export/1.0'
OPENALEX_OQL='works where title/abstract has (Bangladesh and (immunization or vaccination or EPI) and (child or infant) and (coverage or timeliness or dropout or "zero dose" or incomplete or determinant))'
EPMC_TITLE_ABS=' AND '.join([
 '(TITLE_ABS:Bangladesh)',
 '(TITLE_ABS:immunization OR TITLE_ABS:immunisation OR TITLE_ABS:vaccination OR TITLE_ABS:vaccine)',
 '(TITLE_ABS:child OR TITLE_ABS:infant OR TITLE_ABS:newborn OR TITLE_ABS:"under-five")',
 '(TITLE_ABS:coverage OR TITLE_ABS:timeliness OR TITLE_ABS:dropout OR TITLE_ABS:"zero dose" OR TITLE_ABS:"zero-dose" OR TITLE_ABS:incomplete OR TITLE_ABS:uptake OR TITLE_ABS:barrier OR TITLE_ABS:determinant OR TITLE_ABS:equity)'
])

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def get_json(base, params, attempts=5):
    url=base+'?'+urlencode(params)
    last=None
    for i in range(attempts):
        try:
            req=Request(url,headers={'User-Agent':UA,'Accept':'application/json'})
            with urlopen(req,timeout=120) as r: return json.load(r),url
        except (HTTPError,URLError,TimeoutError) as e:
            last=e
            if i+1<attempts: time.sleep(3*(i+1))
    raise last

def export_openalex(outdir):
    params={'oql':OPENALEX_OQL,'per-page':100,'cursor':'*','select':'id,doi,title,display_name,publication_year,ids,authorships,primary_location,abstract_inverted_index,referenced_works,related_works'}
    data,first_url=get_json('https://api.openalex.org/',params)
    total=int(data.get('meta',{}).get('count',0) or 0)
    out=Path(outdir)/'OpenAlex_TitleAbstract_ProtocolIntent_2026-09-01.jsonl'; n=0
    with out.open('w',encoding='utf-8') as f:
        while True:
            items=data.get('results',[])
            for item in items: f.write(json.dumps(item,ensure_ascii=False)+'\n'); n+=1
            nxt=data.get('meta',{}).get('next_cursor')
            if not items or not nxt: break
            params['cursor']=nxt; time.sleep(0.4); data,_=get_json('https://api.openalex.org/',params)
    return {'source':'OpenAlex','scope':'title/abstract OQL','query':OPENALEX_OQL,'raw_hit_count':total,'retrieved_records':n,'first_url':first_url,'export_file':str(out),'sha256':sha256(out)}

def export_epmc(outdir):
    params={'query':EPMC_TITLE_ABS,'format':'json','resultType':'core','pageSize':1000,'cursorMark':'*','synonym':'false'}
    data,first_url=get_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',params)
    total=int(data.get('hitCount',0) or 0)
    out=Path(outdir)/'EuropePMC_TITLE_ABS_ProtocolIntent_2026-09-01.jsonl'; n=0
    with out.open('w',encoding='utf-8') as f:
        while True:
            items=data.get('resultList',{}).get('result',[])
            for item in items: f.write(json.dumps(item,ensure_ascii=False)+'\n'); n+=1
            nxt=data.get('nextCursorMark')
            if not items or not nxt: break
            params['cursorMark']=nxt; time.sleep(0.3); data,_=get_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',params)
    return {'source':'Europe PMC','scope':'TITLE_ABS','query':EPMC_TITLE_ABS,'raw_hit_count':total,'retrieved_records':n,'first_url':first_url,'export_file':str(out),'sha256':sha256(out)}

def main():
    outdir=Path('field_scope_exports'); outdir.mkdir(exist_ok=True)
    summaries=[]
    for name,fn in [('OpenAlex',export_openalex),('Europe PMC',export_epmc)]:
        try:
            s=fn(outdir); summaries.append(s); print(json.dumps(s,indent=2,ensure_ascii=False))
        except Exception as e:
            err={'source':name,'status':'FAILED','error':repr(e)}; summaries.append(err); print(json.dumps(err,indent=2),flush=True)
    (outdir/'field_scope_export_summary.json').write_text(json.dumps(summaries,indent=2,ensure_ascii=False),encoding='utf-8')
    return 0 if all(x.get('status')!='FAILED' for x in summaries) else 2

if __name__=='__main__': raise SystemExit(main())
