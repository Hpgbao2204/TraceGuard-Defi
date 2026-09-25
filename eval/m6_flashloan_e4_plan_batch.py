"""Build blind E4 mutation plans for proof-bound supplementary contexts."""
import json
from pathlib import Path
from core.env import load_dotenv, resolve_rpc_candidates, resolve_trace_rpc_candidates
from core.rpc import RpcClient
from eval.e4.models import Case
from eval.e4.planner import build_mutation_plan

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("Dough Finance", "dough-finance", "0x92cdcc732eebf47200ea56123716e337f6ef7d5ad714a2295794fdc6031ebb2e", 20288623),
    ("XPEPE", "xpepe", "0xbdec39a74e620fc624f90483aff067b17044f81138e6c30038daf7f873159db4", 21699659),
    ("Euler Finance", "euler-finance", "0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d", 16817996),
    ("Indexed Finance", "indexed-finance", "0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa", 13417949),
    ("Harvest Finance", "harvest-finance", "0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877", 11129474),
    ("KyberSwap Elastic", "kyberswap-elastic", "0x396a83df7361519416a6dc960d394e689dd0f158095cbc6a6c387640716f5475", 18630409),
    ("Bao Finance", "bao-finance", "0xdd7dd68cd879d07cfc2cb74606baa2a5bf18df0e3bda9f6b43f904f4f7bbdfc1", 17620871),
]

def serialize(m):
    return {k: v for k, v in vars(m).items() if not k.startswith('_')}

def main():
    load_dotenv()
    aurls, turls = resolve_rpc_candidates("mainnet"), resolve_trace_rpc_candidates("mainnet")
    archive = RpcClient(aurls[0], timeout=60, attempts=2, fallback_urls=aurls[1:])
    trace = RpcClient(turls[0], timeout=60, attempts=2, fallback_urls=turls[1:])
    rows=[]
    for name, slug, tx, block in CASES:
        case=Case(case_id=f"flashloan-{slug}-{block}", protocol=name, attack_type="flash-loan exploit", tx_hash=tx, block=block)
        try:
            plan=build_mutation_plan(case, archive=archive, trace_rpc=trace)
            rows.append({"name":name,"tx_hash":tx,"block":block,"status":"PLANNED","mutations":[serialize(x) for x in plan.mutations],"notes":plan.notes})
        except Exception as e:
            rows.append({"name":name,"tx_hash":tx,"block":block,"status":"PLANNER_ERROR","error_type":type(e).__name__,"error":str(e)[:240]})
    out=ROOT/"eval/results/m6_flashloan_e4_plan_batch.json"
    out.write_text(json.dumps({"schema_version":1,"scope":"supplementary; blind planning only; no mutation execution","cases":rows},indent=2,default=str)+"\n")
    print(json.dumps([{k:r.get(k) for k in ('name','status','mutations','error_type')} for r in rows],indent=2))
if __name__ == '__main__': main()
