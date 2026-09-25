"""Audit whether fixed-case B2 artifacts support authenticated storage edges."""
from __future__ import annotations
import argparse,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def audit_case(path:Path):
    d=json.loads(path.read_text()); tx=next((x for x in d.get("per_tx",[]) if x.get("call_trace")),None)
    if not tx: return {"status":"NO_CALL_TRACE"}
    telemetry = tx.get("opcode_telemetry", [])
    has_struct=False; has_context=False; has_stack=False; has_frame=False
    if isinstance(telemetry, list) and telemetry:
        for item in telemetry:
            if isinstance(item,dict):
                has_struct=True
                has_context |= isinstance(item.get("storage_context"),str)
                has_stack |= isinstance(item.get("stack"),list)
                has_frame |= isinstance(item.get("frame_id"),str)
    for item in tx.get("structLogs",[]):
        if isinstance(item,dict):
            has_struct=True; has_context |= isinstance(item.get("storageContextAddress"),str); has_stack |= isinstance(item.get("stack"),list); has_frame |= isinstance(item.get("frameId"),str)
    if has_struct and has_context and has_stack and has_frame:
        status="FULL_STORAGE_PROVENANCE_READY"
    elif tx.get("opcode_tail"):
        status="OPCODE_TAIL_ONLY"
    else:
        status="NO_OPCODE_TELEMETRY"
    return {"status":status,"call_trace_entries":len(tx.get("call_trace",[])),"opcode_tail_entries":len(tx.get("opcode_tail",[])),"opcode_telemetry_entries":len(telemetry) if isinstance(telemetry,list) else 0,"structlog_entries":len(tx.get("structLogs",[])),"capabilities":{"structLogs":has_struct,"stack":has_stack,"frameId":has_frame,"storageContextAddress":has_context,"authenticated_opcode_telemetry":bool(telemetry)}}

def run(root=ROOT):
 out=[]
 base=root/"eval/results/m4/b2-contexts-fresh"
 for p in sorted(base.glob("*/b2-replay-m4.json")):
  out.append({"case_id":p.parent.name,**audit_case(p)})
 counts={}
 for x in out: counts[x["status"]]=counts.get(x["status"],0)+1
 return {"schema_version":"e5-opcode-telemetry-audit-v1","scope":"fixed-20 B2 artifacts","cases":out,"summary":{"case_count":len(out),"status_counts":counts,"storage_provenance_ready":counts.get("FULL_STORAGE_PROVENANCE_READY",0),"causal_storage_edges_authorized":False},"policy":"depth/to/DELEGATECALL inference is not accepted as storage provenance"}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("-o","--output",type=Path,required=True); a=ap.parse_args(); a.output.write_text(json.dumps(run(),indent=2)+"\n")
if __name__=="__main__": main()
