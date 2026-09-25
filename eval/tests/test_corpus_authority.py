import pytest
from eval.corpus_authority import assert_frozen20, frozen_case_ids
def test_frozen20_accepts_exact_set():
    assert assert_frozen20(frozen_case_ids(),'frozen-20')['corpus_id']=='m4-frozen-20'
def test_frozen20_rejects_extra_case():
    with pytest.raises(ValueError): assert_frozen20(frozen_case_ids()+['extra'],'frozen-20')
