# E5 Claim Schema v2

`eval/results/e5_rcfh/claim_schema_v2.json` is the normalized claim layer for
the frozen-20 E5 audit.

The schema deliberately separates:

- `root_mechanism`: Reviewer-C's adjudicated ontology label and exact decision
  statement;
- `enabling_factors`: the older `f_*` labels, retained as hypotheses or
  execution enablers rather than treated as root-cause truth;
- `vulnerable_boundary`: the adjudicated security objective and causal-call
  description;
- `protected_target` and `harm_definition`: the frozen harm evidence supplied
  by the adjudication record;
- `causal_variable`, `dependency_path`, and
  `expected_counterfactual_effect`: intentionally `null` until a case-specific
  boundary review freezes them.

This artifact is normalization, not causal evidence. It does not select a seam,
run a mutation, or convert reported incident loss into a HarmVector. A case may
only proceed to replay after its claim is mapped to an operation/state boundary
and its dependency path and protected harm observation are explicitly frozen.
