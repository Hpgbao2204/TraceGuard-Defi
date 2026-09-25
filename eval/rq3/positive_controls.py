"""RQ3 positive control: a known security guard must be recovered by the pipeline.

Euler Finance (block 16817996, tx index 0): restore the missing liquidity
check in ``donateToReserves`` by replacing the EToken module runtime with the
source-compiled patch (euler-contracts PR 199, ``eval/fixtures``). Expected: the
counterfactual reverts in the Euler system with ``e/collateral-violation`` after
the patched module is entered, the whole-tx verdict is CAUSE_BLOCKED, and the
guard rule of ``eval.rq3.final_table`` classifies it as ``security``.

Euler dispatches to modules by DELEGATECALL, so the run classifies the reverting
frame by its storage context (``-delegate-context``); the fixed-20 runs do not.

bZx (Feb 2020, flash suppression) is not runnable yet: no script in this repo
builds its B2 context (see ``BZX_NEEDS``).

Usage (from the repository root)::

    python -m eval.rq3.positive_controls --exe .cache/framelocal.exe
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from eval.rq3.final_table import classify_guard
from eval.rq3.run_fixed20 import ROOT, check_context, interpret, sha256_file
from eval.rq3.selectors import name as selector_name

EULER = {
    "name": "euler-finance-16817996",
    "context": ROOT / "eval" / "results" / "runs" / "b2-context-flashloan-euler-finance-16817996",
    "tx_hash": "0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d",
    "tx_index": 0,
    # Euler main (proxy and module dispatcher), eDAI, dDAI, EToken module implementation.
    "victim": ["0x27182842e098f60e3d576794a5bffb0777e025d3", "0xe025e3ca2be02316033184551d4d3aa22024d9dc",
               "0x6085bc95f506c326dcbcd7a6dd6c79fbc18d4686", "0xbb0d4bb654a21054af95456a3b29c63e8d1f4c0a"],
    # Violator account from the incident harm spec; the tx sender is added by the runner.
    "attacker": ["0x583c21631c48d442b5c0e605d624f54a0b366c72"],
    "override": "0xbb0d4bb654a21054af95456a3b29c63e8d1f4c0a",
    "artifact": ROOT / "eval" / "fixtures" / "euler_pr199_etoken_artifact.json",
    "expected_message": "e/collateral-violation",
}

BZX_NEEDS = [
    "a B2 context for tx 0xb5c8bd9430b6cc87a0e2fe110ece6bf527fa4f170a4bc8cd032f768fc5219838 "
    "(block 9484688, tx index 28, 28 prior txs in the block): block.json, transactions.json, receipts, "
    "prestates.json, prestate_proofs.json, ancestors.json; eval/m6_flashloan_build_b2_contexts.py does not list bZx",
    "a proof that the shadow address 0x000000000000000000000000000000000000f1a1 is empty at the state block",
    "the guard runtime from eval/e4/b2_mutation.py _operate_guard_runtime(0x...f1a1, 'a67a6a45') written to a file, "
    "then -target-code-copy 0x...f1a1=0x1e0447b19bb6ecfdae1e4ae1694b0c3659614e4e "
    "-target-code 0x1e0447b19bb6ecfdae1e4ae1694b0c3659614e4e=@guard.hex",
    "an expected outcome: the revert then originates in the intervened provider, not in the victim, so the "
    "gated verdict is INCONCLUSIVE by design; the control would check loss = 0 and the revert site instead",
]


def euler_args(exe: str, context: Path, out: Path) -> list[str]:
    args = [exe, "-context", str(context), "-output", str(out), "-lean", "-target-index", str(EULER["tx_index"]),
            "-mode", "whole-tx", "-delegate-context",
            "-target-code", f"{EULER['override']}=@{EULER['artifact']}"]
    proofs = context / "prestate_proofs.json"
    if proofs.is_file():
        args += ["-proofs", str(proofs)]
    for v in EULER["victim"]:
        args += ["-victim", v]
    for a in EULER["attacker"]:
        args += ["-attacker", a]
    return args


def judge(rec: dict[str, Any]) -> dict[str, Any]:
    rv = rec.get("revert") or {}
    guard = classify_guard(rv) if rv else None
    checks = {
        "replay_gate": bool(rec.get("replay_gate")),
        "cause_blocked": rec.get("verdict") == "CAUSE_BLOCKED",
        "expected_message": (rv.get("revert_message") or "") == EULER["expected_message"],
        "guard_security": (guard or {}).get("type") == "security",
    }
    return {"passed": all(checks.values()), "checks": checks, "verdict": rec.get("verdict"), "reason": rec.get("reason"),
            "revert_message": rv.get("revert_message"), "revert_fn": selector_name(rv.get("origin_selector")),
            "origin": rv.get("origin_address"), "origin_context": rv.get("origin_context"), "guard": guard}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True)
    ap.add_argument("--euler-context", type=Path, default=EULER["context"])
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "rq3_controls")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {"exe_sha256": sha256_file(Path(args.exe)),
                              "artifact_sha256": sha256_file(EULER["artifact"]),
                              "bzx": {"status": "not_runnable", "needs": BZX_NEEDS}}
    bad = check_context(args.euler_context, {"tx_index": EULER["tx_index"], "tx_hash": EULER["tx_hash"]})
    if bad:
        report["euler"] = {"status": "missing_context", "detail": bad, "context": str(args.euler_context)}
    else:
        out = args.out / "euler.whole-tx.json"
        proc = subprocess.run(euler_args(args.exe, args.euler_context, out), capture_output=True, text=True,
                              timeout=args.timeout)
        if proc.returncode != 0:
            (args.out / "euler.stderr.txt").write_text(proc.stderr[-20000:], encoding="utf-8")
            report["euler"] = {"status": "runner_error", "exit": proc.returncode}
        else:
            payload = json.loads(out.read_text(encoding="utf-8"))
            rec = interpret(payload, "whole-tx")
            report["euler"] = {"status": "ran", "baseline_target_match": payload.get("baseline_target_match"),
                               **judge(rec)}
    (args.out / "controls.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    e = report["euler"]
    print(f"euler: {e.get('status')}  passed={e.get('passed')}  verdict={e.get('verdict')} {e.get('reason') or ''}")
    if e.get("checks"):
        print(f"  checks {e['checks']}")
        print(f"  revert {e.get('revert_fn')} {e.get('revert_message')!r} origin={e.get('origin')} "
              f"context={e.get('origin_context')} guard={(e.get('guard') or {}).get('type')}")
    elif e.get("detail"):
        print(f"  {e['detail']} at {e.get('context')}")
    print("bzx: not runnable in this repo yet; needs:")
    for n in BZX_NEEDS:
        print(f"  - {n}")
    print(f"written: {args.out / 'controls.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
