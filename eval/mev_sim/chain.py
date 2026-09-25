"""Local anvil chain (no fork, no RPC key) and the deployed simulation world.

Every transaction is mined in its own anvil block (automine), so a builder "slot" is a range of
anvil blocks whose order the builder controls exactly. Gas price and base fee are zero and
``--auto-impersonate`` is on, so any address can send without ETH or signing.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address

ARTIFACTS = Path(__file__).resolve().parent / "contracts" / "artifacts.json"
TX_GAS = 3_000_000
UINT_MAX = 2**256 - 1

TOPIC_TRANSFER = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
TOPIC_SWAP = "0x" + keccak(text="Swap(address,uint256,uint256,uint256,uint256,address)").hex()
TOPIC_SYNC = "0x" + keccak(text="Sync(uint112,uint112)").hex()


def selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def calldata(signature: str, *args) -> str:
    types = signature[signature.index("(") + 1 : -1]
    arg_types = _split_types(types)
    return "0x" + (selector(signature) + encode(arg_types, list(args))).hex()


def _split_types(types: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in types:
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        depth += ch == "("
        depth -= ch == ")"
        cur += ch
    if cur:
        out.append(cur)
    return out


def find_anvil() -> str | None:
    env = os.environ.get("ANVIL")
    if env and Path(env).exists():
        return env
    for cand in (shutil.which("anvil"), str(Path.home() / ".foundry" / "bin" / "anvil"), "/opt/foundry/anvil"):
        if cand and Path(cand).exists():
            return cand
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Anvil:
    """A throwaway anvil process."""

    def __init__(self, binary: str | None = None, port: int | None = None):
        self.binary = binary or find_anvil()
        if not self.binary:
            raise RuntimeError("anvil not found; install foundry or set ANVIL=/path/to/anvil")
        self.port = port or _free_port()
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "Anvil":
        self.proc = subprocess.Popen(
            [self.binary, "--port", str(self.port), "--silent", "--auto-impersonate",
             "--gas-price", "0", "--block-base-fee-per-gas", "0", "--gas-limit", "1000000000",
             "--chain-id", "31337"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f"http://127.0.0.1:{self.port}"
        for _ in range(100):
            try:
                requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}, timeout=1)
                return self
            except requests.ConnectionError:
                time.sleep(0.05)
        raise RuntimeError("anvil did not start")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, *exc) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=10)


@dataclass
class Receipt:
    status: int
    logs: list[dict]
    gas_used: int


class Rpc:
    def __init__(self, url: str):
        self.url = url
        self.session = requests.Session()
        self._id = 0

    def call(self, method: str, params: list | None = None):
        self._id += 1
        r = self.session.post(self.url, json={"jsonrpc": "2.0", "id": self._id, "method": method,
                                              "params": params or []}, timeout=60)
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"{method}: {body['error']}")
        return body["result"]

    def send(self, frm: str, to: str | None, data: str) -> Receipt:
        tx = {"from": frm, "data": data, "gas": hex(TX_GAS), "gasPrice": "0x0"}
        if to:
            tx["to"] = to
        h = self.call("eth_sendTransaction", [tx])
        rc = self.call("eth_getTransactionReceipt", [h])
        while rc is None:  # automine is normally synchronous; guard against a late receipt
            time.sleep(0.001)
            rc = self.call("eth_getTransactionReceipt", [h])
        return Receipt(int(rc["status"], 16), rc["logs"], int(rc["gasUsed"], 16)) if to else _deploy_receipt(rc)

    def eth_call(self, to: str, data: str) -> bytes:
        return bytes.fromhex(self.call("eth_call", [{"to": to, "data": data}, "latest"])[2:])

    def snapshot(self) -> str:
        return self.call("evm_snapshot")

    def revert(self, snap: str) -> None:
        if not self.call("evm_revert", [snap]):
            raise RuntimeError("evm_revert failed")


def _deploy_receipt(rc: dict) -> Receipt:
    r = Receipt(int(rc["status"], 16), rc["logs"], int(rc["gasUsed"], 16))
    r.contract = to_checksum_address(rc["contractAddress"])  # type: ignore[attr-defined]
    return r


def addr(i: int, tag: int) -> str:
    """Deterministic simulation address (tag separates users, bots, throwaway accounts)."""
    return to_checksum_address(keccak(tag.to_bytes(4, "big") + i.to_bytes(8, "big"))[-20:])


TAG_USER, TAG_SEARCHER, TAG_FRESH, TAG_DEPLOYER = 1, 2, 3, 9
N_USERS, N_SEARCHERS = 24, 24
E18 = 10**18


@dataclass
class World:
    """Addresses of the deployed simulation: tokens A/B/C, pools P1,P2 (A/B) and P3 (B/C)."""
    rpc: Rpc
    tokens: dict[str, str]
    pools: dict[str, str]
    pool_tokens: dict[str, tuple[str, str]]
    router: str
    aggregator: str
    users: list[str]
    searchers: list[str]
    names: dict[str, str] = field(default_factory=dict)

    def reserves(self) -> dict[str, tuple[int, int]]:
        out = {}
        for name, p in self.pools.items():
            r0, r1, _ = decode(["uint112", "uint112", "uint32"], self.rpc.eth_call(p, calldata("getReserves()")))
            out[p] = (r0, r1)
        return out

    def lp_supply(self, pool: str) -> int:
        return decode(["uint256"], self.rpc.eth_call(pool, calldata("totalSupply()")))[0]


INITIAL_LIQUIDITY = {  # pool -> (token x, amount x, token y, amount y), whole tokens
    "P1": ("A", 1_000, "B", 2_000_000),
    "P2": ("A", 600, "B", 1_200_000),
    "P3": ("B", 2_000_000, "C", 2_000_000),
}


def deploy_world(rpc: Rpc) -> World:
    art = json.loads(ARTIFACTS.read_text())["contracts"]
    dep = addr(0, TAG_DEPLOYER)

    def deploy(name: str, types: list[str] = (), args: list = ()) -> str:
        code = art[name]["bytecode"] + (encode(list(types), list(args)).hex() if types else "")
        rc = rpc.send(dep, None, code)
        assert rc.status == 1, name
        return rc.contract  # type: ignore[attr-defined]

    tokens = {s: deploy("SimToken", ["string", "string"], [f"Token {s}", s]) for s in "ABC"}
    pools, pool_tokens = {}, {}
    for pname, (x, _, y, _) in INITIAL_LIQUIDITY.items():
        p = deploy("SimPair", ["address", "address"], [tokens[x], tokens[y]])
        pools[pname] = p
        t0, t1 = sorted([tokens[x], tokens[y]], key=lambda a: int(a, 16))
        pool_tokens[p] = (t0, t1)
    router = deploy("SimRouter")
    aggregator = deploy("SimAggregator")
    for pname, (x, ax, y, ay) in INITIAL_LIQUIDITY.items():
        p = pools[pname]
        for tok, amt in ((x, ax), (y, ay)):
            assert rpc.send(dep, tokens[tok], calldata("mint(address,uint256)", p, amt * E18)).status == 1
        assert rpc.send(dep, p, calldata("mint(address)", dep)).status == 1

    users = [addr(i, TAG_USER) for i in range(N_USERS)]
    searchers = [addr(i, TAG_SEARCHER) for i in range(N_SEARCHERS)]
    for who in users + searchers:
        for tok in tokens.values():
            rpc.send(dep, tok, calldata("mint(address,uint256)", who, 10**12 * E18))
            for spender in (router, aggregator):
                rpc.send(who, tok, calldata("approve(address,uint256)", spender, UINT_MAX))
    for who in searchers:  # JIT liquidity providers withdraw LP through the router
        for p in pools.values():
            rpc.send(who, p, calldata("approve(address,uint256)", router, UINT_MAX))

    names = {v: k for k, v in {**tokens, **pools, "router": router, "aggregator": aggregator}.items()}
    names[router], names[aggregator] = "router", "aggregator"
    return World(rpc, tokens, pools, pool_tokens, router, aggregator, users, searchers, names)
