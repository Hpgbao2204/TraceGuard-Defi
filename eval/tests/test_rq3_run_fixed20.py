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
    assert lock["manifest_sha256"] == rf.sha256_text(manifest)
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


def test_factor_rule():
    from eval.rq3 import discover_factors as df
    reads = [
        {"target": "0xAA", "selector": "0x70A08231", "changed_before_entry": True, "is_revert": False},
        {"target": "0xaa", "selector": "0x70a08231", "changed_before_entry": True, "is_revert": False},
        {"target": "0xbb", "selector": "0x0902f1ac", "changed_before_entry": False, "diverges": True, "is_revert": False},
        {"target": "0xcc", "selector": "0x12345678", "changed_before_entry": True, "is_revert": True},
    ]
    ok = df.factor_from_discovery({"replay_gate": True, "frame_local_result": {"target_frame_index": 3}, "scoped_reads": reads})
    assert ok["sites"] == ["0xaa:0x70a08231"] and ok["reason"] is None and ok["n_changed_before_entry"] == 3
    gate = df.factor_from_discovery({"replay_gate": False, "frame_local_result": {"target_frame_index": 3}, "scoped_reads": reads})
    assert gate["sites"] == [] and gate["reason"] == "replay_gate_failed"
    none = df.factor_from_discovery({"replay_gate": True, "frame_local_result": {"target_frame_index": -1, "reason_code": "no_harm_frame"}})
    assert none["reason"] == "no_harm_frame"
    empty = df.factor_from_discovery({"replay_gate": True, "frame_local_result": {"target_frame_index": 0}, "scoped_reads": reads[2:3]})
    assert empty["sites"] == [] and empty["reason"] == "no_read_changed_before_entry"


def test_runner_uses_frozen_factors(tmp_path, monkeypatch):
    contexts = tmp_path / "ctx"
    make_context(contexts, "case-a", ["0x0", "0xabc"])
    make_context(contexts, "case-b", ["0x0", "0xabc"])
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"schema": 1, "cases": {"case-a": CASE, "case-b": CASE}}), encoding="utf-8")
    factors = tmp_path / "factors.json"
    factors.write_text(json.dumps({"manifest_sha256": rf.sha256_text(manifest), "cases": {
        "case-a": {"sites": ["0xaa:0x70a08231"], "reason": None},
        "case-b": {"sites": [], "reason": "no_harm_frame"}}}), encoding="utf-8")
    exe = tmp_path / "framelocal.exe"
    exe.write_bytes(b"stub")
    seen = []

    def fake_run(args, capture_output, text, timeout):
        seen.append(args)
        mode = args[args.index("-mode") + 1]
        Path(args[args.index("-output") + 1]).write_text(json.dumps(fake_output(mode)), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(rf.subprocess, "run", fake_run)
    out = tmp_path / "out"
    rf.main(["--exe", str(exe), "--manifest", str(manifest), "--contexts", str(contexts), "--out", str(out),
             "--factors", str(factors)])
    assert len(seen) == 4 and all(a[a.index("-read-site") + 1] == "0xaa:0x70a08231" for a in seen)
    doc = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert doc["factors_sha256"] == rf.sha256_text(factors)
    assert doc["cases"]["case-b"]["frame-local"]["reason"] == "no_declared_factor:no_harm_frame"
    assert doc["summary"]["modes"]["frame-local"]["inconclusive_reasons"] == {"no_declared_factor": 1}

    other = tmp_path / "other.json"
    other.write_text(json.dumps({"manifest_sha256": "x", "cases": {}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        rf.main(["--exe", str(exe), "--manifest", str(manifest), "--contexts", str(contexts), "--out", str(out),
                 "--factors", str(other)])


def test_text_hash_ignores_line_endings(tmp_path):
    lf, crlf = tmp_path / "lf.json", tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "a": 1\n}\n')
    crlf.write_bytes(b'{\r\n  "a": 1\r\n}\r\n')
    assert rf.sha256_text(lf) == rf.sha256_text(crlf)


def test_dose_modes(tmp_path, monkeypatch, capsys):
    ctx = make_context(tmp_path, "c", ["0x0", "0xabc"])
    th = {"loss_min_frac": 0.01, "rho": 0.1}
    args = rf.build_args("exe", ctx, CASE, "frame-local@0.5", tmp_path / "o.json", th)
    assert args[args.index("-mode") + 1] == "frame-local" and args[args.index("-dose-lambda") + 1] == "0.5"
    assert rf.dose_modes([0.25, 0.5]) == ("whole-tx@0.25", "frame-local@0.25", "whole-tx@0.5", "frame-local@0.5")

    contexts = tmp_path / "ctx"
    make_context(contexts, "case-a", ["0x0", "0xabc"])
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"schema": 1, "cases": {"case-a": CASE}}), encoding="utf-8")
    exe = tmp_path / "framelocal.exe"
    exe.write_bytes(b"stub")

    def fake_run(a, capture_output, text, timeout):
        mode = a[a.index("-mode") + 1]
        out = fake_output(mode)
        if "-dose-lambda" in a and mode == "frame-local":
            out["frame_local_result"] = {"verdict": "PARTIAL"}
        if "-dose-lambda" in a and mode == "whole-tx":
            out["whole_tx_result"] = {"verdict": "CAUSE_BLOCKED"}
        Path(a[a.index("-output") + 1]).write_text(json.dumps(out), encoding="utf-8")
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(rf.subprocess, "run", fake_run)
    out = tmp_path / "out"
    rf.main(["--exe", str(exe), "--manifest", str(manifest), "--contexts", str(contexts), "--out", str(out), "--dose", "0.5"])
    doc = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert doc["cases"]["case-a"]["frame-local@0.5"]["verdict"] == "PARTIAL"
    assert doc["summary"]["modes"]["whole-tx@0.5"]["n"] == 1
    assert "dose-response" in capsys.readouterr().out
    assert rf.main(["--render", str(out / "summary.json")]) == 0
    assert "CB/P" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        rf.main(["--exe", str(exe), "--manifest", str(manifest), "--contexts", str(contexts), "--out", str(out), "--dose", "1"])
