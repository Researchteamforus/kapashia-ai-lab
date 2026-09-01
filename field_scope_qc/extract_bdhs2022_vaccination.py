#!/usr/bin/env python3
import hashlib, re, subprocess, sys
from pathlib import Path
from urllib.request import Request, urlopen

URLS=[
 'https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-niport/2024/12/5772635b052d4199b614df673b87b3ee.pdf',
 'https://file-dhaka.portal.gov.bd/uploads/2885ee76-3129-49f9-b843-2e0839793d0d/695/0ff/a02/6950ffa02e5d9870851855.pdf',
 'https://preview.dhsprogram.com/pubs/pdf/FR386/FR386.pdf'
]
UA='Mozilla/5.0 SRMA-BDHS2022-Verification/1.0'
OUT=Path('bdhs2022_verification'); OUT.mkdir(exist_ok=True)
pdf=OUT/'Bangladesh_DHS_2022_Final_Report.pdf'

def download():
    errors=[]
    for u in URLS:
        try:
            req=Request(u,headers={'User-Agent':UA,'Accept':'application/pdf,*/*'})
            with urlopen(req,timeout=180) as r:
                data=r.read()
            if len(data)>1000000 and data[:4]==b'%PDF':
                pdf.write_bytes(data); return u,len(data)
            errors.append((u,'not_pdf_or_too_small',len(data)))
        except Exception as e: errors.append((u,repr(e)))
    raise RuntimeError(errors)

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    src,size=download()
    txt=OUT/'Bangladesh_DHS_2022_Final_Report.txt'
    subprocess.run(['pdftotext','-layout',str(pdf),str(txt)],check=True)
    lines=txt.read_text(encoding='utf-8',errors='replace').splitlines()
    pats=[r'fully vaccinated',r'full basic',r'all basic',r'12[–-]23 months',r'vaccination coverage',r'no vaccinations',r'national schedule']
    hitidx=set()
    for i,line in enumerate(lines):
        if any(re.search(p,line,re.I) for p in pats):
            hitidx.update(range(max(0,i-12),min(len(lines),i+30)))
    excerpt='\n'.join(f'{i+1:06d}: {lines[i]}' for i in sorted(hitidx))
    (OUT/'BDHS2022_vaccination_excerpt.txt').write_text(excerpt,encoding='utf-8')
    # A compact structured clue list for audit.
    clues=[]
    for i,line in enumerate(lines):
        if re.search(r'fully vaccinated|all basic|12[–-]23 months|no vaccinations',line,re.I):
            clues.append({'line':i+1,'text':line.strip()})
    import json
    summary={'source_url':src,'pdf_size_bytes':size,'pdf_sha256':sha(pdf),'text_lines':len(lines),'clues':clues[:300]}
    (OUT/'BDHS2022_verification_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    print('\n--- EXCERPT START ---\n')
    print(excerpt[:60000])

if __name__=='__main__': main()
