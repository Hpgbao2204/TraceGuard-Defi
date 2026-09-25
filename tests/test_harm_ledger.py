from decimal import Decimal

from core.harm import HarmSpecification, assess_ledger
from eval.e4.harm import TRANSFER_TOPIC, _loss_from_receipt_data, assess_harm


def transfer(sender, recipient, amount, token="0xtoken"):
    return {"address": token, "topics": ["0x" + TRANSFER_TOPIC,
            "0x" + sender[2:].rjust(64, "0"),
            "0x" + recipient[2:].rjust(64, "0")], "data": hex(amount)}


def spec() -> HarmSpecification:
    return HarmSpecification(
        victims=frozenset({"0xVictim"}),
        assets={"0xtoken": (2, Decimal("2"))},
        threshold=Decimal("10"),
    )


def liabilities():
    return {"0xvictim": {"0xtoken": 0}}


def test_signed_transfer_and_threshold():
    result = assess_ledger(spec(), {"0xvictim": {"0xtoken": -600}}, liabilities=liabilities())
    assert result.status == "HARM"
    assert result.value == Decimal("12")


def test_missing_price_is_unknown():
    result = assess_ledger(
        HarmSpecification(victims=frozenset({"0xVictim"}), assets={},
                          required_assets=frozenset({"0xother"}),
                          threshold=Decimal("10")),
        {"0xvictim": {"0xother": -1}},
        liabilities={"0xvictim": {"0xother": 0}},
    )
    assert result.status == "UNKNOWN"
    assert result.value is None


def test_below_threshold_is_not_harm():
    result = assess_ledger(spec(), {"0xvictim": {"0xtoken": -400}}, liabilities=liabilities())
    assert result.status == "NO_HARM"
    assert result.value == Decimal("8")


def test_explicit_zero_delta_is_observed_no_harm():
    result = assess_ledger(spec(), {"0xvictim": {"0xtoken": 0}}, liabilities=liabilities())
    assert result.status == "NO_HARM"
    assert result.value == Decimal("0")


def test_missing_protected_asset_cell_is_unknown_not_zero():
    result = assess_ledger(spec(), {"0xvictim": {}}, liabilities=liabilities())
    assert result.status.value == "UNKNOWN"


def test_empty_liability_mapping_is_unknown_not_zero():
    result = assess_ledger(spec(), {"0xvictim": {"0xtoken": 0}}, liabilities={})
    assert result.status.value == "UNKNOWN"


def test_missing_protected_owner_is_unknown():
    result = assess_ledger(spec(), {}, liabilities=liabilities())
    assert result.status.value == "UNKNOWN"


def test_internal_transfer_between_protected_victims_cancels():
    result = assess_ledger(
        spec(),
        {"0xvictim": {"0xtoken": -600}, "0xVICTIM": {"0xtoken": 600}},
        liabilities=liabilities(),
    )
    assert result.status == "NO_HARM"
    assert result.value == Decimal("0")


def test_e4_receipt_ledger_nets_internal_protected_transfer():
    receipt = {"logs": [transfer("0x" + "a" * 40, "0x" + "b" * 40, 100)]}
    assert _loss_from_receipt_data(
        receipt, {"0xtoken": {"usd_per_token": 1, "decimals": 0}},
        victims={"0x" + "a" * 40, "0x" + "b" * 40},
    ) == 0


def test_e4_receipt_ledger_missing_price_is_unknown():
    receipt = {"logs": [transfer("0x" + "a" * 40, "0x" + "b" * 40, 100),
                         transfer("0x" + "a" * 40, "0x" + "c" * 40, 1,
                                  token="0xother")]}
    result = assess_harm(receipt, {"victims": ["0x" + "a" * 40],
        "token_prices": {"0xtoken": {"usd_per_token": 1, "decimals": 0}},
        "lmin_usd": 1})
    assert result.status == "UNKNOWN"


def test_e4_receipt_ledger_without_historical_price_provenance_is_unknown():
    receipt = {"logs": [transfer("0x" + "a" * 40, "0x" + "b" * 40, 100)]}
    result = assess_harm(receipt, {
        "victims": ["0x" + "a" * 40],
        "token_prices": {"0xtoken": {"usd_per_token": 1, "decimals": 0}},
        "lmin_usd": 1,
    })
    assert result.status == "UNKNOWN"
    assert "provenance" in result.reason
