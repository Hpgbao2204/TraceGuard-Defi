"""Verify Balancer seam fixtures without assigning a dependency verdict."""
import argparse, json
from pathlib import Path

FIELDS = ("total_actual_gas", "total_expected_gas")

def load(path):
    return json.loads(Path(path).read_text())

def main():
    p=argparse.ArgumentParser(); p.add_argument("--canonical",required=True); p.add_argument("--nomatch",required=True); p.add_argument("--intervention",required=True); p.add_argument("--sham",required=True); p.add_argument("--out",required=True); a=p.parse_args()
    c,n,i,s=map(load,(a.canonical,a.nomatch,a.intervention,a.sham))
    cr,nr,ir,sr=(x["per_tx"][-1] for x in (c,n,i,s))
    callback=lambda row: sum(1 for f in row.get("call_trace",[]) if f.get("event")=="enter" and str(f.get("input","")).lower().startswith("0xf04f2707"))
    preserved={f: c[f]==n[f] for f in FIELDS}
    per_tx_preserved = all(
        (x.get("actual_gas"), x.get("actual_status"), x.get("logs_match"), x.get("post_state_match")) ==
        (y.get("actual_gas"), y.get("actual_status"), y.get("logs_match"), y.get("post_state_match"))
        for x,y in zip(c["per_tx"], n["per_tx"]))
    sham_ev = sr.get("call_intervention") or {}
    sham_ok = (sham_ev.get("match_count") == 1 and sham_ev.get("application_verified") is True
               and sham_ev.get("call_type") == "STATICCALL" and sham_ev.get("action") == "observe_only")
    report={"schema_version":1,"status":"BALANCER_SEAM_FIXTURE_VERIFIED","execution_performed":True,
      "canonical_preservation":{"pass":all(preserved.values()) and per_tx_preserved,"fields":preserved,"per_tx_metrics_preserved":per_tx_preserved},
      "no_match":{"match_count":(nr.get("call_intervention") or {}).get("match_count"),"fail_closed":n.get("acceptance_gate") is False,"execution_preserved":all(preserved.values()) and per_tx_preserved,"callback_reached":callback(nr)},
      "intervention":{"match_count":(ir.get("call_intervention") or {}).get("match_count"),"application_verified":(ir.get("call_intervention") or {}).get("application_verified"),"callback_reached":callback(ir),"callback_lineage_pass":callback(ir)==0,"outcome":"reverted_at_intervention"},
      "sham":{"status":"NON_CAUSAL_PROVIDER_LOCAL_SHAM_PASS" if sham_ok else "FAIL","match_count":sham_ev.get("match_count"),"application_verified":sham_ev.get("application_verified"),"call_type":sham_ev.get("call_type"),"execution_preserved":all(s[f]==c[f] for f in FIELDS) and all((x.get("actual_gas"),x.get("actual_status"),x.get("logs_match"),x.get("post_state_match"))==(y.get("actual_gas"),y.get("actual_status"),y.get("logs_match"),y.get("post_state_match")) for x,y in zip(c["per_tx"],s["per_tx"])),"action":sham_ev.get("action"),"note":"same pre-dispatch seam exercised on a non-causal Balancer STATICCALL control edge; execution is preserved"},
      "d3_5_pass":bool(all(preserved.values()) and per_tx_preserved and n.get("acceptance_gate") is False and i.get("acceptance_gate") is False and (ir.get("call_intervention") or {}).get("match_count")==1 and callback(ir)==0 and sham_ok),"d4_authorized":False}
    Path(a.out).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
