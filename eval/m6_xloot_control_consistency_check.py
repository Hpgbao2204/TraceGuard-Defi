import json
from pathlib import Path

CONTROL = Path("eval/results/m6_xloot_historical_control_1e30cff6.json")
OUT = Path("eval/results/m6_xloot_control_consistency_check.json")

d = json.loads(CONTROL.read_text())
e = d["entitlement"]
computed = sum(int(x) for x in e["epoch_rewards_1_2"]) * len(e["prestate_cursors"])
recorded = int(e["authorized_payout"])
observed = int(e["observed_protected_debit"])
residual = observed - recorded
result = {
    "schema_version": 1,
    "status": "PASS" if computed == recorded and residual == int(e["reconciliation_residual"]) else "FAIL",
    "computed_authorized_payout": str(computed),
    "recorded_authorized_payout": str(recorded),
    "observed_protected_debit": str(observed),
    "computed_residual": str(residual),
    "recorded_residual": e["reconciliation_residual"],
    "checks": {
        "computed_equals_recorded": computed == recorded,
        "residual_equals_recorded": residual == int(e["reconciliation_residual"])
    },
    "scope": "control arithmetic consistency only; not reviewer adjudication or causal evidence"
}
OUT.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
