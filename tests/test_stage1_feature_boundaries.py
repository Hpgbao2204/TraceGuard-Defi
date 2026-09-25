import unittest
from unittest.mock import Mock

from core.trace import TraceFetcher, infer_state_delta_from_trace, parse_call_tracer
from core.rpc import RpcError
from core.views import economic_features, token_flow_features, view_state_delta


class Stage1FeatureBoundaryTests(unittest.TestCase):
    def test_call_parser_declares_root_as_first_flat_call(self):
        trace = parse_call_tracer("0xtx", {
            "from": "0x" + "11" * 20,
            "to": "0x" + "22" * 20,
            "value": "0x64",
            "input": "0x",
            "calls": [{
                "from": "0x" + "22" * 20,
                "to": "0x" + "33" * 20,
                "value": "0x0a",
                "input": "0x",
            }],
        })
        self.assertEqual(trace["flat_calls"][0]["depth"], 0)
        self.assertEqual(trace["value"], 100)

    def test_inferred_eth_delta_counts_root_and_nested_edges_once(self):
        trace = parse_call_tracer("0xtx", {
            "from": "0x" + "11" * 20,
            "to": "0x" + "22" * 20,
            "value": "0x64",
            "input": "0x",
            "calls": [{
                "from": "0x" + "22" * 20,
                "to": "0x" + "33" * 20,
                "value": "0x0a",
                "input": "0x",
            }],
        })
        delta = infer_state_delta_from_trace(trace)
        self.assertEqual(delta["balances"]["0x" + "11" * 20], -100)
        self.assertEqual(delta["balances"]["0x" + "22" * 20], 90)
        self.assertEqual(delta["balances"]["0x" + "33" * 20], 10)

    def test_token_flow_accepts_normalized_integer_values_without_root_double_count(self):
        trace = {
            "from": "0x" + "11" * 20,
            "to": "0x" + "22" * 20,
            "value": 100,
            "flat_calls": [{"from": "0x" + "11" * 20,
                            "to": "0x" + "22" * 20, "value": 100},
                           {"from": "0x" + "22" * 20,
                            "to": "0x" + "33" * 20, "value": 10}],
            "logs": [],
        }
        features = token_flow_features(trace)
        self.assertEqual(features["n_transfer_events"], 2)

    def test_empty_delta_is_unavailable_not_trace_inferred(self):
        result = view_state_delta({}, {"from": "0x" + "11" * 20,
                                       "to": "0x" + "22" * 20,
                                       "value": 100, "flat_calls": []})
        self.assertEqual(result["features"]["coverage"], 0)

    def test_state_delta_does_not_use_block_boundary_fallback(self):
        client = Mock()
        client.call.side_effect = RpcError("unsupported")
        fetcher = TraceFetcher(client, use_debug_trace=True)
        fetcher.fetch_trace = Mock(return_value={
            "tx_hash": "0xtx", "block": 10,
            "addresses": {"0x" + "11" * 20},
        })
        result = fetcher.state_delta("0xtx")
        self.assertEqual(result["method"], "unavailable")
        client.eth_get_balance.assert_not_called()

    def test_economic_slippage_is_selector_specific_and_marks_unsupported(self):
        v2_input = "0x38ed1739" + ("00" * 32) + ("00" * 32)
        features = economic_features({
            "flat_calls": [{"selector": "0x38ed1739", "input": v2_input}],
            "logs": [],
        })
        self.assertIs(features["slippage"], True)
        self.assertEqual(features["slippage_observed"], 1)

        unsupported = economic_features({
            "flat_calls": [{"selector": "0x8803dbee",
                             "input": "0x8803dbee" + ("00" * 32) * 5}],
            "logs": [],
        })
        self.assertIsNone(unsupported["slippage"])
        self.assertEqual(unsupported["slippage_observed"], 0)

    def test_economic_transfer_signal_is_explicitly_raw_unit_diagnostic(self):
        features = economic_features({"from": "0x" + "11" * 20,
            "flat_calls": [], "logs": []})
        self.assertIn("raw_transfer_imbalance", features)
        self.assertNotIn("net_profit", features)


if __name__ == "__main__":
    unittest.main()
