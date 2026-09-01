#!/usr/bin/env python3
import argparse,csv,hashlib,json
from collections import Counter
from pathlib import Path
DEC={'Include','Exclude','Unclear'}; CODES={f'R{i}' for i in range(1,9)}
ID=['Candidate_ID','Source_Route','Title','Year','DOI','PMID','OpenAlex_ID']
HF=['Human_Decision','Exclude_Reason_Code','Human_Rationale','Reviewer_Initials','Review_Date']
def clean(x): return (x or '').strip()
def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:
        r=csv.DictReader(f); return r.fieldnames or [],list(r)
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
def audit(label,fields,rows):
    miss=[x for x in ID+HF if x not in fields]
    if miss: raise ValueError(f'{label}: missing {miss}')
    if len(rows)!=59: raise ValueError(f'{label}: expected 59 rows, got {len(rows)}')
    ids=[clean(r['Candidate_ID']) for r in rows]
    if len(ids)!=len(set(ids)) or any(not x for x in ids): raise ValueError(f'{label}: bad Candidate_ID set')
    probs=[]
    for n,r in enumerate(rows,2):
        d=clean(r['Human_Decision']); c=clean(r['Exclude_Reason_Code']); e=[]
        if d not in DEC:e.append('decision')
        if d=='Exclude' and c not in CODES:e.append('exclude_code')
        if d!='Exclude' and c:e.append('code_should_blank')
        for x in ['Human_Rationale','Reviewer_Initials','Review_Date']:
            if not clean(r[x]):e.append(x)
        if e: probs.append({'row':n,'id':r['Candidate_ID'],'errors':e})
    return probs
def write(p,fields,rows):
    with open(p,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def main():
    a=argparse.ArgumentParser();a.add_argument('--r1',required=True);a.add_argument('--r2',required=True);a.add_argument('--outdir',required=True);x=a.parse_args();o=Path(x.outdir);o.mkdir(parents=True,exist_ok=True)
    f1,r1=read(x.r1);f2,r2=read(x.r2);p1=audit('R1',f1,r1);p2=audit('R2',f2,r2)
    if p1 or p2:
        (o/'FinalSearch_Validation_Report.json').write_text(json.dumps({'status':'FAILED_VALIDATION','r1':p1,'r2':p2},indent=2),encoding='utf-8');raise SystemExit('validation failed')
    b1={clean(r['Candidate_ID']):r for r in r1};b2={clean(r['Candidate_ID']):r for r in r2}
    if set(b1)!=set(b2):raise SystemExit('candidate sets differ')
    for cid in b1:
        for k in ID:
            if clean(b1[cid].get(k))!=clean(b2[cid].get(k)):raise SystemExit(f'identity mismatch {cid} {k}')
    af=ID+['R1_Decision','R1_Reason_Code','R1_Rationale','R2_Decision','R2_Reason_Code','R2_Rationale','Agreement_Type']
    cf=ID+['Machine_Suggested_Decision','Machine_Suggested_Reason_Code','Machine_Suggestion_Confidence','Machine_Evidence','R1_Decision','R1_Reason_Code','R1_Rationale','R2_Decision','R2_Reason_Code','R2_Rationale','Disagreement_Type','Consensus_Decision','Consensus_Reason_Code','Consensus_Rationale','Consensus_Date','Status']
    agree=[];cons=[];mat=Counter();dd=rd=0
    for cid in sorted(b1):
        u,v=b1[cid],b2[cid];d1,d2=clean(u['Human_Decision']),clean(v['Human_Decision']);c1,c2=clean(u['Exclude_Reason_Code']),clean(v['Exclude_Reason_Code']);mat[(d1,d2)]+=1;base={k:clean(u.get(k)) for k in ID}
        if d1==d2 and (d1!='Exclude' or c1==c2):
            agree.append({**base,'R1_Decision':d1,'R1_Reason_Code':c1,'R1_Rationale':clean(u['Human_Rationale']),'R2_Decision':d2,'R2_Reason_Code':c2,'R2_Rationale':clean(v['Human_Rationale']),'Agreement_Type':'EXACT_DECISION_AND_REASON_AGREEMENT'});continue
        typ='DECISION_DISAGREEMENT' if d1!=d2 else 'EXCLUSION_CODE_DISAGREEMENT';dd+=d1!=d2;rd+=d1==d2
        cons.append({**base,'Machine_Suggested_Decision':clean(u.get('Machine_Suggested_Decision')),'Machine_Suggested_Reason_Code':clean(u.get('Machine_Suggested_Reason_Code')),'Machine_Suggestion_Confidence':clean(u.get('Machine_Suggestion_Confidence')),'Machine_Evidence':clean(u.get('Machine_Evidence')),'R1_Decision':d1,'R1_Reason_Code':c1,'R1_Rationale':clean(u['Human_Rationale']),'R2_Decision':d2,'R2_Reason_Code':c2,'R2_Rationale':clean(v['Human_Rationale']),'Disagreement_Type':typ,'Status':'PENDING_HUMAN_CONSENSUS'})
    write(o/'FinalSearch_59_Exact_Agreements.csv',af,agree);write(o/'FinalSearch_Disagreement_Consensus_READY.csv',cf,cons)
    s={'status':'VALIDATED_AND_RECONCILED','total_records':59,'exact_agreement':len(agree),'decision_disagreement':dd,'reason_code_disagreement':rd,'consensus_rows_required':len(cons),'decision_matrix':{f'{a}__vs__{b}':n for (a,b),n in mat.items()},'r1_sha256':sha(x.r1),'r2_sha256':sha(x.r2),'note':'No disagreement auto-adjudicated.'}
    (o/'FinalSearch_PostHuman_Summary.json').write_text(json.dumps(s,indent=2),encoding='utf-8');print(json.dumps(s,indent=2))
if __name__=='__main__':main()
