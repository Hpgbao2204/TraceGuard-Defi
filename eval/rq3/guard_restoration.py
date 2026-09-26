"""Root-cause-matched guard restorations on the fixed-20 queue (RQ3, analyst-specified interventions).

    python -m eval.rq3.guard_restoration build     # compile eval/rq3/guards/*.sol, write guards.lock.json
    python -m eval.rq3.guard_restoration prepare   # copy contexts, add the shadow's non-existence proof
    python -m eval.rq3.guard_restoration run --exe .cache/framelocal.exe

``guards.json`` fixes, per case, the guard source, the contract it replaces and the expected revert; the
lock file fixes the compiled runtimes. Both are committed before ``run``. Each case is replayed three
times in whole-transaction mode on the amended boundary (``fixed20_cases_amended.json``): the baseline,
the identity wrapper (control: must reproduce the baseline), and the guard. The guard passes if the
counterfactual is CAUSE_BLOCKED at a victim-origin revert whose message is the expected one, which the
fixed guard rule of ``final_table`` types as a security guard. Outputs go to .cache/rq3_guard/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from eval.rq3.final_table import classify_guard
from eval.rq3.run_fixed20 import interpret

ROOT = Path(__file__).resolve().parents[2]
GUARDS = ROOT / "eval" / "rq3" / "guards"
MANIFEST = GUARDS / "guards.json"
LOCK = GUARDS / "guards.lock.json"
AMENDED = ROOT / "eval" / "rq3" / "fixed20_cases_amended.json"
CONTEXTS = ROOT / "eval" / "results" / "m4" / "b2-contexts-fresh"
WORK = ROOT / ".cache" / "rq3_guard"
SOLC = ROOT / ".cache" / "solc" / "solc-0.8.24.exe"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def cmd_build(_args) -> None:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = {p.name: {"content": p.read_text(encoding="utf-8")} for p in sorted(GUARDS.glob("*.sol"))}
    req = {"language": "Solidity", "sources": sources,
           "settings": {"optimizer": {"enabled": True, "runs": 200}, "evmVersion": man["evm_version"],
                        "outputSelection": {"*": {"*": ["evm.deployedBytecode.object"]}}}}
    proc = subprocess.run([str(SOLC), "--standard-json"], input=json.dumps(req), capture_output=True, text=True,
                          check=True)
    out = json.loads(proc.stdout)
    errors = [e for e in out.get("errors", []) if e.get("severity") == "error"]
    if errors:
        raise SystemExit("\n".join(e["formattedMessage"] for e in errors))
    WORK.mkdir(parents=True, exist_ok=True)
    lock: dict[str, Any] = {"solc": proc.stdout and subprocess.run([str(SOLC), "--version"], capture_output=True,
                                                                   text=True).stdout.split()[-1],
                            "evm_version": man["evm_version"], "optimizer_runs": 200, "runtimes": {}}
    for fname, contracts in out["contracts"].items():
        for cname, art in contracts.items():
            code = art["evm"]["deployedBytecode"]["object"]
            if not code:
                continue
            (WORK / f"{cname}.hex").write_text("0x" + code, encoding="utf-8")
            lock["runtimes"][cname] = {"source": fname, "source_sha256": _sha(sources[fname]["content"].encode()),
                                       "runtime_sha256": _sha(bytes.fromhex(code)), "runtime_bytes": len(code) // 2}
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(lock, indent=2))


def cmd_prepare(_args) -> None:
    from core.env import load_dotenv, resolve_rpc_candidates
    from core.rpc import RpcClient
    from eval.b2_proofs import acquire as acquire_proofs
    load_dotenv()
    a = resolve_rpc_candidates("mainnet")
    archive = RpcClient(a[0], timeout=60, attempts=3, fallback_urls=a[1:])
    shadow = json.loads(MANIFEST.read_text(encoding="utf-8"))["shadow"]
    for name in json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]:
        dst = WORK / "ctx" / name
        if not dst.exists():
            shutil.copytree(CONTEXTS / name, dst)
        acquire_proofs(dst, archive, include_synthetic_shadows=True)
        # Re-acquisition covers the traced prestate only; keep every item of the frozen context's proof set
        # (e.g. a DELEGATECALL implementation), all verified against the same state root.
        proofs = json.loads((dst / "prestate_proofs.json").read_text(encoding="utf-8"))
        frozen = json.loads((CONTEXTS / name / "prestate_proofs.json").read_text(encoding="utf-8"))
        have = {str(i.get("address", "")).lower() for i in proofs["proofs"]}
        merged = [i for i in frozen["proofs"] if str(i.get("address", "")).lower() not in have]
        if merged:
            if frozen.get("header", {}).get("stateRoot") != proofs.get("header", {}).get("stateRoot"):
                raise SystemExit(f"{name}: frozen proofs are for a different state root")
            proofs["proofs"] += merged
            (dst / "prestate_proofs.json").write_text(json.dumps(proofs), encoding="utf-8")
        items = proofs["proofs"]
        ok = any(str(p.get("address", "")).lower() == shadow for p in items)
        print(f"{name}: shadow proof {'present' if ok else 'MISSING'}")


def original_runtime(ctx: Path, address: str) -> Path:
    """The replaced contract's runtime at S0, taken from its verified proof item (or the prestate)."""
    out = WORK / f"orig-{address}.hex"
    if not out.is_file():
        proofs = json.loads((ctx / "prestate_proofs.json").read_text(encoding="utf-8"))
        items = proofs.get("proofs", proofs) if isinstance(proofs, dict) else proofs
        code = next((i.get("code") for i in items if str(i.get("address", "")).lower() == address), None)
        if not code:
            pre = json.loads((ctx / "prestates.json").read_text(encoding="utf-8"))
            code = json.dumps(pre).lower().split(f'"{address}": {{', 1)[1].split('"code": "', 1)[1].split('"', 1)[0]
        out.write_text(code, encoding="utf-8")
    return out


def _args(exe: str, ctx: Path, case: dict, out: Path, replace: str | None, code: Path | None, shadow: str,
          delegate: bool, extra_gas: int) -> list[str]:
    args = [exe, "-context", str(ctx), "-proofs", str(ctx / "prestate_proofs.json"), "-output", str(out), "-lean",
            "-target-index", str(case["tx_index"]), "-mode", "whole-tx"]
    if replace and code:
        # The shadow is proven empty at the state block; it receives the replaced contract's original
        # runtime, and the replaced address receives the wrapper that forwards to it.
        args += ["-target-code", f"{shadow}=@{original_runtime(ctx, replace)}", "-target-code", f"{replace}=@{code}",
                 "-target-extra-gas", str(extra_gas)]
    if delegate:
        args += ["-delegate-context"]
    for v in case["victim"]:
        args += ["-victim", v]
    for a in case["attacker"]:
        args += ["-attacker", a]
    return args


def cmd_run(args) -> None:
    exe = str(Path(args.exe).resolve())
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    amended = json.loads(AMENDED.read_text(encoding="utf-8"))["cases"]
    report: dict[str, Any] = {"exe_sha256": _sha(Path(exe).read_bytes()), "lock": lock, "cases": {},
                              "not_measurable": man.get("not_measurable", {})}
    for name, g in man["cases"].items():
        ctx, case = WORK / "ctx" / name, amended[name]
        runs = WORK / "runs" / name
        runs.mkdir(parents=True, exist_ok=True)
        res: dict[str, Any] = {"replace": g["replace"], "victim": case["victim"], "expected_revert": g["expected_revert"],
                               "replace_in_victim": g["replace"] in [v.lower() for v in case["victim"]]}
        for label, code in (("baseline", None), ("identity", WORK / "IdentityForward.hex"),
                            ("guard", WORK / f"{g['contract']}.hex")):
            out = runs / f"{label}.json"
            proc = subprocess.run(_args(exe, ctx, case, out, g["replace"] if code else None, code, man["shadow"],
                                        g["delegate_context"], man["extra_gas"]), capture_output=True, text=True,
                                  timeout=1800)
            if proc.returncode != 0 or not out.is_file():
                (runs / f"{label}.stderr.txt").write_text(proc.stderr[-20000:], encoding="utf-8")
                res[label] = {"status": "runner_error", "exit": proc.returncode}
                continue
            payload = json.loads(out.read_text(encoding="utf-8"))
            rec = interpret(payload, "whole-tx")
            rv = rec.get("revert") or {}
            res[label] = {"verdict": rec.get("verdict"), "reason": rec.get("reason"),
                          "replay_gate": rec.get("replay_gate"), "origin_class": rec.get("revert_origin"),
                          "origin": rv.get("origin_address"), "revert_message": rv.get("revert_message"),
                          "guard_type": classify_guard(rv).get("type") if rv else None,
                          "guard_fired_but_caught": any((h.get("message") or "") == g["expected_revert"]
                                                        for h in rv.get("caught_victim_reverts") or []),
                          "token_losses": rec.get("token_losses")}
        gd, idn, base = res.get("guard", {}), res.get("identity", {}), res.get("baseline", {})
        res["identity_reproduces_baseline"] = bool(idn.get("replay_gate") and not idn.get("origin_class")
                                                   and idn.get("verdict") in ("NO_EFFECT", "INCONCLUSIVE")
                                                   and idn.get("reason") in (None, "not_consumed"))
        res["passed"] = bool(base.get("replay_gate") and res["identity_reproduces_baseline"]
                             and gd.get("verdict") == "CAUSE_BLOCKED" and gd.get("origin_class") == "victim"
                             and gd.get("revert_message") == g["expected_revert"]
                             and gd.get("guard_type") == "security")
        report["cases"][name] = res
        print(f"{name[13:]:34s} passed={res['passed']} guard={gd.get('verdict')}/{gd.get('origin_class')}/"
              f"{gd.get('revert_message')!r}/{gd.get('guard_type')} caught={gd.get('guard_fired_but_caught')} "
              f"identity={idn.get('verdict')}({idn.get('reason')})")
    (WORK / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"written: {WORK / 'results.json'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("prepare")
    rn = sub.add_parser("run")
    rn.add_argument("--exe", default=str(ROOT / ".cache" / "framelocal-gas.exe"),
                    help="cmd/framelocal built with -target-extra-gas support")
    args = ap.parse_args()
    {"build": cmd_build, "prepare": cmd_prepare, "run": cmd_run}[args.cmd](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
