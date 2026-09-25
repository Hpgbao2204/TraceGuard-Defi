from eval.e4.harm_compare import compare
def h(x): return {'resolver_version':'t0-v2','boundary_id':'b','tier':'T0','hard_asset_registry':'v1','hard':x}
def test_compare_cause(): assert compare(h({('v','a'):-10}),h({}),('v','a'))['verdict']=='CAUSE'
def test_compare_not_necessary(): assert compare(h({('v','a'):-10}),h({('v','a'):-8}),('v','a'))['verdict']=='NOT_NECESSARY'
def test_compare_mismatch():
    x=h({}); y=h({}); y['boundary_id']='x'
    assert compare(x,y)['verdict']=='INCONCLUSIVE_OBSERVATION'
