#!/usr/bin/env python3
import json, re, xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UA='SRMA-Bangladesh-NewPubMed-Fulltext/1.0'
OUT=Path('new_pubmed_fulltext'); OUT.mkdir(exist_ok=True)
RECORDS=[
 {'pmid':'42676577','doi':'10.1002/hsr2.73160','label':'Bridging Equity Gaps'},
 {'pmid':'42646680','doi':'10.3390/vaccines14080661','label':'Pharmacist paediatric vaccination review'},
]

def get(url, accept='*/*'):
    req=Request(url,headers={'User-Agent':UA,'Accept':accept})
    with urlopen(req,timeout=120) as r: return r.read(),r.geturl()

def idconv(pmid):
    url='https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?'+urlencode({'ids':pmid,'format':'json'})
    raw,_=get(url,'application/json'); return json.loads(raw.decode())

def oai(pmcid):
    num=pmcid.replace('PMC','')
    url='https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?'+urlencode({'verb':'GetRecord','identifier':'oai:pubmedcentral.nih.gov:'+num,'metadataPrefix':'pmc'})
    raw,final=get(url,'application/xml,text/xml'); return raw,final

def node_text(node):
    return re.sub(r'\s+',' ',' '.join(''.join(x.itertext()) for x in [node])).strip()

def extract(xmlbytes):
    root=ET.fromstring(xmlbytes)
    article=root.find('.//article')
    if article is None: return {'error':'article element not found'}
    title=node_text(article.find('.//article-title')) if article.find('.//article-title') is not None else ''
    abstract=' '.join(node_text(x) for x in article.findall('.//abstract//p'))
    paragraphs=[node_text(x) for x in article.findall('.//body//p')]
    tables=[]
    for tw in article.findall('.//table-wrap'):
        label=node_text(tw.find('./label')) if tw.find('./label') is not None else ''
        cap=node_text(tw.find('./caption')) if tw.find('./caption') is not None else ''
        table_txt=node_text(tw)
        tables.append({'label':label,'caption':cap,'text':table_txt})
    terms=['immuniz','vaccin','12–23','12-23','12 to 23','fully vaccin','full vaccin','complete vaccin','bdhs 2022','2022 bdhs','zero-dose','zero dose','child']
    hits=[]
    for i,p in enumerate(paragraphs):
        lp=p.lower()
        matched=[t for t in terms if t.lower() in lp]
        if matched: hits.append({'paragraph_index':i+1,'matched':matched,'text':p})
    thits=[]
    for t in tables:
        lt=t['text'].lower(); matched=[term for term in terms if term.lower() in lt]
        if matched: thits.append({**t,'matched':matched})
    return {'title':title,'abstract':abstract,'paragraph_count':len(paragraphs),'table_count':len(tables),'keyword_paragraphs':hits,'keyword_tables':thits}

def main():
    summary=[]
    for rec in RECORDS:
        row=dict(rec)
        try:
            conv=idconv(rec['pmid']); row['idconv']=conv
            rs=conv.get('records') or []
            pmcid=(rs[0].get('pmcid') if rs else None)
            row['pmcid']=pmcid
            if not pmcid:
                row['status']='NO_PMC_FULLTEXT'; summary.append(row); continue
            raw,url=oai(pmcid); xmlpath=OUT/f"PMID_{rec['pmid']}_{pmcid}.xml"; xmlpath.write_bytes(raw)
            ext=extract(raw); row['oai_url']=url; row['status']='FULLTEXT_RETRIEVED'; row['extraction']=ext
            (OUT/f"PMID_{rec['pmid']}_extraction.json").write_text(json.dumps(ext,indent=2,ensure_ascii=False),encoding='utf-8')
        except Exception as e:
            row['status']='FAILED'; row['error']=repr(e)
        summary.append(row)
    (OUT/'new_pubmed_fulltext_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__': main()
