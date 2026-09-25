from eval.m6_dependency_executor import classify, validate_plan
from eval.m6_dependency_adapters import adapter_for


def test_missing_gate_is_inconclusive():
    result = classify({})
    assert result["status"] == "INCONCLUSIVE"


def test_confirmed_requires_real_boundary_and_sham():
    evidence = {key: True for key in (
        "baseline_fidelity", "provider_frame", "callback_boundary",
        "real_intervention_application", "expected_blocking_site",
        "sham_executable", "provenance")}
    evidence.update(real_reverted=True, blocking_boundary_observed=True)
    assert classify(evidence)["status"] == "DEPENDENCY_CONFIRMED"


def test_executable_path_is_not_confirmed():
    evidence = {key: True for key in (
        "baseline_fidelity", "provider_frame", "callback_boundary",
        "real_intervention_application", "expected_blocking_site",
        "sham_executable", "provenance")}
    evidence.update(real_executed=True, blocking_boundary_observed=False)
    assert classify(evidence)["status"] == "DEPENDENCY_NOT_CONFIRMED"


def test_plan_only_authorizes_four_ready_cases():
    matrix = {"cases": [
        {"case_id": str(i), "semantic_support": "D2_READY",
         "replay_authorized": True, "provider_address": "0x1",
         "exact_selector": "0x2", "callback_selector": "0x3",
         "expected_boundary": "b", "intervention_contract": "i",
         "sham_control": "s", "sham_expected_behavior": "e"}
        for i in range(4)
    ]}
    assert validate_plan(matrix)["replay_authorized"] is True


def test_provider_frame_requires_callback_edge():
    adapter = adapter_for("Balancer Vault")
    calls = [
        {"to": adapter.address, "selector": adapter.selector},
        {"from": adapter.address, "selector": adapter.callback_selector},
    ]
    assert adapter.validate_frame(calls)


def test_provider_execution_is_fail_closed_until_real_seam_exists():
    adapter = adapter_for("Aave V3")
    try:
        adapter.execute()
    except NotImplementedError:
        pass
    else:
        raise AssertionError("unimplemented provider adapter must fail closed")
