"""RQ3 final table: guard classification, dose threshold, rows and --reuse/--json-only."""
from __future__ import annotations

import json
from pathlib import Path

from eval.rq3 import final_table as ft
from eval.rq3 import run_fixed20 as rf

CASE = {"victim": ["0x" + "11" * 20], "attacker": ["0x" + "22" * 20], "tx_index": 1, "block": 1, "tx_hash": "0xabc"}


def rv(kind: str, msg: str) -> dict:
    return {"revert_kind": kind, "revert_message": msg, "origin_address": "0x11", "origin_selector": "0x022c0d9f"}


def test_classify_guard():
    assert ft.classify_guard(rv("error_string", "UniswapV2: K"))["type"] == "consistency"
    assert ft.classify_guard(rv("error_string", "Pancake: K"))["type"] == "consistency"
    assert ft.classify_guard(rv("error_string", "ERC20: transfer amount exceeds balance"))["type"] == "consistency"
    assert ft.classify_guard(rv("panic", "0x11 arithmetic_overflow"))["type"] == "consistency"
    assert ft.classify_guard(rv("error_string", "Insufficient collateral"))["type"] == "security"
    assert ft.classify_guard(rv("error_string", "health factor too low"))["type"] == "security"
    assert ft.classify_guard(rv("error_string", "Ownable: caller is not the owner"))["type"] == "security"
    assert ft.classify_guard(rv("error_string", "EXPIRED"))["type"] == "other"
    assert ft.classify_guard(rv("empty", ""))["type"] == "unknown"
    assert ft.classify_guard(rv("custom_error", "0xdeadbeef"))["type"] == "unknown"
    assert ft.classify_guard(None)["type"] == "unknown"


def test_smallest_blocked_lambda():
    recs = {"whole-tx": {"verdict": "CAUSE_BLOCKED"}, "whole-tx@0.75": {"verdict": "CAUSE_BLOCKED"},
            "whole-tx@0.5": {"verdict": "NO_EFFECT"}, "whole-tx@0.25": {"verdict": "CAUSE_BLOCKED"}}
    # Monotone from the top: 0.25 blocks but 0.5 does not, so the threshold is 0.75.
    assert ft.smallest_blocked_lambda(recs, "whole-tx", [0.25, 0.5, 0.75]) == 0.75
    assert ft.smallest_blocked_lambda({"whole-tx": {"verdict": "NO_EFFECT"}}, "whole-tx", [0.5]) is None
    assert ft.smallest_blocked_lambda({"whole-tx": {"verdict": "CAUSE"}}, "whole-tx", []) == 1.0


def runs_fixture() -> dict:
    blocked = {"verdict": "CAUSE_BLOCKED", "reason": None, "revert_origin": "victim",
               "revert": rv("error_string", "UniswapV2: K"), "reads_by_caller": {"victim": 1}}
    return {
        "a-sec": {"unscoped": {"verdict": "INCONCLUSIVE", "reason": "revert_confound_attacker", "revert_origin": "attacker",
                               "reads_by_caller": {"attacker": 3, "victim": 1}},
                  "whole-tx": {**blocked, "revert": rv("error_string", "health factor too low")},
                  "frame-local": {"verdict": "CAUSE_BLOCKED"}, "isolation": {"verdict": "PASS"},
                  "whole-tx@0.5": {"verdict": "CAUSE_BLOCKED"}},
        "b-cons": {"unscoped": dict(blocked), "whole-tx": dict(blocked), "frame-local": {"verdict": "CAUSE_BLOCKED"},
                   "isolation": {"verdict": "PASS"}, "whole-tx@0.5": {"verdict": "NO_EFFECT"}},
        "c-tp": {"unscoped": {"verdict": "INCONCLUSIVE", "reason": "revert_confound_third_party", "revert_origin": "third_party"},
                 "whole-tx": {"verdict": "INCONCLUSIVE", "reason": "revert_confound_third_party", "revert_origin": "third_party"},
                 "frame-local": {"verdict": "INCONCLUSIVE", "reason": "revert_confound_third_party"},
                 "isolation": {"verdict": "PASS"}},
        "d-none": {m: {"verdict": "INCONCLUSIVE", "reason": "no_declared_factor:no_harm_frame"} for m in ft.RUN_MODES},
    }


FACTORS = {"a-sec": {"sites": ["0x" + "aa" * 20 + ":0x70a08231"]}, "b-cons": {"sites": ["0x" + "bb" * 20 + ":0x0902f1ac"]},
           "c-tp": {"sites": ["0x" + "cc" * 20 + ":0x70a08231"]}, "d-none": {"sites": [], "reason": "no_harm_frame"}}


def test_rows_and_totals():
    runs = runs_fixture()
    rows = [ft.final_row(n, FACTORS[n], runs[n], [0.5], {}) for n in sorted(runs)]
    by = {r["case"]: r for r in rows}
    assert by["a-sec"]["final"] == "CAUSE_BLOCKED(security)"
    assert by["a-sec"]["dose_min_blocked_lambda"]["whole_tx"] == 0.5
    assert by["b-cons"]["final"] == "CAUSE_BLOCKED(consistency)"
    assert by["b-cons"]["dose_min_blocked_lambda"]["whole_tx"] == 1.0
    assert by["c-tp"]["final"] == "INCONCLUSIVE(revert_confound_third_party)"
    assert by["d-none"]["final"] == "INCONCLUSIVE(no_declared_factor:no_harm_frame)"
    t = ft.totals(rows)
    assert t["coverage_valid"] == 2 and t["strong_evidence"] == 1 and t["with_factor"] == 3
    assert t["inconclusive_reasons"] == {"no_declared_factor:no_harm_frame": 1, "revert_confound_third_party": 1}
    assert t["revert_origin_with_factor"]["unscoped"] == {"attacker": 1, "third_party": 1, "victim": 1}
    assert t["unscoped_pinned_reads_by_caller"] == {"attacker": 3, "victim": 2}
    # A manual override only applies to unknown/other and is marked.
    runs["b-cons"]["whole-tx"]["revert"] = rv("empty", "")
    row = ft.final_row("b-cons", FACTORS["b-cons"], runs["b-cons"], [0.5], {"b-cons": {"type": "security", "note": "src L10"}})
    assert row["final"] == "CAUSE_BLOCKED(security)" and row["guard"]["source"] == "manual"
    assert "*" in ft.render({"rows": [row], "totals": ft.totals([row])})


def test_reuse_json_only(tmp_path, capsys):
    out = tmp_path / "final"
    out.mkdir()
    lock = {"manifest": "m", "manifest_sha256": "x", "n_cases": 4, "dose_lambdas": [0.5]}
    (out / "runs.json").write_text(json.dumps({"lock": lock, "cases": runs_fixture()}), encoding="utf-8")
    assert ft.main(["--reuse", "--json-only", "--out", str(out), "--guard-overrides", str(tmp_path / "none.json")]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc == json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert doc["totals"]["n_cases"] == 4 and len(doc["rows"]) == 4


def test_factors_must_be_frozen(tmp_path):
    other = tmp_path / "f.json"
    other.write_text("{}", encoding="utf-8")
    try:
        ft.main(["--reuse", "--factors", str(other), "--out", str(tmp_path)])
    except SystemExit as e:
        assert "not the frozen" in str(e)
    else:
        raise AssertionError("a non-frozen factors file must be refused")


def test_build_args_unscoped(tmp_path):
    ctx = tmp_path / "c"
    ctx.mkdir()
    args = rf.build_args("fl", ctx, CASE, "unscoped", tmp_path / "o.json", {"loss_min_frac": 0.01, "rho": 0.1},
                         ["0x" + "aa" * 20 + ":0x70a08231"])
    i = args.index("-mode")
    assert args[i:i + 4] == ["-mode", "whole-tx", "-scoped-price", "-unscoped"]
    rec = rf.interpret({"replay_gate": True, "whole_tx_result": {"verdict": "NO_EFFECT"},
                        "scoped_reads": [{"caller_class": "attacker"}, {"caller_class": "victim"}]}, "unscoped")
    assert rec["verdict"] == "NO_EFFECT" and rec["reads_by_caller"] == {"attacker": 1, "victim": 1}
