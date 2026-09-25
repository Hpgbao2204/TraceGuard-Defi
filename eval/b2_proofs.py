"""Acquire local Merkle proofs for the B2 transaction-relevant prestate.

Proof acquisition is deliberately resumable. A large mid-block context can
contain thousands of accounts, and a timeout must not discard proofs already
accepted by the archive provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Iterable

from core.env import load_dotenv, resolve_rpc
from core.rpc import RpcClient, RpcError
from eval.replay_context import provider_identity, redacted_diagnostic


DEFAULT_CHUNK_SIZE = 50
DEFAULT_CHUNK_ATTEMPTS = 3
B2_RUNNER = Path(__file__).resolve().parent.parent / "tools" / "geth-replay" / "geth-replay"
BEACON_ROOTS_ADDRESS = "0x000f3df6d732807ef1319fb7b8bb8522d0beac02"
SYSTEM_ADDRESS = "0xfffffffffffffffffffffffffffffffffffffffe"
HISTORY_STORAGE_ADDRESS = "0x0000f90827f1c53a10cb7a02335b175320002935"
SYNTHETIC_SHADOW_ADDRESSES = (
    "0x000000000000000000000000000000000000f1a1",
    "0x000000000000000000000000000000000000f1a2",
    "0x000000000000000000000000000000000000f1a3",
)


def _canonical_address(value: object) -> str:
    if not isinstance(value, str) or not value.lower().startswith("0x"):
        raise ValueError(f"invalid address: {value!r}")
    text = value[2:]
    if len(text) != 40 or any(char not in "0123456789abcdefABCDEF" for char in text):
        raise ValueError(f"invalid address: {value!r}")
    return "0x" + text.lower()


def _canonical_storage_key(value: object) -> str:
    """Return a storage key in the 32-byte JSON-RPC representation.

    prestateTracer may emit a short quantity (and can emit an odd number of
    hex digits).  eth_getProof expects a bytes32-shaped hex string, so the
    representation must be canonicalized before it enters the proof request,
    fingerprint, or authenticated-state pipeline.
    """
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip().lower()
        if text.startswith("0x"):
            text = text[2:]
        if not text or any(char not in "0123456789abcdef" for char in text):
            raise ValueError(f"invalid storage key: {value!r}")
        number = int(text, 16)
    else:
        raise ValueError(f"invalid storage key type: {type(value).__name__}")
    if number < 0 or number >= 1 << 256:
        raise ValueError("storage key is outside uint256 range")
    return f"0x{number:064x}"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def _write_atomic(path: Path, value: object) -> None:
    """Publish a complete JSON artifact, never a partially written one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    _write(temporary, value)
    temporary.replace(path)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_state_header_binding(block: dict, header: dict,
                                   ancestors: list[dict]) -> None:
    """Bind the proof header to the target's canonical parent header."""
    if not ancestors:
        raise RpcError("ancestor context is required for proof acquisition")
    target_number = int(block["number"], 16)
    parent = ancestors[0]
    if int(header.get("number", "-1"), 16) != target_number - 1:
        raise RpcError("proof state header number is not target-1")
    if str(block.get("parentHash", "")).lower() != str(parent.get("hash", "")).lower():
        raise RpcError("target parent does not match ancestor context")
    for field in ("hash", "stateRoot"):
        if str(header.get(field, "")).lower() != str(parent.get(field, "")).lower():
            raise RpcError(f"proof state header {field} is not canonical parent")


def _accounts_from_traces(traces: list[dict], poststates: list[dict] | None = None) -> dict[str, set[str]]:
    """Discover the authenticated closure, including accounts created in diffs."""
    accounts: dict[str, set[str]] = {}
    sources = [row.get("trace") or {} for row in traces]
    for row in poststates or []:
        sources.extend((row.get("prestate") or {}, row.get("poststate") or {}))
        _add_creation_destinations(row.get("calltrace") or {}, accounts)
    for trace in sources:
        for address, raw in trace.items():
            address = address.lower()
            accounts.setdefault(address, set())
            for slot in (raw.get("storage") or {}):
                accounts[address].add(_canonical_storage_key(slot))
    return accounts


def _add_creation_destinations(trace: object, accounts: dict[str, set[str]]) -> None:
    """Discover Geth-reported CREATE destinations for later proof acquisition."""
    if isinstance(trace, dict):
        typ = str(trace.get("type") or "").upper()
        if typ in {"CREATE", "CREATE2"} and isinstance(trace.get("to"), str):
            accounts.setdefault(str(trace["to"]).lower(), set())
        for value in trace.values():
            _add_creation_destinations(value, accounts)
    elif isinstance(trace, list):
        for value in trace:
            _add_creation_destinations(value, accounts)


def _authorization_authorities(context: Path) -> list[str]:
    """Recover EIP-7702 authorities with go-ethereum's canonical signer logic."""
    transactions_path = context / "transactions.json"
    if transactions_path.is_file() and json.loads(
        transactions_path.read_text(encoding="utf-8")
    ) == []:
        return []
    if not B2_RUNNER.is_file():
        raise RuntimeError(f"B2 runner missing: {B2_RUNNER}")
    try:
        result = subprocess.run(
            [str(B2_RUNNER), "--context", str(context), "--list-authorities"],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("authority extraction timed out") from exc
    if result.returncode != 0:
        raise RuntimeError(
            "authority extraction failed: " + result.stderr[-512:]
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("authority extraction returned malformed JSON") from exc
    addresses = payload.get("required_accounts", payload.get("authorities"))
    if not isinstance(addresses, list) or not all(isinstance(a, str) for a in addresses):
        raise RuntimeError("authority extraction returned invalid required accounts")
    return [a.lower() for a in addresses]


def _load_reusable_proofs(context: Path, accounts: dict[str, set[str]]) -> dict[str, dict]:
    """Reuse proofs whose requested address/key set is unchanged across context extension."""
    path = context / "prestate_proofs.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    reusable: dict[str, dict] = {}
    if payload.get("schema_version", 0) < 3:
        return reusable
    for item in payload.get("proofs", []):
        address = str(item.get("address") or "").lower()
        if not isinstance(item.get("code"), str):
            continue
        keys = {_canonical_storage_key(key) for key in item.get("storage_keys", [])}
        if address in accounts and keys == accounts[address]:
            reusable[address] = item
    return reusable


def _authorization_accounts(
    proofs: dict[str, dict], required_accounts: list[str], archive: RpcClient,
    state_block: str,
) -> dict[str, dict]:
    """Bind recovered authorities to authenticated account values for StateDB injection."""
    accounts: dict[str, dict] = {}
    for address in required_accounts:
        item = proofs.get(address)
        if item is None:
            raise RpcError(f"missing proof for EIP-7702 authority {address}")
        proof = item.get("proof") or {}
        code = archive.call("eth_getCode", [address, state_block])
        if not isinstance(code, str):
            raise RpcError(f"eth_getCode returned invalid value for authority {address}")
        # EIP-1186 encodes a non-existent account with zero account fields,
        # including a zero codeHash. Preserve that absence explicitly; do not
        # turn requested zero storage proofs into an existing empty account.
        code_hash = str(proof.get("codeHash", "0x0")).lower()
        exists = code_hash != "0x0" and code_hash != ("0x" + "0" * 64)
        accounts[address] = {
            "balance": proof.get("balance", "0x0"),
            "nonce": int(str(proof.get("nonce", "0x0")), 16),
            "code": code,
            "exists": exists,
            "storage": {
                str(slot.get("key", "")).lower(): str(slot.get("value", "0x0")).lower()
                for slot in proof.get("storageProof", [])
                if slot.get("key")
            },
        }
    return accounts


def _context_fingerprint(block_number: int, state_root: str,
                         accounts: dict[str, set[str]]) -> str:
    canonical = {
        "block": block_number,
        "state_root": state_root,
        "accounts": {address: sorted(keys)
                      for address, keys in sorted(accounts.items())},
    }
    return hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def _chunked(values: list[str], size: int) -> Iterable[tuple[int, list[str]]]:
    for index in range(0, len(values), size):
        yield index // size, values[index:index + size]


def _load_progress(context: Path, fingerprint: str) -> tuple[dict, dict[str, dict]]:
    """Load only chunk artifacts belonging to the current proof request."""
    progress_path = context / "proof_progress.json"
    if not progress_path.is_file():
        return {"context_fingerprint": fingerprint}, {}
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if progress.get("context_fingerprint") != fingerprint:
        return {"context_fingerprint": fingerprint}, {}
    chunk_dir = context / "proof_chunks"
    proofs: dict[str, dict] = {}
    for chunk_name in progress.get("chunk_files", []):
        chunk_path = chunk_dir / chunk_name
        if not chunk_path.is_file():
            continue
        chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
        if (chunk.get("context_fingerprint") != fingerprint
                or chunk.get("schema_version", 0) < 3):
            continue
        for item in chunk.get("proofs", []):
            proofs[item["address"]] = item
    return progress, proofs


def _fetch_proof(archive: RpcClient, address: str, keys: list[str],
                 state_block: str, attempts: int,
                 backoff_seconds: float = 1.0) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            proof = archive.call("eth_getProof", [address, keys, state_block])
            if not isinstance(proof, dict) or not isinstance(proof.get("accountProof"), list):
                raise RpcError("eth_getProof returned no accountProof")
            code = archive.call("eth_getCode", [address, state_block])
            if not isinstance(code, str):
                raise RpcError("eth_getCode returned invalid code")
            return {"address": address, "storage_keys": keys,
                    "code": code, "proof": proof}
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(backoff_seconds * (attempt + 1))
    assert last_error is not None
    raise last_error


def _fetch_proof_key_batched(archive: RpcClient, address: str, keys: list[str],
                             state_block: str, attempts: int,
                             keys_per_request: int) -> dict:
    """Fetch one account proof while bounding the eth_getProof key list.

    The account proof is identical across requests; storage proofs are merged
    by key. This is only a transport-size mitigation and does not weaken
    proof verification.
    """
    if keys_per_request < 1 or len(keys) <= keys_per_request:
        return _fetch_proof(archive, address, keys, state_block, attempts)
    merged = None
    code = None
    storage = {}
    for start in range(0, len(keys), keys_per_request):
        item = _fetch_proof(archive, address, keys[start:start + keys_per_request],
                            state_block, attempts)
        proof = item["proof"]
        if merged is None:
            merged = dict(proof)
            merged["storageProof"] = []
        elif proof.get("accountProof") != merged.get("accountProof"):
            raise RpcError("eth_getProof accountProof changed between key batches")
        for entry in proof.get("storageProof", []):
            storage[str(entry.get("key"))] = entry
        code = item["code"]
    assert merged is not None
    merged["storageProof"] = list(storage.values())
    return {"address": address, "storage_keys": keys, "code": code, "proof": merged}


def acquire(context: Path, archive: RpcClient, *,
            chunk_size: int = DEFAULT_CHUNK_SIZE,
            chunk_attempts: int = DEFAULT_CHUNK_ATTEMPTS,
            keys_per_request: int | None = None,
            extra_footprint: dict[str, set[str]] | None = None,
            include_synthetic_shadows: bool = False) -> dict:
    if chunk_size < 1 or chunk_attempts < 1:
        raise ValueError("chunk_size and chunk_attempts must be positive")
    block = json.loads((context / "block.json").read_text())
    block_number = int(block["number"], 16)
    state_block = hex(block_number - 1)
    header = archive.call("eth_getBlockByNumber", [state_block, False])
    if not isinstance(header, dict) or not header.get("stateRoot"):
        raise RpcError("state-block header/stateRoot unavailable")
    try:
        ancestors = json.loads((context / "ancestors.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RpcError("ancestor context is required for proof acquisition") from exc
    if not isinstance(ancestors, list):
        raise RpcError("ancestor context must be a JSON list")
    _validate_state_header_binding(block, header, ancestors)
    traces = json.loads((context / "prestates.json").read_text())
    poststate_path = context / "poststates.json"
    poststates = json.loads(poststate_path.read_text()) if poststate_path.is_file() else []
    accounts = _accounts_from_traces(traces, poststates)
    for raw_address, raw_slots in (extra_footprint or {}).items():
        address = _canonical_address(raw_address)
        slots = accounts.setdefault(address, set())
        slots.update(_canonical_storage_key(slot) for slot in raw_slots)
    authorities = _authorization_authorities(context)
    system_accounts: list[str] = []
    if block.get("parentBeaconBlockRoot"):
        # SYSTEM_ADDRESS is only the synthetic caller for PreExecution.  It
        # is not a historical contract whose account must be proof-acquired.
        system_accounts.extend((BEACON_ROOTS_ADDRESS, HISTORY_STORAGE_ADDRESS))
        raw_timestamp = block.get("timestamp", "0x0")
        timestamp = int(raw_timestamp, 16) if isinstance(raw_timestamp, str) else int(raw_timestamp)
        accounts.setdefault(BEACON_ROOTS_ADDRESS, set())
        accounts.setdefault(HISTORY_STORAGE_ADDRESS, set())
        accounts[BEACON_ROOTS_ADDRESS].add(
            _canonical_storage_key(timestamp % 8191)
        )
        accounts[BEACON_ROOTS_ADDRESS].add(
            _canonical_storage_key((timestamp % 8191) + 8191)
        )
        accounts[HISTORY_STORAGE_ADDRESS].add(
            _canonical_storage_key((block_number - 1) % 8191)
        )
    for address in authorities:
        accounts.setdefault(address, set())
    if include_synthetic_shadows:
        # Synthetic mutation shadows must have an authenticated non-existence
        # proof before the runner is allowed to install code at them. Keeping
        # them in the proof bundle makes the reservation auditable and
        # prevents a fixed address from silently colliding with real state.
        for address in SYNTHETIC_SHADOW_ADDRESSES:
            accounts.setdefault(address, set())
    for address in system_accounts:
        accounts.setdefault(address, set())
    fingerprint = _context_fingerprint(block_number, header["stateRoot"], accounts)
    progress, known_proofs = _load_progress(context, fingerprint)
    known_proofs.update(_load_reusable_proofs(context, accounts))
    addresses = sorted(accounts)
    chunk_dir = context / "proof_chunks"
    started = time.monotonic()
    failures: list[dict] = []
    chunk_files: list[str] = list(progress.get("chunk_files", []))

    for chunk_index, chunk_addresses in _chunked(addresses, chunk_size):
        chunk_name = f"chunk-{chunk_index:05d}.json"
        chunk_proofs: list[dict] = []
        chunk_failures: list[dict] = []
        for address in chunk_addresses:
            if address in known_proofs:
                chunk_proofs.append(known_proofs[address])
                continue
            keys = sorted(accounts[address])
            try:
                item = (_fetch_proof_key_batched(
                    archive, address, keys, state_block, chunk_attempts,
                    keys_per_request) if keys_per_request else _fetch_proof(
                        archive, address, keys, state_block, chunk_attempts))
                known_proofs[address] = item
                chunk_proofs.append(item)
            except Exception as exc:
                chunk_failures.append({
                    "address": address,
                    "storage_keys": keys,
                    "failure_class": "proof_transport_or_provider",
                    "diagnostic": redacted_diagnostic(exc),
                })
        _write_atomic(chunk_dir / chunk_name, {
            "schema_version": 3,
            "context_fingerprint": fingerprint,
            "chunk_index": chunk_index,
            "addresses": chunk_addresses,
            "proofs": chunk_proofs,
            "failures": chunk_failures,
        })
        if chunk_name not in chunk_files:
            chunk_files.append(chunk_name)
        failures.extend(chunk_failures)
        _write_atomic(context / "proof_progress.json", {
            "schema_version": 3,
            "context_fingerprint": fingerprint,
            "block": block_number,
            "state_block": block_number - 1,
            "chunk_size": chunk_size,
            "chunk_attempts": chunk_attempts,
            "total_account_count": len(addresses),
            "proof_count": len(known_proofs),
            "failure_count": len(failures),
            "chunk_files": sorted(chunk_files),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        })

    proofs = [known_proofs[address] for address in addresses
              if address in known_proofs]
    authorization_accounts = _authorization_accounts(
        known_proofs, authorities + system_accounts, archive, state_block
    )
    _write_atomic(context / "authorization_accounts.json", authorization_accounts)
    payload = {
        "schema_version": 3,
        "block": block_number,
        "state_block": block_number - 1,
        "state_root": header["stateRoot"],
        "account_count": len(accounts),
        "proof_count": len(proofs),
        "failures": failures,
        "chunk_size": chunk_size,
        "chunk_attempts": chunk_attempts,
        "resumed_proof_count": len(proofs),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        "provider_identity": provider_identity(archive.url),
        "prestate_proof_complete": not failures and len(proofs) == len(accounts),
        "authorization_count": len(authorities),
        "system_account_count": len(system_accounts),
        "authorization_accounts_path": "authorization_accounts.json",
        "global_state_root_scope": "out_of_scope: full world-state trie is not reconstructed",
        "note": "Proofs cover transaction-relevant account/storage cells at block-1.",
    }
    _write_atomic(context / "prestate_proofs.json", {
        "schema_version": 3,
        "header": header,
        "proofs": proofs,
    })
    payload["input_hash"] = _sha(context / "prestate_proofs.json")
    _write_atomic(context / "proof_manifest.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--rpc", default=None)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-attempts", type=int, default=DEFAULT_CHUNK_ATTEMPTS)
    parser.add_argument("--keys-per-request", type=int, default=None,
                        help="split one account's storage keys across eth_getProof requests")
    parser.add_argument(
        "--include-synthetic-shadows", action="store_true",
        help="acquire absence proofs for reserved mutation shadow addresses",
    )
    parser.add_argument(
        "--extra-footprint", type=Path,
        help="JSON object mapping addresses to additional storage slots discovered by a prior failed replay",
    )
    args = parser.parse_args()
    load_dotenv()
    rpc = args.rpc or resolve_rpc("mainnet")
    if not rpc:
        parser.error("missing archive RPC")
    extra: dict[str, set[str]] = {}
    if args.extra_footprint:
        payload = json.loads(args.extra_footprint.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            parser.error("extra footprint must be a JSON object")
        for address, slots in payload.items():
            if not isinstance(slots, list) or not all(isinstance(slot, str) for slot in slots):
                parser.error("extra footprint values must be lists of slot strings")
            extra[str(address)] = set(slots)
    result = acquire(args.context, RpcClient(rpc, timeout=60, attempts=2),
                     chunk_size=args.chunk_size, chunk_attempts=args.chunk_attempts,
                     keys_per_request=args.keys_per_request,
                     extra_footprint=extra,
                     include_synthetic_shadows=args.include_synthetic_shadows)
    print(json.dumps(result, indent=2))
    return 0 if result["prestate_proof_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
