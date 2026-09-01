#!/usr/bin/env python3
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UA='SRMA-Bangladesh-FieldScope-QC/1.0'

OPENALEX_OQL = 'works where title/abstract has (Bangladesh and (immunization or vaccination or EPI) and (child or infant) and (coverage or timeliness or dropout or "zero dose" or incomplete or determinant))'

EPMC_TITLE_ABS = ' AND '.join([
    '(TITLE_ABS:Bangladesh)',
    '(TITLE_ABS:immunization OR TITLE_ABS:immunisation OR TITLE_ABS:vaccination OR TITLE_ABS:vaccine)',
    '(TITLE_ABS:child OR TITLE_ABS:infant OR TITLE_ABS:newborn OR TITLE_ABS:"under-five")',
    '(TITLE_ABS:coverage OR TITLE_ABS:timeliness OR TITLE_ABS:dropout OR TITLE_ABS:"zero dose" OR TITLE_ABS:"zero-dose" OR TITLE_ABS:incomplete OR TITLE_ABS:uptake OR TITLE_ABS:barrier OR TITLE_ABS:determinant OR TITLE_ABS:equity)'
])

def get_json(url, params):
    req=Request(url+'?'+urlencode(params),headers={'User-Agent':UA,'Accept':'application/json'})
    with urlopen(req,timeout=90) as r:
        return json.load(r), req.full_url

def main():
    oa, oa_url = get_json('https://api.openalex.org/', {'oql':OPENALEX_OQL,'per-page':1})
    ep, ep_url = get_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search', {'query':EPMC_TITLE_ABS,'format':'json','resultType':'lite','pageSize':1,'synonym':'false'})
    out={
        'OpenAlex_title_abstract_OQL': {'query':OPENALEX_OQL,'count':oa.get('meta',{}).get('count'),'url':oa_url,'x_query':oa.get('meta',{}).get('x_query')},
        'EuropePMC_TITLE_ABS': {'query':EPMC_TITLE_ABS,'count':ep.get('hitCount'),'url':ep_url}
    }
    print(json.dumps(out,indent=2,ensure_ascii=False))

if __name__=='__main__': main()
