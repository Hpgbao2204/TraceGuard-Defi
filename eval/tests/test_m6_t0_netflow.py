from eval.m6_t0_netflow import t0_detect

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ALICE = "0x" + "1" * 40
BOB = "0x" + "2" * 40
HELPER = "0x" + "3" * 40

def flow(src, dst, amount=10):
    return [{"token": WETH, "from": src, "to": dst, "amount_raw": amount}]

def test_protected_outflow_is_harm():
    assert t0_detect(flow(BOB, ALICE), ALICE)["status"] == "HARM"

def test_protected_inflow_is_not_harm():
    assert t0_detect(flow(BOB, ALICE), BOB)["status"] == "NO_HARM"

def test_attacker_created_helper_excluded_from_protected_complement():
    result = t0_detect(flow(ALICE, HELPER), ALICE, [HELPER])
    assert result["status"] == "UNKNOWN"
    assert HELPER not in result["protected_set"]

def test_self_transfer_is_zero():
    result = t0_detect(flow(ALICE, ALICE), BOB)
    assert result["status"] == "NO_HARM"

def test_missing_ledger_is_unknown():
    assert t0_detect(None, ALICE)["status"] == "UNKNOWN"
