from eval.counterfactual_outcome import attack_verdict, topology_gate, vector_difference


def test_topology_gate_allows_boundary_blocking_without_exact_topology():
    assert topology_gate({
        "intervention_seam_match": True,
        "same_kind_sham_pass": True,
        "unexpected_early_divergence": False,
        "blocking_point_reached": True,
        "sink_committed": False,
    }) == "BLOCKING_COMPARABLE"


def test_extraction_is_asset_vector_not_cross_asset_scalar():
    assert vector_difference({"WETH": 4, "USDC": 100}, {"WETH": 0, "USDC": 50}) == {"USDC": -50, "WETH": -4}


def test_downstream_predicate_removed_is_attack_outcome_removed():
    factual = {"downstream_predicates": {"transfer": True}, "extraction_vector": {"QUEST": 1}}
    cf = {"topology_gate": "BLOCKING_COMPARABLE", "downstream_predicates": {"transfer": False}, "extraction_vector": {"QUEST": 0}}
    assert attack_verdict(factual, cf) == "ATTACK_OUTCOME_REMOVED"
