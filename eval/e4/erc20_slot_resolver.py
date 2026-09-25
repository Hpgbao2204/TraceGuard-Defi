"""Proof-bound mapping-slot resolver for ERC-20 balances."""
from eval.necessity import _keccak256
import subprocess
def _evm_keccak(data):
    try: return _keccak256(data)
    except ModuleNotFoundError:
        out=subprocess.check_output(['cast','keccak','0x'+data.hex()],text=True).strip()
        return bytes.fromhex(out.removeprefix('0x'))
def resolve_balance_slot(token, prestate, proofs, addresses, max_slot=32):
    token=token.lower(); hits=[]
    storage=prestate.get(token,prestate.get(token.lower(),{})).get('storage',{})
    proof_slots=set()
    for item in proofs if isinstance(proofs,list) else []:
        if item.get('address','').lower()==token:
            proof_slots.update(str(raw).lower() for raw in item.get('storage_keys',[]))
    for i in range(max_slot+1):
        found=[]
        for a in addresses:
            raw=bytes.fromhex(a[2:].lower().zfill(64))+int(i).to_bytes(32,'big')
            try: key='0x'+_evm_keccak(raw).hex()
            except (FileNotFoundError, subprocess.CalledProcessError): raise ValueError('SLOT_UNRESOLVED: keccak backend unavailable')
            if key in {str(k).lower() for k in storage}: found.append((a.lower(),key))
        if len(found)>=2 and all(k in proof_slots for _,k in found): hits.append((i,found))
    if len(hits)!=1: raise ValueError('SLOT_UNRESOLVED')
    return {'slot_index':hits[0][0],'hits':hits[0][1]}
