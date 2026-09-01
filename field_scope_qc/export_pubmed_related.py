#!/usr/bin/env python3
import csv, hashlib, json, re, time
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

UA = 'SRMA-Bangladesh-PubMed-Related/1.0 (systematic review evidence export)'
OUT = Path('pubmed_related_exports')
OUT.mkdir(exist_ok=True)

PUBMED_QUERY = '(("Bangladesh"[Mesh] OR Bangladesh*[tiab]) AND ("Immunization Programs"[Mesh] OR "Vaccination"[Mesh] OR immuni*[tiab] OR vaccinat*[tiab] OR "expanded programme on immunization"[tiab] OR EPI[tiab]) AND ("Infant"[Mesh] OR "Child, Preschool"[Mesh] OR infant*[tiab] OR child*[tiab] OR newborn*[tiab] OR under-five[tiab] OR toddler*[tiab]) AND (coverage[tiab] OR uptake[tiab] OR timeliness[tiab] OR timely[tiab] OR delay*[tiab] OR dropout[tiab] OR "zero dose"[tiab] OR zero-dose[tiab] OR unvaccinated[tiab] OR incomplete[tiab] OR partial*[tiab] OR "missed opportunit*"[tiab] OR barrier*[tiab] OR determinant*[tiab] OR inequ*[tiab] OR access*[tiab] OR "service delivery"[tiab]))'

# Protocol-governed thematic seeds: coverage/full vaccination, dropout/incomplete/zero-dose,
# programme delivery/intervention, and current outbreak/context. Seeds are reports already
# represented or handled in the SRMA project; this route is for related-record discovery only.
SEEDS = [
    {'label':'RF-055 coverage/seroprevalence', 'doi':'10.1371/journal.pmed.1003071'},
    {'label':'RF-052 dropout', 'doi':'10.3329/ewmcj.v12i1.77174'},
    {'label':'RF-064 flood/incomplete vaccination', 'doi':'10.64898/2026.02.11.26346067'},
    {'label':'RF-065 measles dropout', 'doi':'10.64898/2025.12.18.25342636'},
    {'label':'RF-061 BDHS full vaccination', 'doi':'10.1136/bmjopen-2025-106039'},
    {'label':'RF-059 programme analysis', 'doi':'10.3389/fpubh.2021.738623'},
    {'label':'RF-063 programme/intervention', 'doi':'10.1177/1010539508327030'},
    {'label':'current intervention/stakeholder', 'pmid':'40555405'},
    {'label':'current outbreak commentary handled', 'pmid':'42456565'},
    {'label':'current outbreak/context', 'doi':'10.1016/j.microb.2026.100759'},
]

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for c in iter(lambda: f.read(1024*1024), b''):
            h.update(c)
    return h.hexdigest()

def get(url, attempts=5, accept='application/json'):
    last = None
    for i in range(attempts):
        try:
            req = Request(url, headers={'User-Agent':UA, 'Accept':accept})
            with urlopen(req, timeout=120) as r:
                return r.read(), r.geturl()
        except (HTTPError, URLError, TimeoutError) as e:
            last = e
            if i+1 < attempts:
                time.sleep(3*(i+1))
    raise last

def get_json(base, params):
    raw, final_url = get(base + '?' + urlencode(params))
    return json.loads(raw.decode('utf-8')), final_url

def normalize_title(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()

def reconstruct_abstract(inv):
    if not inv:
        return ''
    parts=[]
    for word, positions in inv.items():
        for pos in positions:
            parts.append((pos, word))
    parts.sort()
    return ' '.join(w for _,w in parts)

def pubmed_export():
    es_base='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
    data, first_url = get_json(es_base, {'db':'pubmed','term':PUBMED_QUERY,'retmode':'json','retmax':100000,'sort':'pub date'})
    es = data['esearchresult']
    ids = es.get('idlist', [])
    count = int(es.get('count', 0))
    (OUT/'PubMed_Final_Update_2026-09-01_ids.txt').write_text('\n'.join(ids)+'\n', encoding='utf-8')

    nbib = OUT/'PubMed_Final_Update_2026-09-01.nbib'
    with nbib.open('wb') as fout:
        for i in range(0, len(ids), 200):
            batch = ids[i:i+200]
            if not batch: continue
            params={'db':'pubmed','id':','.join(batch),'rettype':'medline','retmode':'text'}
            raw,_=get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?'+urlencode(params), accept='text/plain')
            fout.write(raw)
            if not raw.endswith(b'\n'):
                fout.write(b'\n')
            time.sleep(0.35)
    return {
        'source':'PubMed/MEDLINE', 'query':PUBMED_QUERY, 'raw_hit_count':count,
        'retrieved_ids':len(ids), 'first_url':first_url,
        'id_file':str(OUT/'PubMed_Final_Update_2026-09-01_ids.txt'),
        'nbib_file':str(nbib), 'nbib_sha256':sha256(nbib)
    }

def resolve_openalex_seed(seed):
    if seed.get('doi'):
        data,_=get_json('https://api.openalex.org/works', {'filter':'doi:https://doi.org/'+seed['doi'], 'per-page':1})
        rs=data.get('results',[])
        return rs[0] if rs else None
    if seed.get('pmid'):
        data,_=get_json('https://api.openalex.org/works', {'filter':'pmid:'+seed['pmid'], 'per-page':1})
        rs=data.get('results',[])
        return rs[0] if rs else None
    return None

def fetch_openalex_work(oa_id):
    raw,_=get('https://api.openalex.org/works/'+quote(oa_id, safe=':/'))
    return json.loads(raw.decode('utf-8'))

def related_export():
    raw_rows=[]
    seed_log=[]
    for seed in SEEDS:
        try:
            work=resolve_openalex_seed(seed)
            if not work:
                seed_log.append({**seed,'status':'NOT_RESOLVED'})
                continue
            rel=work.get('related_works') or []
            seed_log.append({**seed,'status':'RESOLVED','openalex_id':work.get('id'),'title':work.get('title'),'related_count':len(rel)})
            for rank, rid in enumerate(rel,1):
                try:
                    rw=fetch_openalex_work(rid)
                    ids=rw.get('ids') or {}
                    loc=rw.get('primary_location') or {}
                    src=(loc.get('source') or {}) if loc else {}
                    raw_rows.append({
                        'seed_label':seed['label'],'seed_openalex_id':work.get('id'),'related_rank':rank,
                        'openalex_id':rw.get('id'),'doi':(rw.get('doi') or '').replace('https://doi.org/',''),
                        'pmid':str(ids.get('pmid') or '').replace('https://pubmed.ncbi.nlm.nih.gov/','').strip('/'),
                        'title':rw.get('title') or rw.get('display_name') or '',
                        'year':rw.get('publication_year'),'source':src.get('display_name',''),
                        'abstract':reconstruct_abstract(rw.get('abstract_inverted_index')),
                        'cited_by_count':rw.get('cited_by_count',0)
                    })
                except Exception as e:
                    raw_rows.append({'seed_label':seed['label'],'seed_openalex_id':work.get('id'),'related_rank':rank,'openalex_id':rid,'fetch_error':repr(e)})
                time.sleep(0.12)
        except Exception as e:
            seed_log.append({**seed,'status':'FAILED','error':repr(e)})

    raw_path=OUT/'Related_Articles_OpenAlex_AllSeeds_2026-09-01.jsonl'
    with raw_path.open('w',encoding='utf-8') as f:
        for r in raw_rows:
            f.write(json.dumps(r,ensure_ascii=False)+'\n')
    (OUT/'Related_Articles_Seed_Log_2026-09-01.json').write_text(json.dumps(seed_log,indent=2,ensure_ascii=False),encoding='utf-8')

    # Cross-seed exact dedup only; no machine exclusion. Preserve provenance of every seed.
    uniq={}
    for r in raw_rows:
        if r.get('fetch_error'): continue
        key=('doi',r['doi'].lower()) if r.get('doi') else (('pmid',r['pmid']) if r.get('pmid') else ('title',normalize_title(r.get('title'))))
        if key not in uniq:
            x=dict(r); x['seed_labels']=[r['seed_label']]; x['seed_hits']=1; uniq[key]=x
        else:
            uniq[key]['seed_hits'] += 1
            if r['seed_label'] not in uniq[key]['seed_labels']:
                uniq[key]['seed_labels'].append(r['seed_label'])
    dedup=list(uniq.values())
    dedup.sort(key=lambda x:(-x.get('seed_hits',0),-int(x.get('cited_by_count') or 0),x.get('title','')))
    csv_path=OUT/'Related_Articles_OpenAlex_Dedup_2026-09-01.csv'
    fields=['openalex_id','doi','pmid','title','year','source','seed_hits','seed_labels','cited_by_count','abstract']
    with csv_path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in dedup:
            rr={k:r.get(k,'') for k in fields}; rr['seed_labels']=' | '.join(r.get('seed_labels',[])); w.writerow(rr)
    return {
        'route':'Related articles via OpenAlex related_works','run_date':'2026-09-01','seed_count':len(SEEDS),
        'seeds_resolved':sum(1 for s in seed_log if s.get('status')=='RESOLVED'),
        'raw_related_links':len(raw_rows),'cross_seed_exact_unique':len(dedup),
        'raw_export':str(raw_path),'raw_sha256':sha256(raw_path),
        'dedup_export':str(csv_path),'dedup_sha256':sha256(csv_path),
        'seed_log':str(OUT/'Related_Articles_Seed_Log_2026-09-01.json')
    }

def main():
    summaries=[]
    for name,fn in [('PubMed',pubmed_export),('Related articles',related_export)]:
        try:
            s=fn(); summaries.append(s); print(json.dumps(s,indent=2,ensure_ascii=False))
        except Exception as e:
            err={'source':name,'status':'FAILED','error':repr(e)}; summaries.append(err); print(json.dumps(err,indent=2),flush=True)
    summary_path=OUT/'pubmed_related_summary.json'
    summary_path.write_text(json.dumps(summaries,indent=2,ensure_ascii=False),encoding='utf-8')
    return 0 if all(x.get('status')!='FAILED' for x in summaries) else 2

if __name__=='__main__':
    raise SystemExit(main())
