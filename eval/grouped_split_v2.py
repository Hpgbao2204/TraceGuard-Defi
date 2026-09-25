"""Deterministic group-aware split for screening protocol v2.

Rows sharing a chain/block or incident are assigned to one connected group.
This module is pure and accepts the normalized rows emitted by
``eval.e1_train.build_dataset``; it does not read the cache or fit a model.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from core.protocol import (
    SCREENING_FEATURE_CONTRACT_VERSION,
    SCREENING_PROTOCOL_VERSION,
    SCREENING_VIEWS,
)


@dataclass(frozen=True)
class SplitManifest:
    protocol_version: str
    feature_contract_version: str
    views: tuple[str, ...]
    seed: int
    target_fractions: tuple[float, float, float]
    groups: dict[str, str]
    partitions: dict[str, tuple[str, ...]]
    achieved_counts: dict[str, int]
    achieved_labels: dict[str, dict[str, int]]
    infeasible_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "feature_contract_version": self.feature_contract_version,
            "views": list(self.views),
            "seed": self.seed,
            "target_fractions": list(self.target_fractions),
            "groups": dict(sorted(self.groups.items())),
            "partitions": {
                name: list(values) for name, values in self.partitions.items()
            },
            "achieved_counts": self.achieved_counts,
            "achieved_labels": self.achieved_labels,
            "infeasible_reason": self.infeasible_reason,
        }


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def _stable_key(value: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def _relation_keys(row: dict[str, Any]) -> tuple[str, ...]:
    keys: list[str] = []
    chain = str(row.get("chain") or row.get("network") or "mainnet")
    block = row.get("block")
    if block is not None:
        keys.append(f"block:{chain}:{block}")
    for field in ("incident_id", "incident", "incident_key"):
        value = row.get(field)
        if value not in (None, ""):
            keys.append(f"incident:{value}")
    return tuple(keys)


def build_groups(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Return transaction hash → connected component ID."""
    hashes = [str(row["tx_hash"]) for row in rows]
    union_find = _UnionFind(hashes)
    first_by_relation: dict[str, str] = {}
    for row in rows:
        tx_hash = str(row["tx_hash"])
        for relation in _relation_keys(row):
            previous = first_by_relation.get(relation)
            if previous is not None:
                union_find.union(tx_hash, previous)
            else:
                first_by_relation[relation] = tx_hash
    root_to_group: dict[str, str] = {}
    groups: dict[str, str] = {}
    for tx_hash in hashes:
        root = union_find.find(tx_hash)
        root_to_group.setdefault(root, f"group-{len(root_to_group):05d}")
        groups[tx_hash] = root_to_group[root]
    return groups


def split_rows(
    rows: list[dict[str, Any]],
    *,
    seed: int = 42,
    fractions: tuple[float, float, float] = (0.64, 0.16, 0.20),
) -> SplitManifest:
    """Assign connected groups without splitting any group across partitions."""
    if len(fractions) != 3 or abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("fractions must contain three values summing to one")
    if not rows:
        raise ValueError("cannot split an empty dataset")
    groups = build_groups(rows)
    row_by_hash = {str(row["tx_hash"]): row for row in rows}
    members: dict[str, list[str]] = defaultdict(list)
    for tx_hash, group in groups.items():
        members[group].append(tx_hash)
    for values in members.values():
        values.sort()

    total = len(rows)
    targets = [fraction * total for fraction in fractions]
    partitions = {name: [] for name in ("fit", "calibration", "test")}
    counts = {name: 0 for name in partitions}
    labels = {name: {"attack": 0, "benign": 0} for name in partitions}
    names = tuple(partitions)

    # Largest groups first prevents a late large block from being split. The
    # stable hash is only a tie-breaker, never a metric-driven seed search.
    ordered_groups = sorted(
        members,
        key=lambda group: (-len(members[group]), _stable_key(group, seed)),
    )
    for group in ordered_groups:
        group_rows = [row_by_hash[tx_hash] for tx_hash in members[group]]
        group_label_counts = {
            "attack": sum(row.get("label") == "attack" for row in group_rows),
            "benign": sum(row.get("label") != "attack" for row in group_rows),
        }
        # Minimize normalized size error first, then label-ratio error. This
        # deterministic rule does not inspect feature values or predictions.
        def score(index: int) -> tuple[float, float, int]:
            projected = counts[names[index]] + len(group_rows)
            # Fill the partition with the largest normalized deficit first.
            # Absolute distance would always prefer the smallest target for
            # early groups and can leave the fit partition empty.
            size_error = projected / max(targets[index], 1.0)
            projected_attack = labels[names[index]]["attack"] + group_label_counts["attack"]
            projected_ratio = projected_attack / max(projected, 1)
            global_ratio = sum(row.get("label") == "attack" for row in rows) / total
            label_error = abs(projected_ratio - global_ratio)
            return size_error, label_error, index

        index = min(range(3), key=score)
        name = names[index]
        partitions[name].extend(members[group])
        counts[name] += len(group_rows)
        labels[name]["attack"] += group_label_counts["attack"]
        labels[name]["benign"] += group_label_counts["benign"]

    infeasible = None
    if any(not partitions[name] for name in names):
        infeasible = "fewer than three assignable groups"
    return SplitManifest(
        protocol_version=SCREENING_PROTOCOL_VERSION,
        feature_contract_version=SCREENING_FEATURE_CONTRACT_VERSION,
        views=SCREENING_VIEWS,
        seed=seed,
        target_fractions=fractions,
        groups=groups,
        partitions={name: tuple(sorted(values)) for name, values in partitions.items()},
        achieved_counts=counts,
        achieved_labels=labels,
        infeasible_reason=infeasible,
    )
