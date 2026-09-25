from eval.m6_harm_adapters import assess_alkimiya_wbtc, assess_xloot_native_eth

OWNER = "0x1111111111111111111111111111111111111111"
TOKEN = "0x2222222222222222222222222222222222222222"
TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def spec(**extra):
    base = {"protected_entity": OWNER, "lmin_usd": 20, "usd_per_token": 100,
            "price_reference_block": 9, "target_block": 10,
            "price_provenance": {"native_eth": {"reference_block": 9, "source": "fixture"},
                                  "wbtc": {"reference_block": 9, "source": "fixture"}}}
    base.update(extra)
    return base


def test_xloot_harm_and_no_harm():
    target = {"balance_changes": [{"address": OWNER, "previous": "1000000000000000000", "current": "0"}]}
    assert assess_xloot_native_eth(target, spec(asset_kind="native")).status == "HARM"
    target["balance_changes"][0]["current"] = "1000000000000000000"
    assert assess_xloot_native_eth(target, spec(asset_kind="native")).status == "NO_HARM"


def test_xloot_missing_observation_is_unknown():
    assert assess_xloot_native_eth({}, spec(asset_kind="native")).status == "UNKNOWN"


def test_alkimiya_uses_protected_wbtc_ledger():
    def topic(addr): return "0x" + "0" * 24 + addr[2:]
    target = {"logs": [{"address": TOKEN, "topics": [TOPIC, topic(OWNER), topic("0x3333333333333333333333333333333333333333")], "data": hex(1_000_000_000)}]}
    s = spec(asset_kind="erc20", asset_address=TOKEN, decimals=8, usd_per_token=100)
    assert assess_alkimiya_wbtc(target, s).status == "HARM"


def test_alkimiya_missing_price_is_unknown():
    s = spec(asset_kind="erc20", asset_address=TOKEN, decimals=8, usd_per_token=None)
    assert assess_alkimiya_wbtc({"logs": []}, s).status == "UNKNOWN"
