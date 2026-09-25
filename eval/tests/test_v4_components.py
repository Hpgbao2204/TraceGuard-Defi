from eval.attacker_set_v2 import derive
from eval.native_ledger_v1 import committed_native_delta
from eval.e4.harm_vector import from_flows
def test_attacker_calls_do_not_capture_victim_or_factory_child():
    s='0x'+'1'*40; victim='0x'+'2'*40; helper='0x'+'3'*40; child='0x'+'4'*40
    trace=[{'event':'enter','type':'CALL','from':s,'to':victim}, {'event':'enter','type':'CREATE','from':victim,'to':child}, {'event':'enter','type':'CREATE','from':s,'to':helper}]
    att,created=derive(trace,s)
    assert victim not in att and child not in att and helper in att
def test_committed_native_delta_uses_poststate_pair():
    a='0x'+'1'*40
    pre={'prestate':{a:{'balance':'0x64'}},'poststate':{a:{'balance':'0x32'}}}
    assert committed_native_delta({},pre)[a]==-50

def test_harm_vector_resolves_erc20_addresses_from_registry():
    attacker='0x'+'1'*40; protected='0x'+'2'*40
    v=from_flows([{'token':'0x2260fac5e5542a773aa44fbcfedf7c193bc2c599','from':protected,'to':attacker,'amount_raw':7}], {attacker}, {protected})
    assert v.hard[(protected,'0x2260fac5e5542a773aa44fbcfedf7c193bc2c599')]==-7
    assert not v.exotic
