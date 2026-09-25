"""Build objective protocol/family relation evidence for hard-negative leads.

This is an evidence collector only.  It never assigns review labels or turns
shared addresses/selectors into same-protocol claims.
"""
from __future__ import annotations

import csv
import hashlib
import http.client
import json
import os
import ssl
from urllib.parse import urlparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "eval/results/hard_negative_review_queue.csv"
CACHE = ROOT / "eval/results/e1_trace_cache.jsonl"
OUT = ROOT / "eval/results/hard_negative_anchor_evidence_v2.json"
CHECKPOINT = ROOT / "eval/results/hard_negative_anchor_evidence_v2.checkpoint.json"
EIP1967_IMPL = "0x" + "360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_BEACON = "0x" + "a3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
BEACON_IMPLEMENTATION_SELECTOR = "0x5c60da1b"
INFRA = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH mainnet
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC mainnet
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT mainnet
    "0x4200000000000000000000000000000000000006",  # WETH on OP-like chains
}


def _env_urls() -> list[str]:
    urls = []
    preferred = ("ARCHIVE_RPC", "ALCHEMY", "INFURA", "ANKR_ETHEREUM",
                 "NODEREAL", "NODIES", "DRPC", "ETOX", "CHAINSTACK_RETH",
                 "ONFINALITY", "LIQUIFY", "BOAR", "BOLTRPC", "BlockPI",
                 "CHAINSTACK_ETH_HTTP_URL")
    values = {key: os.environ.get(key, "") for key in preferred}
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(errors="ignore").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if key in values: values[key] = value
    for key in preferred:
        value = values[key].strip().strip('"')
        if value.startswith(("http://", "https://")) and value not in urls:
            urls.append(value)
    if not urls:
        raise RuntimeError("no archive RPC configured")
    return urls


class RPC:
    def __init__(self, url: str):
        self.url, self.n = url, 0
        parsed = urlparse(url)
        self.path = parsed.path or "/"
        if parsed.query:
            self.path += "?" + parsed.query
        self.host = parsed.netloc
        self.conn = http.client.HTTPSConnection(
            self.host, timeout=8, context=ssl.create_default_context())

    def call(self, method: str, params: list):
        self.n += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self.n,
                           "method": method, "params": params}).encode()
        try:
            self.conn.request("POST", self.path, body,
                              {"Content-Type": "application/json"})
            response = self.conn.getresponse()
            raw = response.read()
        except Exception:
            self.conn.close()
            self.conn = http.client.HTTPSConnection(
                self.host, timeout=8, context=ssl.create_default_context())
            raise
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}: {raw[:200]!r}")
        data = json.loads(raw)
        if data.get("error"):
            raise RuntimeError(f"{method}: {data['error']}")
        return data.get("result")


class RPCPool:
    def __init__(self, urls: list[str]):
        self.clients = [RPC(url) for url in urls]
        self.errors: list[str] = []

    def call(self, method: str, params: list):
        last = None
        for client in self.clients:
            try:
                return client.call(method, params)
            except Exception as exc:
                last = exc
                self.errors.append(f"{method}:{type(exc).__name__}")
        raise RuntimeError(f"all RPC fallbacks failed for {method}: {last}")

    @property
    def n(self) -> int:
        return sum(client.n for client in self.clients)


def _addresses(item: dict) -> set[str]:
    trace = item.get("trace") or {}
    values = set()
    for key in ("from", "to"):
        if trace.get(key): values.add(str(trace[key]).lower())
    for call in trace.get("flat_calls") or []:
        for key in ("from", "to"):
            if call.get(key): values.add(str(call[key]).lower())
    return {a for a in values if a not in INFRA}


def _code(rpc: RPC, address: str, block: int) -> str:
    return str(rpc.call("eth_getCode", [address, hex(block)]) or "0x").lower()


def _slot(rpc: RPC, address: str, slot: str, block: int) -> str:
    return str(rpc.call("eth_getStorageAt", [address, slot, hex(block)]) or "0x").lower()


def _impl(rpc: RPC, address: str, block: int) -> dict:
    impl = _slot(rpc, address, EIP1967_IMPL, block)
    beacon = _slot(rpc, address, EIP1967_BEACON, block)
    def tail(value):
        raw = value[2:] if value.startswith("0x") else value
        return "0x" + raw[-40:] if int(raw or "0", 16) else None
    beacon_address = tail(beacon)
    beacon_impl = None
    if beacon_address:
        result = rpc.call("eth_call", [{"to": beacon_address,
                                         "data": BEACON_IMPLEMENTATION_SELECTOR}, hex(block)])
        beacon_impl = tail(str(result or "0x"))
    return {"implementation": tail(impl), "beacon": beacon_address,
            "beacon_implementation": beacon_impl}


def build() -> dict:
    cache = {json.loads(line)["tx_hash"].lower(): json.loads(line)
             for line in CACHE.read_text().splitlines() if line.strip()}
    errors = []
    for url in _env_urls():
        try:
            rpc = RPC(url)
            if rpc.call("web3_clientVersion", []):
                break
        except Exception as exc:
            errors.append(type(exc).__name__)
    else:
        raise RuntimeError("all configured archive RPC endpoints failed: " + ",".join(errors))
    # Keep every configured endpoint for per-request fallback.  The first
    # endpoint is only the capability probe, not the sole producer.
    rpc = RPCPool(_env_urls())
    cache_meta = {}
    if CHECKPOINT.is_file():
        try:
            cache_meta = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache_meta = {}
    for row in csv.DictReader(QUEUE.open(newline="", encoding="utf-8")):
        for tx_key, block_key in (("attack_tx_hash", "attack_block"),
                                  ("candidate_tx_hash", "candidate_block")):
            tx = row[tx_key].lower()
            if tx in cache_meta and all("error" not in item
                                        for item in cache_meta[tx].get("addresses", [])):
                continue
            item = cache[tx]
            block = int(row[block_key])
            details = []
            prior = {x["address"]: x for x in cache_meta.get(tx, {}).get("addresses", [])}
            for address in sorted(_addresses(item)):
                if address in prior and "error" not in prior[address]:
                    details.append(prior[address]); continue
                try:
                    code = _code(rpc, address, block)
                    digest = hashlib.sha256(bytes.fromhex(code.removeprefix("0x"))).hexdigest()
                    details.append({"address": address, "bytecode_sha256": digest,
                                    "code_present": code not in ("0x", "0x0"),
                                    "proxy": _impl(rpc, address, block)})
                except Exception as exc:
                    details.append({"address": address, "error": type(exc).__name__})
            cache_meta[tx] = {"tx_hash": tx, "block": block, "addresses": details}
            CHECKPOINT.write_text(json.dumps(cache_meta, indent=2) + "\n",
                                  encoding="utf-8", newline="\n")
    evidence = []
    for row in csv.DictReader(QUEUE.open(newline="", encoding="utf-8")):
        a, c = cache_meta[row["attack_tx_hash"].lower()], cache_meta[row["candidate_tx_hash"].lower()]
        a_hashes = {x["bytecode_sha256"] for x in a["addresses"]
                    if x.get("code_present") and "bytecode_sha256" in x}
        c_hashes = {x["bytecode_sha256"] for x in c["addresses"]
                    if x.get("code_present") and "bytecode_sha256" in x}
        evidence.append({"incident_tx_hash": a["tx_hash"],
                         "candidate_tx_hash": c["tx_hash"],
                         "evidence": "same_runtime_bytecode" if a_hashes & c_hashes else "unresolved",
                         "shared_bytecode_sha256": sorted(a_hashes & c_hashes),
                         "review_required": True})
    return {"schema_version": 2, "policy": "objective evidence only; no labels inferred",
            "source_queue": str(QUEUE.relative_to(ROOT)),
            "candidate_count": len(evidence), "rpc_calls": rpc.n,
            "evidence": evidence, "address_metadata": cache_meta}


if __name__ == "__main__":
    payload = build()
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_count": payload["candidate_count"],
                      "same_runtime_bytecode": sum(x["evidence"] != "unresolved" for x in payload["evidence"]),
                      "rpc_calls": payload["rpc_calls"]}, indent=2))
