from eval.e4.same_kind_sham import validate
def test_same_kind_sham_passes():
    x={'call_type':'STATICCALL','caller':'a','callee':'b','selector':'0x1','depth':2,'match_count':1,'execution_preserved':True,'harm_vector':{'x':-1}}
    assert validate(x,dict(x))['pass'] is True
def test_sham_different_seam_fails():
    x={'call_type':'CALL','caller':'a','callee':'b','selector':'0x1','depth':2,'match_count':1,'execution_preserved':True,'harm_vector':{}}
    y=dict(x); y['selector']='0x2'
    assert validate(x,y)['reason_code']=='SHAM_SEAM_MISMATCH'
