"""RQ3 v3 factor rule, self-balance guard, pair diagnosis, positive control."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.rq3 import diagnose as dg
from eval.rq3 import discover_factors as df
from eval.rq3 import final_table as ft
from eval.rq3 import positive_controls as pc

V = "0x" + "b4" * 20
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
OTHER = "0x" + "22" * 20


def arg(addr: str) -> str:
    return "0" * 24 + addr[2:]


def read(target: str, selector: str, args: str = "", changed: bool = True) -> dict:
    return {"target": target, "selector": selector, "args": args, "changed_before_entry": changed, "is_revert": False}


def payload(reads: list[dict]) -> dict:
    return {"replay_gate": True, "frame_local_result": {"target_frame_index": 3}, "scoped_reads": reads}


def test_v3_drops_self_balance_and_non_economic():
    reads = [read(WETH, "0x70a08231", arg(V)), read(WETH, "0x70a08231", arg(OTHER)),
             read(OTHER, "0x095ea7b3", arg(V) + "0" * 64), read(OTHER, "0x01ffc9a7", "ab" * 32),
             read(OTHER, "0x0902f1ac")]
    v2 = df.factor_from_discovery(payload(reads))
    assert v2["sites"] == sorted({f"{WETH}:0x70a08231", f"{OTHER}:0x095ea7b3", f"{OTHER}:0x01ffc9a7",
                                  f"{OTHER}:0x0902f1ac"})
    v3 = df.factor_from_discovery(payload(reads), "v3", [V.upper().replace("0X", "0x")])
    assert v3["sites"] == sorted([f"{WETH}:0x70a08231:{arg(OTHER)}", f"{OTHER}:0x0902f1ac"])
    assert v3["excluded"] == {"non_economic:approve": 1, "non_economic:supportsInterface": 1, "self_balance": 1}
    assert df.subset_check({"c": v3}, {"c": v2}) == {}
    only_self = df.factor_from_discovery(payload([read(WETH, "0x70a08231", arg(V))]), "v3", [V])
    assert only_self["sites"] == [] and only_self["reason"] == "only_self_balance_or_non_economic"
    with pytest.raises(ValueError):
        df.factor_from_discovery(payload([read(WETH, "0x70a08231", "")]), "v3", [V])


def test_self_balance_guard_takes_precedence():
    sc = {"verdict": "CAUSE_BLOCKED", "revert_origin": "victim",
          "revert": {"revert_kind": "error_string", "revert_message": "UniswapV2: INSUFFICIENT_INPUT_AMOUNT"},
          "pinned": [{"caller": V, "caller_class": "victim", "target": WETH, "selector": "0x70a08231",
                      "args": arg(V), "kind": "neutral"}]}
    recs = {"whole-tx": sc, "frame-local": {"verdict": "CAUSE_BLOCKED"}, "isolation": {"verdict": "PASS"},
            "unscoped": {"verdict": "INCONCLUSIVE", "reason": "revert_confound_third_party",
                         "revert_origin": "third_party"}}
    row = ft.final_row("c", {"sites": [f"{WETH}:0x70a08231"]}, recs, [], {}, [V])
    assert row["final"] == "CAUSE_BLOCKED(self_balance_consistency)" and row["self_balance_pins"] == 1
    t = ft.totals([row])
    nv = t["naive_vs_gated"]
    assert nv["naive_any_change"] == 1 and nv["runner_cause_or_blocked"] == 1 and nv["strong_evidence"] == 0
    assert nv["guard_types"] == {"self_balance_consistency": 1}
    # Without V in the victim list the string rule applies.
    assert ft.final_row("c", {"sites": ["x"]}, recs, [], {}, [])["final"] == "CAUSE_BLOCKED(consistency)"
    other = dict(row, case="c", factor="1: x", final="INCONCLUSIVE(x)")
    cmp = ft.render_compare({"factors_rule_version": "v2", "rows": [row], "totals": t},
                            {"factors_rule_version": "v3", "rows": [other], "totals": t})
    assert "v2" in cmp and "v3" in cmp and "INCONCLUSIVE(x)" in cmp


def test_unfrozen_v3_must_be_committed(tmp_path):
    f = tmp_path / "v3.json"
    f.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="commit"):
        ft.check_frozen(f, "abc", {"rule_version": "v3"})
    with pytest.raises(SystemExit, match="frozen v2"):
        ft.check_frozen(f, "abc", {})
    assert ft.check_frozen(f, ft.FROZEN_FACTORS_SHA256, {}) == "970ce98"


def word(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:]


def test_pair_diagnosis():
    probes = [{"target": V, "input": "0xc45a0155", "output": word(OTHER)},
              {"target": V, "input": "0x0dfe1681", "output": word(WETH)},
              {"target": V, "input": "0xd21220a7", "output": word(OTHER)},
              {"target": V, "input": "0x0902f1ac", "output": "0x" + "00" * 96}]
    info = dg.pair_info(probes, [V])
    assert info[V]["is_pair"] and info[V]["token0"] == WETH
    assert not dg.pair_info([{"target": V, "input": "0xc45a0155", "error": "execution reverted"}], [V])[V]["is_pair"]
    scoped = {"verdict": "CAUSE_BLOCKED", "revert_origin": "victim",
              "revert": {"origin_address": V, "origin_selector": "0x6a627842", "revert_kind": "error_string",
                         "revert_message": "UniswapV2: INSUFFICIENT_LIQUIDITY_MINTED",
                         "revert_chain": [{"address": OTHER, "selector": "0xf04f2707"}, {"address": V, "selector": "0x6a627842"}]},
              "pinned": [{"caller": V, "caller_class": "victim", "target": WETH, "selector": "0x70a08231", "args": arg(V)}]}
    row = dg.diagnose_case("c", {"victim": [V]}, {"sites": ["s"]}, {"probes": probes}, scoped)
    assert row["v_is_pair"] and row["pinned_self_balance"] == 1 and row["pinned_token_is_pair_token"]
    assert row["revert_fn"] == "mint" and row["revert_chain"][0].endswith("receiveFlashLoan")
    assert row["guard"]["type"] == "self_balance_consistency"
    assert "True" in dg.render([row])


def test_positive_control_judge_and_args(tmp_path):
    rec = {"verdict": "CAUSE_BLOCKED", "replay_gate": True,
           "revert": {"revert_kind": "error_string", "revert_message": "e/collateral-violation"}}
    j = pc.judge(rec)
    assert j["passed"] and j["guard"]["type"] == "security"
    assert not pc.judge({**rec, "revert": {"revert_kind": "empty"}})["passed"]
    args = pc.euler_args("fl", tmp_path, tmp_path / "o.json")
    assert "-delegate-context" in args and any(a.endswith("euler_pr199_etoken_artifact.json") for a in args)
    art = json.loads(Path(pc.EULER["artifact"]).read_text(encoding="utf-8"))
    assert (art.get("deployedBytecode") or art.get("runtime") or "").startswith("0x")
