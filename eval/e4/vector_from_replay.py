"""Build comparable committed harm vectors from B2 replay rows."""
from eval.attacker_set_v2 import derive
from eval.e4.harm_vector import from_flows
TRANSFER='0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
def flows(row):
    out=[]
    for log in row.get('logs') or []:
        topics=log.get('topics') or []
        if len(topics)>=3 and topics[0].lower()==TRANSFER:
            out.append({'token':log.get('address','').lower(),'from':'0x'+topics[1][-40:].lower(),'to':'0x'+topics[2][-40:].lower(),'amount_raw':int(log.get('data','0x0'),16)})
    for b in row.get('balance_changes') or []:
        a=str(b.get('address','')).lower(); prev=int(str(b.get('previous','0')),0); cur=int(str(b.get('current','0')),0); d=cur-prev
        if d: out.append({'token':'eth','from':a if d<0 else '0x'+'0'*40,'to':a if d>0 else '0x'+'0'*40,'amount_raw':abs(d)})
    return out
def vector(row, infra=()):
    trace=row.get('call_trace') or []; sender=next((x.get('from') for x in trace if x.get('event')=='enter' and x.get('depth')==0),None)
    attackers,_=derive(trace,sender); infra={x.lower() for x in infra}; fs=flows(row); protected={x for f in fs for x in (f['from'].lower(),f['to'].lower()) if x not in attackers and x not in infra and x!='0x'+'0'*40}
    return from_flows(fs,attackers,protected),attackers,protected
