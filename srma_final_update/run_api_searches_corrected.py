#!/usr/bin/env python3
"""
SRMA final-update API runner
- OpenAlex: protocol-aligned Boolean search + cursor pagination
- Europe PMC: protocol-aligned query + cursorMark pagination
- Writes reproducible raw exports and run metadata
- Does NOT make screening decisions
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

OPENALEX_QUERY = ('Bangladesh AND (immunization OR vaccination OR EPI) AND (child OR infant) AND (coverage OR timeliness OR dropout OR "zero dose" OR incomplete OR determinant)')
EUROPE_PMC_QUERY = ('(Bangladesh) AND (immunization OR immunisation OR vaccination OR vaccine) AND (child OR infant OR newborn OR under-five) AND (coverage OR timeliness OR dropout OR "zero dose" OR zero-dose OR incomplete OR uptake OR barrier OR determinant OR equity)')
USER_AGENT = 'SRMA-Bangladesh-FinalUpdate/1.0'

def utc_now(): return datetime.now(timezone.utc).isoformat()
def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def http_json(base_url, params, headers=None, timeout=60):
    url=base_url+'?'+urlencode(params)
    hdrs={'User-Agent':USER_AGENT,'Accept':'application/json'}
    if headers: hdrs.update(headers)
    with urlopen(Request(url,headers=hdrs), timeout=timeout) as resp:
        return json.load(resp), url

def run_openalex(outdir, count_only=False, sleep_s=1.1):
    api_key=os.getenv('OPENALEX_API_KEY','').strip()
    headers={'Authorization':f'Bearer {api_key}'} if api_key else {}
    params={'search':OPENALEX_QUERY,'per_page':100,'cursor':'*','select':'id,doi,title,publication_year,ids,authorships,primary_location,abstract_inverted_index,referenced_works,related_works'}
    data, first_url=http_json('https://api.openalex.org/works',params,headers=headers)
    total=int(data.get('meta',{}).get('count',0) or 0)
    meta={'source':'OpenAlex','run_utc':utc_now(),'query':OPENALEX_QUERY,'first_request_url_without_key':first_url,'raw_hit_count':total,'count_only':count_only,'retrieved_records':0}
    if count_only: return meta,None
    out=Path(outdir)/'OpenAlex_Final_Update_Corrected.jsonl'; written=0; next_cursor=data.get('meta',{}).get('next_cursor')
    with out.open('w',encoding='utf-8') as f:
        while True:
            for item in data.get('results',[]): f.write(json.dumps(item,ensure_ascii=False)+'\n'); written+=1
            if not next_cursor or not data.get('results'): break
            time.sleep(sleep_s); params['cursor']=next_cursor
            data,_=http_json('https://api.openalex.org/works',params,headers=headers); next_cursor=data.get('meta',{}).get('next_cursor')
    meta.update({'retrieved_records':written,'export_file':str(out),'sha256':sha256_file(out)}); return meta,out

def run_europe_pmc(outdir, count_only=False, sleep_s=0.15):
    params={'query':EUROPE_PMC_QUERY,'format':'json','resultType':'core','pageSize':1000,'cursorMark':'*','synonym':'false'}
    data, first_url=http_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',params)
    total=int(data.get('hitCount',0) or 0)
    meta={'source':'Europe PMC','run_utc':utc_now(),'query':EUROPE_PMC_QUERY,'first_request_url':first_url,'raw_hit_count':total,'count_only':count_only,'retrieved_records':0}
    if count_only: return meta,None
    out=Path(outdir)/'EuropePMC_Final_Update_Corrected.jsonl'; written=0
    with out.open('w',encoding='utf-8') as f:
        while True:
            items=data.get('resultList',{}).get('result',[])
            for item in items: f.write(json.dumps(item,ensure_ascii=False)+'\n'); written+=1
            nxt=data.get('nextCursorMark')
            if not items or not nxt: break
            params['cursorMark']=nxt; time.sleep(sleep_s); data,_=http_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',params)
    meta.update({'retrieved_records':written,'export_file':str(out),'sha256':sha256_file(out)}); return meta,out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--source',choices=['openalex','europepmc','both'],default='both'); ap.add_argument('--outdir',default='final_api_exports'); ap.add_argument('--count-only',action='store_true'); ap.add_argument('--dry-run',action='store_true'); args=ap.parse_args()
    outdir=Path(args.outdir); outdir.mkdir(parents=True,exist_ok=True)
    if args.dry_run:
        print(json.dumps({'OpenAlex':OPENALEX_QUERY,'Europe PMC':EUROPE_PMC_QUERY,'OpenAlex_API_key_present':bool(os.getenv('OPENALEX_API_KEY','').strip())},indent=2)); return 0
    summaries=[]
    try:
        if args.source in ('openalex','both'): summaries.append(run_openalex(outdir,args.count_only)[0])
        if args.source in ('europepmc','both'): summaries.append(run_europe_pmc(outdir,args.count_only)[0])
    except (HTTPError,URLError,TimeoutError,OSError) as e:
        print(f'NETWORK/API ERROR: {e}',file=sys.stderr); return 2
    (outdir/'api_run_summary.json').write_text(json.dumps(summaries,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(summaries,indent=2,ensure_ascii=False)); return 0

if __name__=='__main__': raise SystemExit(main())
