from eval.e4.semantic_validation import (
    PriceValue, compare_reference_price, flash_loan_postcondition, oracle_postcondition,
)


def payload(output="0x1234", reverted=False):
    return {"target_index": 0, "per_tx": [{"call_trace": [
        {"event": "enter", "depth": 1, "to": "0xAbC", "input": "0xfeaf968c"},
        {"event": "exit", "depth": 1, "output": output, "reverted": reverted},
    ]}]}


def test_oracle_postcondition_requires_historical_return_and_matches_it():
    assert oracle_postcondition(payload(), oracle="0xabc", selector="feaf968c") == (
        "unknown", "oracle-reference-return-missing")
    assert oracle_postcondition(payload(), oracle="0xabc", selector="feaf968c",
                                expected_return="0x1234", reference_verified=True) == (
        "valid", "oracle-getter-postcondition-verified")
    assert oracle_postcondition(payload("0x9999"), oracle="0xabc", selector="feaf968c",
                                expected_return="0x1234", reference_verified=True)[0] == "invalid"
    assert oracle_postcondition(payload(reverted=True), oracle="0xabc", selector="feaf968c",
                                expected_return="0x1234", reference_verified=True)[0] == "invalid"

    assert oracle_postcondition(payload(), oracle="0xabc", selector="feaf968c",
                                expected_return="0x1234")[0] == "unknown"


def test_oracle_postcondition_rejects_wrong_target_or_selector():
    assert oracle_postcondition(payload(), oracle="0xdef", selector="feaf968c")[0] == "invalid"
    assert oracle_postcondition(payload(), oracle="0xabc", selector="85bb7d69")[0] == "invalid"
    assert oracle_postcondition(payload(), oracle="0xabc", selector="")[0] == "invalid"


def test_oracle_postcondition_rejects_shaped_unregistered_oracle():
    status, reason = oracle_postcondition(
        payload(), oracle="0xabc", selector="feaf968c", expected_return="0x1234",
        reference_verified=True, protocol_id="aventa",
    )
    assert (status, reason) == ("invalid", "oracle-address-not-in-registry")

    assert oracle_postcondition(
        payload(), oracle="0xabc", selector="feaf968c", expected_return="0x1234",
        reference_verified=True, allowed_oracles={"0xabc"},
    )[0] == "valid"


def test_oracle_postcondition_fails_closed_without_registry_entry():
    status, reason = oracle_postcondition(
        payload(), oracle="0xabc", selector="feaf968c", expected_return="0x1234",
        reference_verified=True, protocol_id="protocol-without-registry",
    )
    assert (status, reason) == ("invalid", "oracle-address-not-in-registry")


def test_price_comparison_rejects_decimals_and_quote_mismatch():
    reference = PriceValue(2_000_000, 6, "USDC")
    observed = PriceValue(2_000_000_000_000_000_000, 18, "USDC")
    assert compare_reference_price(reference, observed) == (
        "invalid", "oracle-price-unit-mismatch-decimals")
    assert compare_reference_price(
        PriceValue(2_000, 6, "USDC"), PriceValue(2_000, 6, "ETH")
    ) == ("invalid", "oracle-price-unit-mismatch-quote-currency")
    assert compare_reference_price(
        PriceValue(2_000, 6, "usdc"), PriceValue(2_100, 6, "USDC")
    ) == ("valid", "oracle-price-units-match")


def test_oracle_postcondition_fails_closed_on_malformed_trace():
    assert oracle_postcondition({"target_index": 0, "per_tx": "bad"},
                                oracle="0xabc", selector="feaf968c")[0] == "invalid"
    assert oracle_postcondition({"target_index": 0, "per_tx": [{}]},
                                oracle="0xabc", selector="feaf968c")[0] == "invalid"


def test_flash_loan_postcondition_requires_targeted_entrypoint_to_revert():
    base = {"target_index": 0, "per_tx": [{"call_trace": [
        {"event": "enter", "depth": 1, "to": "0xabc", "input": "0xabcd1234"},
        {"event": "exit", "depth": 1, "reverted": True},
    ]}]}
    assert flash_loan_postcondition(base, provider="0xabc", selector="abcd1234") == (
        "valid", "flash-entrypoint-blocked")
    unblocked = {**base, "per_tx": [{"call_trace": [
        {"event": "enter", "depth": 1, "to": "0xabc", "input": "0xabcd1234"},
        {"event": "exit", "depth": 1, "reverted": False},
    ]}]}
    assert flash_loan_postcondition(unblocked, provider="0xabc", selector="abcd1234")[0] == "invalid"
    assert flash_loan_postcondition(base, provider="0xdef", selector="abcd1234")[0] == "invalid"
