from eval.m6_t1_detection import detect_t1

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
A = "0x" + "1" * 40
B = "0x" + "2" * 40

def boundary(status="ADJUDICATED"):
    return {"status": status, "protocol_id": "p", "protected_entities": [A],
            "hard_assets": [WETH], "boundary_id": "b"}

def test_pending_boundary_fails_closed():
    assert detect_t1([], boundary("PENDING_ADJUDICATION"))["status"] == "UNKNOWN"

def test_adjudicated_boundary_detects_harm():
    flows = [{"token": WETH, "from": A, "to": B, "amount_raw": 5}]
    assert detect_t1(flows, boundary())["status"] == "HARM"
