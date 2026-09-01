#!/usr/bin/env python3
import argparse, json, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

UA='SRMA-Bangladesh-FieldScope-QC/1.1'
OPENALEX_OQL='works where title/abstract has (Bangladesh and (immunization or vaccination or EPI) and (child or infant) and (coverage or timeliness or dropout or "zero dose" or incomplete or determinant))'
EPMC_TITLE_ABS=' AND '.join([
 '(TITLE_ABS:Bangladesh)',
 '(TITLE_ABS:immunization OR TITLE_ABS:immunisation OR TITLE_ABS:vaccination OR TITLE_ABS:vaccine)',
 '(TITLE_ABS:child OR TITLE_ABS:infant OR TITLE_ABS:newborn OR TITLE_ABS:"under-five")',
 '(TITLE_ABS:coverage OR TITLE_ABS:timeliness OR TITLE_ABS:dropout OR TITLE_ABS:"zero dose" OR TITLE_ABS:"zero-dose" OR TITLE_ABS:incomplete OR TITLE_ABS:uptake OR TITLE_ABS:barrier OR TITLE_ABS:determinant OR TITLE_ABS:equity)'
])

def get_json(base, params, attempts=4):
    url=base+'?'+urlencode(params)
    last=None
    for i in range(attempts):
        try:
            req=Request(url,headers={'User-Agent':UA,'Accept':'application/json'})
            with urlopen(req,timeout=90) as r: return json.load(r),url
        except (HTTPError,URLError,TimeoutError) as e:
            last=e
            if i+1<attempts: time.sleep(3*(i+1))
    raise last

def run_oa():
    d,u=get_json('https://api.openalex.org/',{'oql':OPENALEX_OQL,'per-page':1})
    return {'source':'OpenAlex','scope':'title/abstract OQL','query':OPENALEX_OQL,'count':d.get('meta',{}).get('count'),'url':u,'x_query':d.get('meta',{}).get('x_query')}

def run_epmc():
    d,u=get_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',{'query':EPMC_TITLE_ABS,'format':'json','resultType':'lite','pageSize':1,'synonym':'false'})
    return {'source':'Europe PMC','scope':'TITLE_ABS','query':EPMC_TITLE_ABS,'count':d.get('hitCount'),'url':u}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--source',choices=['openalex','europepmc'],required=True); a=p.parse_args()
    out=run_oa() if a.source=='openalex' else run_epmc()
    print(json.dumps(out,indent=2,ensure_ascii=False))
if __name__=='__main__': main()
