"""Behavioral EVM tests for the HealthCheckGuard runtime.

These tests are skipped when Anvil is unavailable; they never substitute
bytecode inspection for an EVM execution result.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import unittest
import urllib.request

from core.mutate import (
    _operate_guard_runtime,
    _operate_success_runtime,
    _oracle_forwarding_runtime,
)


RPC = "http://127.0.0.1:18546"
SHADOW = "0x00000000000000000000000000000000000000aa"
GUARD = "0x00000000000000000000000000000000000000bb"
TARGET = "36f022aa"


def rpc(method: str, params: list) -> object:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    with urllib.request.urlopen(urllib.request.Request(
            RPC, body, {"Content-Type": "application/json"}), timeout=5) as response:
        result = json.loads(response.read())
    if "error" in result:
        raise RuntimeError(result["error"])
    return result.get("result")


class HealthCheckGuardEVMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("anvil"):
            raise unittest.SkipTest("anvil unavailable")
        try:
            cls.proc = subprocess.Popen(["anvil", "--port", "18546", "--silent"],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
            for _ in range(50):
                try:
                    rpc("eth_chainId", [])
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Anvil did not become ready")
        except Exception as exc:
            if getattr(cls, "proc", None):
                cls.proc.kill()
            raise unittest.SkipTest(str(exc))

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "proc", None):
            cls.proc.terminate()
            cls.proc.wait(timeout=5)

    def install(self, shadow_code: str) -> None:
        rpc("anvil_setCode", [SHADOW, shadow_code])
        rpc("anvil_setCode", [GUARD, _operate_success_runtime(SHADOW, TARGET)])

    def call(self, address: str, data: str) -> str:
        return rpc("eth_call", [{"to": address, "data": data}, "latest"])

    def test_static_return_and_target_true(self):
        self.install("0x602a60005260206000f3")
        self.assertEqual(self.call(GUARD, "0x11111111"), self.call(SHADOW, "0x11111111"))
        self.assertEqual(self.call(GUARD, "0x36f022aa"), "0x" + "00" * 31 + "01")

    def test_dynamic_bytes_return_is_preserved(self):
        # ABI bytes return: offset=0x20, length=4, payload=deadbeef.
        self.install("0x6020600052600460205263deadbeef60405260606000f3")
        self.assertEqual(self.call(GUARD, "0x11111111"), self.call(SHADOW, "0x11111111"))

    def test_revert_data_is_preserved(self):
        self.install("0x63deadbeef6000526004601cfd")
        with self.assertRaises(RuntimeError) as shadow:
            self.call(SHADOW, "0x11111111")
        with self.assertRaises(RuntimeError) as guarded:
            self.call(GUARD, "0x11111111")
        self.assertIn("deadbeef", str(shadow.exception).lower())
        self.assertIn("deadbeef", str(guarded.exception).lower())

    def test_storage_mutation_and_event_forward(self):
        # SSTORE(0,1), LOG1(topic=0x42), return 0x2a.
        self.install("0x600160005560426000526020600060206000a1602a60005260206000f3")
        sender = rpc("eth_accounts", [])[0]
        tx = {"from": sender, "to": GUARD, "data": "0x11111111", "gas": "0x100000"}
        tx_hash = rpc("eth_sendTransaction", [tx])
        for _ in range(50):
            receipt = rpc("eth_getTransactionReceipt", [tx_hash])
            if receipt:
                break
            time.sleep(0.1)
        self.assertIsNotNone(receipt)
        self.assertEqual(rpc("eth_getStorageAt", [GUARD, "0x0", "latest"]), "0x" + "0" * 63 + "1")
        self.assertEqual(len(receipt["logs"]), 1)

        # The guarded selector must not execute the shadow implementation.
        target_tx = rpc("eth_sendTransaction", [{
            "from": sender, "to": GUARD, "data": "0x36f022aa", "gas": "0x100000"}])
        for _ in range(50):
            if rpc("eth_getTransactionReceipt", [target_tx]):
                break
            time.sleep(0.1)
        self.assertEqual(rpc("eth_getStorageAt", [GUARD, "0x1", "latest"]), "0x" + "0" * 64)

    def test_oracle_override_returns_declared_bytes_and_forwards_other_selectors(self):
        declared = "0x" + "ab" * 40
        runtime = _oracle_forwarding_runtime(SHADOW, TARGET, declared)
        rpc("anvil_setCode", [SHADOW, "0x602a60005260206000f3"])
        rpc("anvil_setCode", [GUARD, runtime])
        self.assertEqual(self.call(GUARD, "0x" + TARGET), declared)
        self.assertEqual(self.call(GUARD, "0x11111111"), self.call(SHADOW, "0x11111111"))

    def test_flash_guard_forwards_success_returndata_for_non_target_selector(self):
        shadow_code = "0x6020600052600460205263deadbeef60405260606000f3"
        rpc("anvil_setCode", [SHADOW, shadow_code])
        rpc("anvil_setCode", [GUARD, _operate_guard_runtime(SHADOW, TARGET)])
        self.assertEqual(self.call(GUARD, "0x11111111"), self.call(SHADOW, "0x11111111"))

    def test_flash_guard_blocks_only_target_selector(self):
        rpc("anvil_setCode", [SHADOW, "0x602a60005260206000f3"])
        rpc("anvil_setCode", [GUARD, _operate_guard_runtime(SHADOW, TARGET)])
        with self.assertRaises(RuntimeError):
            self.call(GUARD, "0x" + TARGET)


if __name__ == "__main__":
    unittest.main()
