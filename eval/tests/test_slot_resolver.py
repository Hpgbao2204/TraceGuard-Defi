import pytest
from eval.e4.erc20_slot_resolver import resolve_balance_slot
def test_slot_resolver_fails_closed_without_proof():
    with pytest.raises(ValueError,match='SLOT_UNRESOLVED'):
        resolve_balance_slot('0x'+'1'*40,{},[],['0x'+'2'*40,'0x'+'3'*40])
