from eval.e4_stage2_execute import _run_status


def test_run_status_does_not_call_rpc_failures_complete():
    assert _run_status([{"system_status": "INCONCLUSIVE"}]) == "partial"
    assert _run_status([
        {"system_status": "OBSERVED"}, {"system_status": "OBSERVED"}
    ]) == "complete"
