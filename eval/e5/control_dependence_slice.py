"""Conservative dynamic control-dependence edges from captured frame bytecode."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from bisect import bisect_right
from pathlib import Path


TERMINAL = {0x00, 0xF3, 0xFD, 0xFE, 0xFF}


def instructions(code: str) -> list[tuple[int, int, int]]:
    raw = bytes.fromhex(code[2:] if code.startswith("0x") else code)
    result = []
    pc = 0
    while pc < len(raw):
        op = raw[pc]
        size = 1 + (op - 0x5F if 0x60 <= op <= 0x7F else 0)
        result.append((pc, op, size))
        pc += size
    return result


def _postdominators(blocks: list[int], successors: dict[int, set[int]], max_iterations: int = 5000) -> dict[int, int] | None:
    bit = {block: 1 << index for index, block in enumerate(blocks)}
    universe = (1 << len(blocks)) - 1
    post = {block: (bit[block] if not successors.get(block) else universe) for block in blocks}
    changed = True
    iterations = 0
    while changed:
        iterations += 1
        if iterations > max_iterations:
            return None
        changed = False
        for block in blocks:
            succ = successors.get(block, set())
            if not succ:
                new = bit[block]
            else:
                common = universe
                for successor in succ:
                    common &= post[successor]
                new = bit[block] | common
            if new != post[block]:
                post[block] = new
                changed = True
    return post


def frame_control_edges(frame_id: str, code: str, observations: list[dict]) -> tuple[list[dict], list[dict]]:
    ins = instructions(code)
    by_pc = {pc: (op, size) for pc, op, size in ins}
    starts = {0}
    for pc, op, size in ins:
        if op == 0x5B:
            starts.add(pc)
        if op in {0x56, 0x57} or op in TERMINAL:
            if pc + size in by_pc:
                starts.add(pc + size)
    branch_by_pc = defaultdict(list)
    for obs in observations:
        if obs.get("frame_id") == frame_id and obs.get("kind") in {"branch_predicate", "jump_target"}:
            if isinstance(obs.get("branch_target"), int):
                branch_by_pc[obs["pc"]].append(obs["branch_target"])
                starts.add(obs["branch_target"])
    starts = sorted(start for start in starts if start in by_pc)
    if len(starts) > 512:
        return [], [{"frame_id": frame_id, "status": "UNRESOLVED", "reason": "CFG_TOO_LARGE", "block_count": len(starts)}]
    block_of = {}
    block_ins = {}
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else None
        block_ins[start] = []
        for pc, op, size in ins:
            if pc < start or (end is not None and pc >= end):
                continue
            block_of[pc] = start
            block_ins[start].append((pc, op, size))
    successors = {start: set() for start in starts}
    unresolved = []
    for start, body in block_ins.items():
        if not body:
            continue
        pc, op, size = body[-1]
        fallthrough = pc + size if pc + size in block_of else None
        if op == 0x57:
            targets = {target for target in branch_by_pc.get(pc, []) if target in block_of}
            if not targets or fallthrough is None:
                unresolved.append({"pc": pc, "reason": "conditional successor missing"})
            successors[start] |= targets
            if fallthrough is not None:
                successors[start].add(fallthrough)
        elif op == 0x56:
            targets = {target for target in branch_by_pc.get(pc, []) if target in block_of}
            if not targets:
                unresolved.append({"pc": pc, "reason": "dynamic jump target missing"})
            successors[start] |= targets
        elif op not in TERMINAL and fallthrough is not None:
            successors[start].add(fallthrough)
    post = _postdominators(starts, successors)
    if post is None:
        return [], [{"frame_id": frame_id, "status": "UNRESOLVED", "reason": "POSTDOMINATOR_DID_NOT_CONVERGE", "block_count": len(starts)}]
    edges = []
    proof = []
    frame_obs = [(idx, obs) for idx, obs in enumerate(observations) if obs.get("frame_id") == frame_id]
    obs_blocks = {idx: block_of.get(obs.get("pc")) for idx, obs in frame_obs}
    positions_by_block = defaultdict(list)
    for idx, block in obs_blocks.items():
        if block is not None:
            positions_by_block[block].append(idx)
    for idx, branch in frame_obs:
        if branch.get("kind") != "branch_predicate" or not isinstance(branch.get("branch_target"), int):
            continue
        branch_block = block_of.get(branch.get("pc"))
        target_block = block_of.get(branch["branch_target"])
        if branch_block is None or target_block is None:
            proof.append({"observation_id": branch["observation_id"], "status": "UNRESOLVED"})
            continue
        block_bit = {block: 1 << index for index, block in enumerate(starts)}
        strict_mask = post.get(branch_block, 0) & ~block_bit[branch_block]
        strict = [candidate for candidate in starts if strict_mask & block_bit[candidate]]
        if not strict:
            proof.append({"observation_id": branch["observation_id"], "status": "UNRESOLVED", "reason": "no post-dominator"})
            continue
        ipdom = min(strict, key=lambda candidate: post.get(candidate, 0).bit_count())
        region = set()
        for successor in successors.get(branch_block, set()):
            queue = deque([successor])
            seen = set()
            while queue:
                current = queue.popleft()
                if current in seen or current == ipdom:
                    continue
                seen.add(current)
                region.add(current)
                queue.extend(successors.get(current, set()))
        proof.append({"observation_id": branch["observation_id"], "status": "RESOLVED", "ipdom_block": ipdom, "region_blocks": sorted(region)})
        join_positions = positions_by_block.get(ipdom, [])
        stop = next((position for position in join_positions if position > idx), len(observations))
        for region_block in region:
            for later_idx in positions_by_block.get(region_block, []):
                if idx < later_idx < stop:
                    later = observations[later_idx]
                    edges.append({"src": branch["observation_id"], "dst": later["observation_id"], "kind": "control_dependence", "ipdom_block": ipdom})
    return edges, proof + unresolved


def _slice_frames(provenance: dict, sink: str | None) -> set[str] | None:
    if sink is None:
        return None
    values = {value["value_id"] for value in provenance.get("values", [])}
    incoming = defaultdict(list)
    for value in provenance.get("values", []):
        for parent in value.get("parents", []):
            if parent in values:
                incoming[value["value_id"]].append(parent)
    for observation in provenance.get("observations", []):
        for value_id in observation.get("values", []):
            if value_id in values:
                incoming[observation["observation_id"]].append(value_id)
    seen = set()
    queue = deque([sink])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(incoming.get(current, []))
    return {observation.get("frame_id") for observation in provenance.get("observations", []) if observation.get("observation_id") in seen}


def build_control_slice(provenance: dict, sink: str | None = None) -> dict:
    observations = provenance.get("observations", [])
    edges = []
    proofs = []
    relevant_frames = _slice_frames(provenance, sink)
    for frame_id, code in provenance.get("frame_code", {}).items():
        if relevant_frames is not None and frame_id not in relevant_frames:
            continue
        frame_edges, frame_proof = frame_control_edges(frame_id, code, observations)
        edges.extend(frame_edges)
        proofs.extend(frame_proof)
    return {
        "schema_version": "e5-control-dependence-slice-v1",
        "edge_count": len(edges),
        "resolved_scope_count": sum(p.get("status") == "RESOLVED" for p in proofs),
        "unresolved_scope_count": sum(p.get("status") != "RESOLVED" for p in proofs),
        "sink_observation_id": sink,
        "frame_scope": "harm_slice_ancestors" if sink else "all_frames",
        "edges": edges,
        "scope_proofs": proofs,
        "interpretation": "Edges are emitted only when both dynamic successors and an immediate post-dominator are established from captured bytecode."
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sink-observation-id")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text())
    result = build_control_slice(payload["provenance"], args.sink_observation_id)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
