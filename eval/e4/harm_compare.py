"""Differential comparison of raw harm vectors; no USD required."""
def _neg(h): return {k for k,v in h.items() if int(v)<0}
def compare(H, H_prime, target=None, threshold=0):
    required=('resolver_version','boundary_id','tier','hard_asset_registry')
    for k in required:
        if H.get(k)!=H_prime.get(k): return {'verdict':'INCONCLUSIVE_OBSERVATION','reason_code':'COMPARABILITY_MISMATCH','field':k}
    a,b=_neg(H.get('hard',{})),_neg(H_prime.get('hard',{}))
    if target is not None and target in a-b: return {'verdict':'CAUSE','removed_target':target,'removed':sorted(a-b)}
    if target is not None and target in b:
        old=abs(int(H.get('hard',{}).get(target,0))); new=abs(int(H_prime.get('hard',{}).get(target,0)))
        if new >= old*threshold: return {'verdict':'NOT_NECESSARY','retained_target':target}
    if a==b: return {'verdict':'NOT_NECESSARY','reason_code':'NEGATIVE_SET_UNCHANGED'}
    return {'verdict':'INCONCLUSIVE_OBSERVATION','reason_code':'TARGET_NOT_RESOLVED'}
