"""run_fixed20 on synthetic contexts with a stubbed frame-local binary."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from eval.rq3 import run_fixed20 as rf

CASE = {"victim": ["0x" + "11" * 20], "attacker": ["0x" + "22" * 20], "tx_index": 1, "block": 1, "tx_hash": "0xabc"}


def make_context(root: Path, name: str, hashes: list[str]) -> Path:
    ctx = root / name
    ctx.mkdir(parents=True)
    (ctx / "transactions.json").write_text(json.dumps([{"hash": h} for h in hashes]), encoding="utf-8")
    return ctx


def fake_output(mode: str, gate: bool = True) -> dict:
    res = {
        "whole-tx": {"verdict": "INCONCLUSIVE", "reason_code": "revert_confound_attacker", "reverted": True,
                     "revert_origin": {"has_revert": True, "origin_class": "attacker"}},
        "frame-local": {"verdict": "CAUSE", "target_frame_index": 2, "intervention_sites": 1,
                        "attacker_input": {"match": True}, "token_losses": [{"asset": "0xt", "outcome": "CAUSE"}]},
        "isolation": {"verdict": "PASS", "intervention_sites": 1},
        "sham": {"verdict": "INCONCLUSIVE", "reason_code": "no_unrelated_read_site"},
    }[mode]
    key = "whole_tx_result" if mode == "whole-tx" else "frame_local_result"
    return {"replay_gate": gate, key: res}


def test_wilson_known_values():
    assert rf.wilson(0, 0) is None
    lo, hi = rf.wilson(10, 20)
    assert lo == pytest.approx(0.2993, abs=1e-3) and hi == pytest.approx(0.7007, abs=1e-3)
    assert rf.wilson(20, 20)[1] == 1.0


def test_check_context(tmp_path):
    assert rf.check_context(tmp_path / "nope", CASE) == "missing_context"
    ok = make_context(tmp_path, "ok", ["0x0", "0xABC"])
    assert rf.check_context(ok, CASE) is None
    short = make_context(tmp_path, "short", ["0xabc"])
    assert rf.check_context(short, CASE) == "context_has_1_txs_expected_2"
    wrong = make_context(tmp_path, "wrong", ["0x0", "0xdef"])
    assert rf.check_context(wrong, CASE) == "target_hash_mismatch"


def test_gate_failure_is_fail_closed():
    rec = rf.interpret(fake_output("frame-local", gate=False), "frame-local")
    assert rec["verdict"] == "INCONCLUSIVE" and rec["reason"] == "replay_gate_failed"
    assert rec["raw_verdict"] == "CAUSE"
    assert rf.interpret(None, "sham", "timeout") == {"verdict": "INCONCLUSIVE", "reason": "timeout"}


def test_build_args_modes(tmp_path):
    ctx = make_context(tmp_path, "c", ["0x0", "0xabc"])
    (ctx / "prestate_proofs.json").write_text("{}", encoding="utf-8")
    th = {"loss_min_frac": 0.01, "rho": 0.1}
    whole = rf.build_args("exe", ctx, CASE, "whole-tx", tmp_path / "o.json", th)
    assert whole[whole.index("-mode") + 1] == "whole-tx" and "-scoped-price" in whole
    assert "-lean" in whole and "-proofs" in whole
    assert whole[whole.index("-target-index") + 1] == "1"
    sham = rf.build_args("exe", ctx, CASE, "sham", tmp_path / "o.json", th)
    assert sham[sham.index("-mode") + 1] == "sham" and "-scoped-price" not in sham


def test_end_to_end_with_stubbed_binary(tmp_path, monkeypatch, capsys):
    contexts = tmp_path / "ctx"
    make_context(contexts, "case-a", ["0x0", "0xabc"])
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"schema": 1, "cases": {"case-a": CASE, "case-missing": CASE}}), encoding="utf-8")
    exe = tmp_path / "framelocal.exe"
    exe.write_bytes(b"stub")

    def fake_run(args, capture_output, text, timeout):
        mode = args[args.index("-mode") + 1]
        Path(args[args.index("-output") + 1]).write_text(json.dumps(fake_output(mode)), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(rf.subprocess, "run", fake_run)
    out = tmp_path / "out"
    assert rf.main(["--exe", str(exe), "--manifest", str(manifest), "--contexts", str(contexts), "--out", str(out)]) == 0

    lock = json.loads((out / "manifest_lock.json").read_text(encoding="utf-8"))
    assert lock["manifest_sha256"] == rf.sha256_file(manifest)
    doc = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert doc["manifest_sha256"] == lock["manifest_sha256"]
    modes = doc["summary"]["modes"]
    assert modes["frame-local"]["valid"] == 1 and modes["frame-local"]["n"] == 2
    assert modes["frame-local"]["inconclusive_reasons"] == {"missing_context": 1}
    assert modes["whole-tx"]["revert_origin"] == {"attacker": 1}
    assert modes["isolation"]["pass"] == 1 and modes["isolation"]["applicable"] == 1
    assert modes["sham"]["applicable"] == 0 and modes["sham"]["pass_rate_wilson95"] is None
    printed = capsys.readouterr().out
    assert "case-a" in printed and "valid 1/2" in printed
