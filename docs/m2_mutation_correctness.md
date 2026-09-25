# M2 Mutation Correctness

Status: implementation-frozen  
Implementation source checkpoint: `4058412`

This checkpoint includes the frozen forwarding, historical token-orientation,
and Uniswap-V2 flash-swap selector fixes. Documentation updates may land in
later commits; they do not change the implementation source binding.

M2 freezes the mutation contract, not a causal result. Release-eligible
operators are limited to `f_fl` and external-feed `f_orc`. Experimental
operators remain available for diagnostics but are forced to
`INCONCLUSIVE` by the policy adapter and cannot enter the causal numerator.

The execution row carries three separate gates:

1. `mutation_application_verified`: the requested mutation was observed by
   read-back evidence.
2. `mutation_contract_verified`: the declared semantic postcondition held.
3. `execution_preserving`: the mutated branch completed successfully.

`semantic_valid` is retained only as a diagnostic compatibility alias;
policy decisions use `mutation_contract_verified`.

For `f_fl`, the declared provider and selector must be observed and blocked;
a revert remains non-comparable evidence. For `f_orc`, the intervention is
selector-scoped and uses exact historical return bytes verified at `b-1`.
Shadow accounts are proof-bound absent and target-time code is copied only
after prefix replay.

No causal evaluation or protected-harm claim is made by this milestone.
Those require the M3 harm contract and later validated evidence.

Manifest: [`m2_mutation_correctness_manifest.json`](m2_mutation_correctness_manifest.json)
