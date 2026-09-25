from eval.m6_harm_quantification import quantify

def test_missing_price_does_not_change_raw_layer():
    result = quantify({"WETH": "-1000000000000000000"}, None)
    assert result["status"] == "QUANTIFICATION_UNAVAILABLE"

def test_frozen_price_quantifies():
    result = quantify({"WETH": "-2000000000000000000"}, {"WETH": "2000"})
    assert result["status"] == "QUANTIFIED"
    assert result["usd"] == "-4000"
