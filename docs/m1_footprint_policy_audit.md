# M1 footprint-policy audit

This is an audit of the fresh canonical target-2 closure run. It does not
change the four-case matrix, acceptance gate, or three-round bound.

## Scope and provenance

- Replay source commit: `14b7d17`
- Context: block `22781962`, target index `2`
- Closure: fresh proof acquisition, three rounds, no prior footprint
- Canonical output: `/tmp/trafisec-m1-freeze-2/closure.round-{1,2,3}.json`

## Round-by-round observations

### Round 1

The guard reported five dependency groups:

- two `SLOAD` slots for `0x3328...9c49`;
- one account read for the zero address;
- one `SLOAD` slot for `0xfc27...3143`;
- one `SLOAD` slot for `0x79c5...597e`.

The affected accounts were already present in the discovered account
footprint, but the exact storage cells were not. These are therefore an
acquisition-coverage gap: the current `prestateTracer`/`callTracer` artifact
does not provide a complete `(execution account, storage slot)` read
footprint. The guard correctly rejected them.

### Round 2

After acquiring round-1 cells, replay exposed a large set of slots for
`0x017e...1987`, plus slots for WETH and another account. The account was
already known from the context, while the slots were not. The evidence proves
that the current initial footprint is incomplete, but the stored artifacts do
not retain the opcode PC/frame mapping needed to prove whether these reads
were already observable in a canonical trace or became reachable only after
sequential prefix state changes.

Classification: `UNRESOLVED_READ_PROVENANCE` (not silently classified as
sequentially emergent).

### Round 3

The remaining failures were repeated/new `SLOAD`/`SSTORE` cells for WETH and
one additional account. As in round 2, the guard records the operation class,
address, and slot, but not the exact call frame/PC provenance. The current
artifact is therefore insufficient to distinguish deterministic acquisition
from sequential emergence for these cells.

Classification: `UNRESOLVED_READ_PROVENANCE`.

## Policy classification

| Category | Current evidence | Decision |
|---|---|---|
| Deterministic acquisition gap | Account reads and storage reads are observed by the authenticated guard, but the acquisition artifact lacks complete account+slot runtime mapping. | Fix acquisition only if a canonical trace can provide the mapping; do not weaken the guard. |
| Sequentially emergent dependency | Not proven by the current artifacts; a slot appearing in a later round alone is not sufficient proof. | Requires explicit per-frame/state-transition provenance before being labelled emergent. |
| Unsupported/non-expandable | No transport failure or proof-verification failure was observed; the unresolved issue is missing read provenance. | Keep the case `INCONCLUSIVE`; do not increase rounds or infer zero state. |

## Required next design step

Acquisition must persist a deterministic read-footprint artifact containing at
least `(tx index, call depth/frame, execution address, opcode, storage slot)`
for state reads, or explicitly declare that a cell is only discoverable by the
bounded sequential closure. The canonical evidence phase must then freeze the
resulting footprint, reacquire all proofs from scratch, and run once without
expansion.

Until that contract exists, all four canonical cases remain
`INCONCLUSIVE(context-incomplete)` and M1 must not claim real-context
acceptance.
