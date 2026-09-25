from eval.m6_harm_v2 import t0, t1
from eval.m6_t1_detection import detect_t1

def test_t0_detects_eth_debit_without_usd():
    victim='0x'+'1'*40; attacker='0x'+'2'*40
    r=t0([{'token':'eth','from':victim,'to':attacker,'amount_raw':'10'}], attacker)
    assert r.status=='HARM' and r.hard_deltas['eth']==-10

def test_t0_complete_empty_flow_is_unknown():
    r=t0([], '0x'+'2'*40, complete=True)
    assert r.status=='UNKNOWN'
    assert r.reason_code=='T0_NO_OBSERVABLE_HARD_ASSET_FLOW'

def test_incomplete_flow_is_unknown():
    r=t0([], '0x'+'2'*40, complete=False)
    assert r.status=='UNKNOWN' and r.reason_code=='RAW_OBSERVATION_INCOMPLETE'

def test_t1_uses_explicit_boundary_and_ignores_exotic_primary():
    victim='0x'+'1'*40; attacker='0x'+'2'*40
    r=t1([{'token':'exotic','from':victim,'to':attacker,'amount_raw':'99'}, {'token':'wbtc','from':victim,'to':attacker,'amount_raw':'1'}], [victim], [attacker])
    assert r.status=='HARM' and r.hard_deltas['wbtc']==-1 and r.exotic_deltas['exotic']==-99

def test_t1_uses_same_raw_engine_without_usd():
    victim='0x'+'3'*40; attacker='0x'+'4'*40
    r=t1([{'token':'wbtc','from':victim,'to':attacker,'amount_raw':'3'}], [victim])
    assert r.status=='HARM' and r.hard_deltas['wbtc']==-3 and r.tier=='T1'

def test_legacy_t1_entrypoint_delegates_to_harm_v2():
    victim='0x'+'5'*40; attacker='0x'+'6'*40
    r=detect_t1(
        [{'token':'eth','from':victim,'to':attacker,'amount_raw':'2'}],
        {'boundary_id':'test-boundary','protected_entities':[victim]},
    )
    assert r['status']=='HARM' and r['detection_spec_id'].startswith('harm-spec-v2|')
