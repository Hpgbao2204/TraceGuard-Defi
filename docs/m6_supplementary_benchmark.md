# Supplementary operator-positive benchmark

This is a separate selection audit, not a replacement for the frozen M6
fixed-20 set. Inclusion is frozen before causal replay and cannot depend on a
mutation result. A case must have adjudicated ground truth in the release
scope (`f_fl` or external-feed `f_orc`), measurable protected harm, and valid
proof-bound historical context.

The current audit is offline and produced no eligible case from fixed-20.
`f_orc_amm` cases are explicitly out of scope. No supplementary causal run is
claimed until a new candidate corpus is selected, reviewed, and frozen.

An offline inventory found six candidate leads in the broader Ethereum corpus;
they are recorded in `eval/results/m6_supplementary_candidate_leads.json`.
These are not benchmark cases: each still requires independent adjudication,
harm measurability, and proof-bound context before a separate freeze.

A stricter offline discovery audit found no additional on-chain Ethereum leads
outside fixed-20 and the prior six with source inventory factors overlapping
the release scope. The negative result is recorded in
`eval/results/m6_supplementary_discovery_audit.json`; no new factor label was
assigned and no replay was run.

The enriched Reviewer-C v2 sidecar is harm-measurable for all six leads, but
operator compatibility remains zero. The round is therefore useful as an
execution-dependency/negative control set, not as a causal-efficacy benchmark.

## Execution-priority policy for the 20-case supplementary queue

The broader flash-loan candidate queue is classified by mechanism family for
coverage, but family labels do not predict causal-replay difficulty. Structural
coupling within the target transaction is the primary screening criterion.

Priority is therefore:

1. access-control and input-validation cases;
2. simple single-callback reentrancy cases;
3. case-specific business-logic cases;
4. accounting/share-price cases and AMM/reserve-oracle cases as high-risk
   case studies unless a seam is independently shown to be executable.

Flash loans are treated as an enabling-capital intervention candidate, not as
the presumed root cause. A causal result must still use a proof-bound baseline,
an independently frozen protected-harm specification, and an intervention that
changes only the declared mechanism under the declared capital policy.
