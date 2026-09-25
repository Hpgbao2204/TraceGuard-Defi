"""Address/asset terminal-delta vector for differential harm comparison."""
import json
from pathlib import Path
from dataclasses import dataclass

_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = json.loads((_ROOT / 'eval/e4/hard_assets_v1.json').read_text())
_HARD_ADDRESSES = {str(x['address']).lower() for x in _REGISTRY['assets'] if x.get('address')}
_HARD_SYMBOLS = {str(x['symbol']).lower() for x in _REGISTRY['assets']}

@dataclass(frozen=True)
class HarmVector:
    resolver_version: str
    boundary_id: str
    tier: str
    hard_asset_registry: str
    hard: dict
    exotic: dict
    liability: dict
    completeness: str = 'COMPLETE'

    def json(self):
        return {'resolver_version':self.resolver_version,'boundary_id':self.boundary_id,
          'tier':self.tier,'hard_asset_registry':self.hard_asset_registry,
          'hard':{f'{a}|{t}':str(v) for (a,t),v in self.hard.items()},
          'exotic':{f'{a}|{t}':str(v) for (a,t),v in self.exotic.items()},
          'liability':{f'{a}|{t}':str(v) for (a,t),v in self.liability.items()},
          'completeness':self.completeness}

def from_flows(flows, attackers, protected, *, resolver_version='t0-v2', boundary_id='auto-complement-v1', tier='T0', registry='hard-assets-v1'):
    hard={}; exotic={}
    for f in flows:
        src=str(f.get('from','')).lower(); dst=str(f.get('to','')).lower(); token=str(f.get('token','')).lower(); amount=int(f.get('amount_raw',0))
        for addr,sign in ((src,-1),(dst,1)):
            if addr not in protected: continue
            # ERC-20 flows are keyed by contract address in traces.  Native
            # ETH is represented by the explicit ``eth`` token marker.
            target=hard if token == 'eth' or token in _HARD_ADDRESSES or token in _HARD_SYMBOLS else exotic
            key=(addr,token); target[key]=target.get(key,0)+sign*amount
    return HarmVector(resolver_version,boundary_id,tier,registry,hard,exotic,{},'COMPLETE')
