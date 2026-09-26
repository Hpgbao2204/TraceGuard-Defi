"""M3 builder simulation: AMM model, screener, layer 2 verdicts, policy, and an end-to-end anvil run."""
from __future__ import annotations

import pytest

from eval.mev_sim.amm import AmmModel, SwapOp, amount_out, victim_harm
from eval.mev_sim.chain import TOPIC_SWAP, TOPIC_TRANSFER, Receipt, find_anvil
from eval.mev_sim.detection import (CAUSE, DEFAULT, EXCLUDE, INCLUDE, INCONCLUSIVE, NO_EFFECT, Thresholds, decide,
                                    heuristic_naive, heuristic_strict, layer1, layer2, resolve)
from eval.mev_sim.metrics import wilson

T0, T1 = "0x" + "a" * 40, "0x" + "b" * 40
P, Q = "0x" + "1" * 40, "0x" + "2" * 40
POOLS = {P, Q}
V, ATK, ATK2 = "0x" + "c" * 40, "0x" + "d" * 40, "0x" + "e" * 40


# ------------------------------------------------------------------ AMM model
def test_amount_out_matches_uniswap_v2():
    assert amount_out(10**18, 10**21, 2 * 10**24) == (10**18 * 997 * 2 * 10**24) // (10**21 * 1000 + 10**18 * 997)
    assert amount_out(0, 1, 1) == 0


def test_victim_harm_signs():
    m = AmmModel({P: (T0, T1)}, {P: (10**21, 10**21)})
    victim = SwapOp((P,), T0, 10**19)
    assert victim_harm(m, [SwapOp((P,), T0, 5 * 10**19)], victim) > 0      # same-direction front-run hurts
    assert victim_harm(m, [SwapOp((P,), T1, 5 * 10**19)], victim) < 0      # opposite direction helps
    assert victim_harm(m, [], victim) == 0
    assert m.reserves[P] == (10**21, 10**21)                                # model not mutated


# ------------------------------------------------------------------ synthetic receipts
def _word(x: int) -> str:
    return f"{x:064x}"


def _topic(a: str) -> str:
    return "0x" + "0" * 24 + a[2:]


def transfer(tok, src, dst, v):
    return {"address": tok, "topics": [TOPIC_TRANSFER, _topic(src), _topic(dst)], "data": "0x" + _word(v)}


def swap_log(pool, zero_in: bool, amt_in, amt_out, to):
    words = (amt_in, 0, 0, amt_out) if zero_in else (0, amt_in, amt_out, 0)
    return {"address": pool, "topics": [TOPIC_SWAP, _topic(to), _topic(to)], "data": "0x" + "".join(map(_word, words))}


def rc_swap(sender, pool, zero_in, amt_in, amt_out, status=1):
    tin, tout = (T0, T1) if zero_in else (T1, T0)
    return Receipt(status, [transfer(tin, sender, pool, amt_in), transfer(tout, pool, sender, amt_out),
                            swap_log(pool, zero_in, amt_in, amt_out, sender)], 100_000)


def rc_plain(tok, src, dst, v, status=1):
    return Receipt(status, [transfer(tok, src, dst, v)] if status else [], 50_000)


def sandwich_obs(back_sender=ATK):
    return [rc_swap(ATK, P, True, 50, 45), rc_swap(V, P, True, 10, 8), rc_swap(back_sender, P, False, 45, 52)]


# ------------------------------------------------------------------ layer 1 and baselines
def test_layer1_flags_front_run_and_ignores_backrun():
    obs = sandwich_obs()
    s = layer1(obs, [False, True, False], 1, POOLS)
    assert s.flagged and s.suspects == [0] and s.same_direction
    backrun = [rc_swap(V, P, True, 10, 8), rc_swap(ATK, P, False, 8, 11)]
    assert not layer1(backrun, [True, False], 0, POOLS).flagged


def test_layer1_other_pool_not_flagged():
    obs = [rc_swap(ATK, Q, True, 50, 45), rc_swap(V, P, True, 10, 8), rc_swap(ATK, Q, False, 45, 52)]
    assert not layer1(obs, [False, True, False], 1, POOLS).flagged
    assert heuristic_naive(obs, [ATK, V, ATK], [False, True, False], 1, POOLS)     # same tokens, same sender
    assert not heuristic_strict(obs, [ATK, V, ATK], [False, True, False], 1, POOLS)


def test_strict_heuristic_evaded_by_address_change():
    pub = [False, True, False]
    assert heuristic_strict(sandwich_obs(), [ATK, V, ATK], pub, 1, POOLS)
    assert not heuristic_strict(sandwich_obs(ATK2), [ATK, V, ATK2], pub, 1, POOLS)
    assert not heuristic_naive(sandwich_obs(ATK2), [ATK, V, ATK2], pub, 1, POOLS)


# ------------------------------------------------------------------ layer 2
def _cf(receipts_by_index):
    def run(keep):
        return [receipts_by_index[k] for k in keep]
    return run


def test_layer2_cause():
    obs = sandwich_obs()
    cf = {1: rc_swap(V, P, True, 10, 9), 2: rc_swap(ATK, P, False, 45, 40, status=0)}
    v = layer2(obs, _cf(cf), V, 1, [0], POOLS, Thresholds())
    assert (v.verdict, v.harm, v.post_changed) == (CAUSE, 1, [2])


def test_layer2_no_effect_below_threshold_and_negative():
    obs = sandwich_obs()
    small = layer2(obs, _cf({1: rc_swap(V, P, True, 10, 8), 2: obs[2]}), V, 1, [0], POOLS, Thresholds())
    assert small.verdict == NO_EFFECT and small.harm == 0
    helped = layer2(obs, _cf({1: rc_swap(V, P, True, 10, 7), 2: obs[2]}), V, 1, [0], POOLS, Thresholds())
    assert helped.verdict == NO_EFFECT and helped.harm == -1
    rel = layer2(obs, _cf({1: rc_swap(V, P, True, 10, 9), 2: obs[2]}), V, 1, [0], POOLS, Thresholds(rel=0.5))
    assert rel.verdict == NO_EFFECT


def test_layer2_ordering_confound():
    decoy_obs = rc_plain(T1, ATK2, ATK, 45)
    obs = [rc_swap(ATK, P, True, 50, 45), decoy_obs, rc_swap(V, P, True, 10, 8), rc_swap(ATK, P, False, 45, 52)]
    cf = {1: rc_plain(T1, ATK2, ATK, 45, status=0), 2: rc_swap(V, P, True, 10, 9), 3: obs[3]}
    v = layer2(obs, _cf(cf), V, 2, [0], POOLS, Thresholds())
    assert (v.verdict, v.reason, v.confounded, v.harm) == (INCONCLUSIVE, "ordering_confound", [1], 1)
    assert v.confound_kind == "intermediate_changed" and decide(v.verdict) == DEFAULT


def test_layer2_victim_reverts_and_no_output():
    obs = sandwich_obs()
    v = layer2(obs, _cf({1: Receipt(0, [], 1), 2: obs[2]}), V, 1, [0], POOLS, Thresholds())
    assert (v.verdict, v.reason, v.confound_kind) == (INCONCLUSIVE, "ordering_confound", "victim_reverted")
    assert decide(v.verdict) == DEFAULT
    obs2 = [obs[0], Receipt(1, [], 1), obs[2]]
    v2 = layer2(obs2, _cf({}), V, 1, [0], POOLS, Thresholds())
    assert (v2.verdict, v2.reason) == (INCONCLUSIVE, "no_victim_output")


def test_policy_branches():
    assert decide(CAUSE) == EXCLUDE
    assert decide(NO_EFFECT) == INCLUDE
    assert decide(INCONCLUSIVE) == DEFAULT
    assert resolve(DEFAULT, INCLUDE) == INCLUDE and resolve(DEFAULT, EXCLUDE) == EXCLUDE
    assert resolve(EXCLUDE, INCLUDE) == EXCLUDE and resolve(INCLUDE, EXCLUDE) == INCLUDE


def test_wilson():
    assert wilson(0, 0) is None
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)


# ------------------------------------------------------------------ end to end on anvil
@pytest.fixture(scope="module")
def sim():
    if not find_anvil():
        pytest.skip("anvil not installed (foundry); set ANVIL=/path/to/anvil")
    from eval.mev_sim.run import run
    return run(slots=12, seed=3)


def _bundles(sim, mode):
    return [b for s in sim["slots"][mode] for b in s["bundles"]]


def test_end_to_end_all_metrics_present(sim):
    s = sim["summary"]
    assert set(s) == {"none", "heur_strict", "heur_naive", "l1_only", "tg_open", "tg_closed"}
    for mode in s:
        for key in ("sandwich_blocked", "benign_blocked", "victim_harm_realized_A", "victim_harm_avoided_A",
                    "latency_ms"):
            assert key in s[mode]
    assert s["none"]["sandwich_blocked"]["k"] == 0 and s["none"]["victim_harm_realized_A"] > 0
    assert s["tg_closed"]["victim_harm_avoided_A"] > 0


def test_end_to_end_layer2_matches_ground_truth(sim):
    checked = [b for m in ("tg_open", "tg_closed") for b in _bundles(sim, m)
               if b["attack"] and b["verdict"] in (CAUSE, NO_EFFECT)]
    assert checked
    assert all(b["harm_l2"] == b["gt_harm"] for b in checked)


def test_end_to_end_backrun_arbitrage_never_blocked(sim):
    for mode in ("l1_only", "tg_open", "tg_closed", "heur_strict", "heur_naive"):
        assert not any(b["kind"] == "arb_backrun" and b["status"] == "excluded" for b in _bundles(sim, mode))


def test_end_to_end_decisions_follow_policy(sim):
    for b in _bundles(sim, "tg_closed"):
        if b["verdict"] is None:
            assert b["status"] != "excluded"
        elif b["status"] in ("included", "excluded"):
            assert b["decision"] == decide(b["verdict"])
            want = resolve(b["decision"], EXCLUDE)
            assert b["status"] == ("excluded" if want == EXCLUDE else "included")


def test_end_to_end_benign_never_excluded_on_cause(sim):
    for mode in ("tg_open", "tg_closed"):
        assert not any(not b["attack"] and b["decision"] == EXCLUDE for b in _bundles(sim, mode))


# ------------------------------------------------------------------ layer 2 on geth-replay
def _geth_out(target_status=True, logs=(), comparable=True, confounds=(), fail_closed=False, error=""):
    return {"per_tx": [{"index": 0, "error": "dropped by ordering intervention"},
                       {"index": 1, "actual_status": target_status, "actual_gas": 1, "error": error,
                        "logs": list(logs)}],
            "ordering_intervention": {"comparable": comparable, "fail_closed": fail_closed,
                                      "ordering_confounds": list(confounds)}}


def test_geth_classify_cause_no_effect_and_confounds():
    from eval.mev_sim.geth_bridge import classify_drop_run
    thr, out_obs = Thresholds(), 900
    clean = [transfer(T1, P, V, 1000)]
    v, kinds, _ = classify_drop_run(_geth_out(logs=clean), 1, T1, out_obs, V, POOLS, thr)
    assert (v.verdict, v.harm) == (CAUSE, 100) and kinds == []
    v, _, _ = classify_drop_run(_geth_out(logs=[transfer(T1, P, V, 900)]), 1, T1, out_obs, V, POOLS, thr)
    assert (v.verdict, v.harm) == (NO_EFFECT, 0)
    v, kinds, _ = classify_drop_run(_geth_out(logs=clean, confounds=[{"index": 1, "kinds": ["logs_changed"]}]),
                                    1, T1, out_obs, V, POOLS, thr)
    assert (v.verdict, v.confound_kind, kinds) == (INCONCLUSIVE, "intermediate_changed", ["logs_changed"])
    v, _, _ = classify_drop_run(_geth_out(target_status=False), 1, T1, out_obs, V, POOLS, thr)
    assert (v.verdict, v.confound_kind) == (INCONCLUSIVE, "victim_reverted")
    v, _, _ = classify_drop_run(_geth_out(logs=clean, fail_closed=True, comparable=False), 1, T1, out_obs, V,
                                POOLS, thr)
    assert (v.verdict, v.reason) == (INCONCLUSIVE, "fail_closed")
    v, _, _ = classify_drop_run(_geth_out(target_status=False, error="nonce too high", comparable=False), 1, T1,
                                out_obs, V, POOLS, thr)
    assert (v.verdict, v.reason) == (INCONCLUSIVE, "incomparable")


def test_sim_accounts_are_key_derived_except_deployer():
    from eth_account import Account
    from eth_utils import keccak, to_checksum_address

    from eval.mev_sim.chain import TAG_DEPLOYER, TAG_FRESH, TAG_USER, addr, sim_key
    for tag in (TAG_USER, TAG_FRESH):
        a = addr(5, tag)
        assert Account.from_key(sim_key(a)).address == a
    legacy = to_checksum_address(keccak(TAG_DEPLOYER.to_bytes(4, "big") + (0).to_bytes(8, "big"))[-20:])
    assert addr(0, TAG_DEPLOYER) == legacy


@pytest.fixture(scope="module")
def sim_geth():
    from eval.mev_sim.geth_bridge import find_geth_replay
    if not find_anvil():
        pytest.skip("anvil not installed (foundry); set ANVIL=/path/to/anvil")
    if not find_geth_replay():
        pytest.skip("geth-replay not built (cd tools/geth-replay && go build -mod=vendor)")
    from eval.mev_sim.run import run
    return run(slots=6, seed=3, modes=("none", "tg_closed"), l2_engine="geth")


def test_end_to_end_geth_replay_agrees_with_anvil(sim_geth):
    evaluated = [b for s in sim_geth["slots"]["tg_closed"] for b in s["bundles"] if b["l2_engine"] == "geth"]
    assert evaluated
    for b in evaluated:
        assert b["geth_gate"] is True                                   # fidelity gate on every exported block
        assert (b["verdict"], b["reason"], b["harm_l2"]) == (b["anvil_verdict"], b["anvil_reason"], b["anvil_harm"])
        assert b["geth_timing"].get("target_evm") is not None or b["verdict"] == INCONCLUSIVE
    g = sim_geth["summary"]["tg_closed"]["geth_replay"]
    assert g["baseline_gate"]["k"] == g["evaluated"]
