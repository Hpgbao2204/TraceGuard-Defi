from eval.e5.harm_sink_binding import bind


def test_harm_binding_is_unique_and_noncausal():
    run={"provenance": {
        "frame_meta": {"f": {"address": "0xabc"}},
        "values": [{"value_id":"v","value":"0xddf252ad"}],
        "observations": [{"observation_id":"o1","kind":"event_log","frame_id":"f","trace_index":3,"values":["v"]}],
    }}
    out=bind(run,{"kind":"event_log","frame_address":"0xABC","call_trace_index":3,"value":"0xDDF252AD"})
    assert out["status"] == "HARM_NODE_BOUND"
    assert out["bound_observation"]["observation_id"] == "o1"
    assert out["causal_verdict"] is None


def test_harm_binding_fails_closed_on_ambiguity():
    run={"provenance": {"observations":[
        {"observation_id":"a","kind":"event_log","frame_id":"f"},
        {"observation_id":"b","kind":"event_log","frame_id":"f"},
    ]}}
    assert bind(run,{"kind":"event_log"})["status"] == "AMBIGUOUS_HARM_NODE"
