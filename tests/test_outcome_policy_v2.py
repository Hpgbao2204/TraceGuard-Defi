from __future__ import annotations

import unittest

from core.domain.policy import (
    CausalEvidence,
    ExecutionState,
    HarmState,
    OutcomePolicy,
    Verdict,
)
from eval.e4.policy_v2 import apply_policy_rows, decide_row


class OutcomePolicyV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = OutcomePolicy()
        self.common = dict(
            baseline_execution=ExecutionState.EXECUTED,
            baseline_harm=HarmState.HARMFUL,
            fidelity_pass=True,
            controls_pass=True,
            intervention_valid=True,
            harm_comparable=True,
        )

    def test_executed_valid_harm_removed_is_cause(self) -> None:
        decision = self.policy.decide(
            **self.common,
            mutation_execution=ExecutionState.EXECUTED,
            mutation_harm=HarmState.AT_OR_BELOW_THRESHOLD,
        )
        self.assertEqual(decision.verdict, Verdict.CAUSE)
        self.assertEqual(decision.causal_evidence, CausalEvidence.TRUE)

    def test_revert_never_has_causal_evidence(self) -> None:
        decision = self.policy.decide(
            **self.common,
            mutation_execution=ExecutionState.REVERTED,
            mutation_harm=HarmState.AT_OR_BELOW_THRESHOLD,
            defense_blocked=True,
        )
        self.assertEqual(decision.verdict, Verdict.INCONCLUSIVE)
        self.assertEqual(decision.causal_evidence, CausalEvidence.FALSE)
        self.assertTrue(decision.defense_blocked)

    def test_unknown_harm_is_not_zero(self) -> None:
        decision = self.policy.decide(
            **self.common,
            mutation_execution=ExecutionState.EXECUTED,
            mutation_harm=HarmState.UNKNOWN,
        )
        self.assertEqual(decision.verdict, Verdict.INCONCLUSIVE)
        self.assertEqual(decision.reason_code, "mutation-harm-unknown")

    def test_valid_execution_with_harm_remaining_is_no_effect(self) -> None:
        decision = self.policy.decide(
            **self.common,
            mutation_execution=ExecutionState.EXECUTED,
            mutation_harm=HarmState.HARMFUL,
        )
        self.assertEqual(decision.verdict, Verdict.NO_EFFECT)
        self.assertEqual(decision.causal_evidence, CausalEvidence.FALSE)

    def test_non_comparable_harm_specification_is_inconclusive(self) -> None:
        decision = self.policy.decide(
            **{**self.common, "harm_comparable": False},
            mutation_execution=ExecutionState.EXECUTED,
            mutation_harm=HarmState.AT_OR_BELOW_THRESHOLD,
        )
        self.assertEqual(decision.verdict, Verdict.INCONCLUSIVE)
        self.assertEqual(decision.reason_code, "harm-specification-not-comparable")

    def test_success_does_not_make_intervention_valid(self) -> None:
        evidence = {**self.common, "intervention_valid": False}
        decision = self.policy.decide(
            **evidence,
            mutation_execution=ExecutionState.EXECUTED,
            mutation_harm=HarmState.AT_OR_BELOW_THRESHOLD,
        )
        self.assertEqual(decision.verdict, Verdict.INCONCLUSIVE)
        self.assertEqual(decision.reason_code, "intervention-invalid")

    def test_row_adapter_does_not_alias_execution_success_to_validity(self) -> None:
        decision = decide_row(
            {
                "baseline_outcome": "EXECUTED",
                "mutation_outcome": "EXECUTED",
                "baseline_harm": "HARM",
                "mutated_harm": "NO_HARM",
                "fidelity_pass": True,
                "controls_pass": True,
                "execution_preserving": True,
                "harm_comparable": True,
            }
        )
        self.assertEqual(decision.verdict, Verdict.INCONCLUSIVE)
        self.assertEqual(decision.reason_code, "intervention-invalid")

    def test_row_policy_requires_controls_and_protected_harm(self) -> None:
        rows = apply_policy_rows([
            {"mutation": "fidelity", "outcome": "EXECUTED_HARM",
             "fidelity_pass": True, "harm_S": "HARM",
             "harm_source": "attacker_value_delta"},
            {"mutation": "f_orc", "outcome": "EXECUTED_NO_HARM",
             "harm_Sm": "NO_HARM", "intervention_valid": True,
             "verdict": "NOT_NECESSARY"},
        ])
        self.assertEqual(rows[1]["verdict"], "INCONCLUSIVE")
        self.assertFalse(rows[1]["causal_evidence"])
        self.assertEqual(rows[1]["policy_reason"], "baseline-harm-not-established")

    def test_row_policy_requires_canonical_mutation_contract_field(self) -> None:
        evidence = [
            {"mutation": "fidelity", "outcome": "EXECUTED_HARM",
             "fidelity_pass": True, "harm_S": "HARM",
             "harm_source": "pool_balance_delta", "harm_spec_id": "spec-a"},
            {"mutation": "f_orc", "outcome": "EXECUTED_NO_HARM",
             "harm_Sm": "NO_HARM", "harm_source_mutated": "pool_balance_delta",
             "harm_spec_id": "spec-a", "intervention_valid": True,
             "mutation_application_verified": True,
             "semantic_valid": True},
            {"mutation": "control_positive", "control_type": "positive",
             "control_pass": True, "harm_source": "pool_balance_delta",
             "harm_spec_id": "spec-a"},
            {"mutation": "control_sham", "control_type": "sham",
             "control_pass": True, "harm_source_mutated": "pool_balance_delta",
             "harm_spec_id": "spec-a"},
        ]
        decided = apply_policy_rows(evidence)[1]
        self.assertEqual(decided["verdict"], "INCONCLUSIVE")
        self.assertEqual(decided["policy_reason"], "intervention-invalid")

    def test_out_of_scope_operator_cannot_produce_causal_evidence(self) -> None:
        decided = apply_policy_rows([
            {"mutation": "fidelity", "outcome": "EXECUTED_HARM",
             "fidelity_pass": True, "harm_S": "HARM",
             "harm_source": "pool_balance_delta", "harm_spec_id": "spec-a"},
            {"mutation": "f_swap:0xdead", "candidate_factor": "f_swap",
             "outcome": "EXECUTED_NO_HARM", "harm_Sm": "NO_HARM",
             "harm_source_mutated": "pool_balance_delta", "harm_spec_id": "spec-a",
             "intervention_valid": True,
             "mutation_application_verified": True,
             "mutation_contract_verified": True},
        ])[1]
        self.assertEqual(decided["verdict"], "INCONCLUSIVE")
        self.assertFalse(decided["causal_evidence"])
        self.assertEqual(decided["policy_reason"], "operator-out-of-scope")

    def test_row_policy_rejects_attacker_value_on_mutation_branch(self) -> None:
        rows = apply_policy_rows([
            {"mutation": "fidelity", "outcome": "EXECUTED_HARM",
             "fidelity_pass": True, "harm_S": "HARM",
             "harm_source": "pool_balance_delta"},
            {"mutation": "f_orc", "outcome": "EXECUTED_NO_HARM",
             "harm_Sm": "NO_HARM", "harm_source_mutated": "attacker_value_delta",
             "intervention_valid": True},
            {"mutation": "control_sham", "control_type": "sham",
             "control_pass": True},
        ])
        self.assertEqual(rows[1]["verdict"], "INCONCLUSIVE")
        self.assertFalse(rows[1]["causal_evidence"])

    def test_row_policy_clears_legacy_cause_flag(self) -> None:
        rows = apply_policy_rows([
            {"mutation": "fidelity", "outcome": "EXECUTED_HARM",
             "fidelity_pass": True, "harm_S": "HARM",
             "harm_source": "pool_balance_delta"},
            {"mutation": "f_orc", "outcome": "REVERTED", "harm_Sm": "UNKNOWN",
             "intervention_valid": False, "verdict": "CAUSE", "cause": "1"},
        ])
        self.assertEqual(rows[1]["verdict"], "INCONCLUSIVE")
        self.assertEqual(rows[1]["cause"], "")

    def test_row_policy_requires_same_harm_specification_id(self) -> None:
        rows = apply_policy_rows([
            {"mutation": "fidelity", "outcome": "EXECUTED_HARM",
             "fidelity_pass": True, "harm_S": "HARM",
             "harm_source": "pool_balance_delta", "harm_spec_id": "spec-a"},
            {"mutation": "f_orc", "outcome": "EXECUTED_NO_HARM",
             "harm_Sm": "NO_HARM", "harm_source_mutated": "pool_balance_delta",
             "harm_spec_id": "spec-b", "intervention_valid": True},
            {"mutation": "control_sham", "control_type": "sham",
             "control_pass": True},
        ])
        self.assertEqual(rows[1]["verdict"], "INCONCLUSIVE")
        self.assertEqual(rows[1]["policy_reason"], "harm-specification-not-comparable")

    def test_row_policy_whitelists_protected_harm_sources(self) -> None:
        rows = apply_policy_rows([
            {"mutation": "fidelity", "outcome": "EXECUTED_HARM",
             "fidelity_pass": True, "harm_S": "HARM",
             "harm_source": "disclosed_incident_loss", "harm_spec_id": "spec-a"},
            {"mutation": "f_orc", "outcome": "EXECUTED_NO_HARM",
             "harm_Sm": "NO_HARM", "harm_source_mutated": "receipt_transfer_ledger",
             "harm_spec_id": "spec-a", "intervention_valid": True,
             "mutation_application_verified": True,
             "mutation_contract_verified": True},
            {"mutation": "control_sham", "control_type": "sham",
             "control_pass": True},
        ])
        self.assertEqual(rows[1]["verdict"], "INCONCLUSIVE")
        self.assertFalse(rows[1]["causal_evidence"])
        self.assertEqual(rows[1]["policy_reason"], "baseline-harm-not-established")

    def test_control_rows_never_become_causal_verdict(self) -> None:
        rows = apply_policy_rows([
            {"mutation": "fidelity", "outcome": "EXECUTED", "fidelity_pass": True,
             "harm_S": "HARM", "harm_source": "pool_balance_delta",
             "harm_spec_id": "spec-a"},
            {"mutation": "sham", "control_type": "sham", "control_pass": True,
             "outcome": "EXECUTED", "harm_Sm": "NO_HARM",
             "harm_source_mutated": "pool_balance_delta", "harm_spec_id": "spec-a",
             "intervention_valid": True, "mutation_application_verified": True,
             "mutation_contract_verified": True},
        ])
        self.assertEqual(rows[1]["verdict"], "CONTROL_PASS")
        self.assertFalse(rows[1]["causal_evidence"])

    def test_controls_require_equivalent_protected_harm_structure(self) -> None:
        rows = apply_policy_rows([
            {"mutation": "fidelity", "outcome": "EXECUTED", "fidelity_pass": True,
             "harm_S": "HARM", "harm_source": "pool_balance_delta",
             "harm_spec_id": "spec-a", "control_type": "positive", "control_pass": True},
            {"mutation": "control_sham", "control_type": "sham", "control_pass": True,
             "harm_Sm": "NO_HARM", "harm_source_mutated": "receipt_transfer_ledger",
             "harm_spec_id": "spec-b"},
            {"mutation": "f_orc", "outcome": "EXECUTED", "harm_Sm": "NO_HARM",
             "harm_source_mutated": "pool_balance_delta", "harm_spec_id": "spec-a",
             "intervention_valid": True, "mutation_application_verified": True,
             "mutation_contract_verified": True},
        ])
        self.assertFalse(rows[2]["controls_pass"])
        self.assertEqual(rows[2]["verdict"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
