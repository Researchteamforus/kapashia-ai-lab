#!/usr/bin/env python3
import hashlib, json, re, subprocess
from pathlib import Path
from urllib.request import Request, urlopen

URLS=[
 ('NIPORT_Oracle_candidate','https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-niport/2024/12/5772635b052d4199b614df673b87b3ee.pdf'),
 ('Bangladesh_Gov_Portal_candidate','https://file-dhaka.portal.gov.bd/uploads/2885ee76-3129-49f9-b843-2e0839793d0d/695/0ff/a02/6950ffa02e5d9870851855.pdf'),
 ('DHS_FR386_candidate','https://preview.dhsprogram.com/pubs/pdf/FR386/FR386.pdf'),
]
UA='Mozilla/5.0 SRMA-BDHS2022-Verification/1.1'
OUT=Path('bdhs2022_verification'); OUT.mkdir(exist_ok=True)

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def download_one(label,url):
    req=Request(url,headers={'User-Agent':UA,'Accept':'application/pdf,*/*'})
    with urlopen(req,timeout=240) as r: data=r.read()
    if len(data)<500000 or data[:4]!=b'%PDF': raise RuntimeError(f'not a usable PDF: {len(data)} bytes')
    p=OUT/f'{label}.pdf'; p.write_bytes(data)
    txt=OUT/f'{label}.txt'
    subprocess.run(['pdftotext','-layout',str(p),str(txt)],check=True)
    t=txt.read_text(encoding='utf-8',errors='replace')
    score=sum(len(re.findall(pat,t,re.I)) for pat in [r'vaccinat',r'immuniz|immunis',r'12[–-]23',r'full basic',r'all basic',r'fully vaccin',r'vaccination coverage'])
    return {'label':label,'url':url,'pdf':str(p),'txt':str(txt),'size':len(data),'sha256':sha(p),'score':score,'text':t}

def main():
    candidates=[]; failures=[]
    for label,url in URLS:
        try:
            c=download_one(label,url); candidates.append(c)
            print(f"CANDIDATE {label}: score={c['score']} size={c['size']} sha256={c['sha256']}")
        except Exception as e:
            failures.append({'label':label,'url':url,'error':repr(e)})
            print(f'FAILED {label}: {e!r}')
    if not candidates: raise RuntimeError(f'No PDF candidate succeeded: {failures}')
    # Select the report with the richest vaccination-specific text rather than the first PDF.
    chosen=max(candidates,key=lambda x:x['score'])
    t=chosen['text']; lines=t.splitlines()
    pats=[r'fully vaccinated',r'full basic',r'all basic',r'12[–-]23 months',r'vaccination coverage',r'no vaccinations',r'national schedule',r'basic antigens',r'age 12[–-]23']
    hitidx=set()
    for i,line in enumerate(lines):
        if any(re.search(p,line,re.I) for p in pats): hitidx.update(range(max(0,i-18),min(len(lines),i+50)))
    excerpt='\n'.join(f'{i+1:06d}: {lines[i]}' for i in sorted(hitidx))
    (OUT/'BDHS2022_vaccination_excerpt.txt').write_text(excerpt,encoding='utf-8')
    clues=[]
    for i,line in enumerate(lines):
        if re.search(r'fully vaccinated|full basic|all basic|12[–-]23 months|no vaccinations|basic antigens',line,re.I): clues.append({'line':i+1,'text':line.strip()})
    summary={
        'selected_label':chosen['label'],'source_url':chosen['url'],'pdf_size_bytes':chosen['size'],'pdf_sha256':chosen['sha256'],
        'selection_score':chosen['score'],'text_lines':len(lines),'candidate_scores':[{k:c[k] for k in ['label','url','size','sha256','score']} for c in candidates],
        'failures':failures,'clues':clues[:500]
    }
    (OUT/'BDHS2022_verification_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    print('\n--- EXCERPT START ---\n'+excerpt[:100000])

if __name__=='__main__': main()
