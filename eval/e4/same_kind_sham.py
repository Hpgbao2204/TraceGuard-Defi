"""Validation contract for same-kind AMM/oracle sham evidence."""
def validate(baseline, sham, *, seam_fields=('call_type','caller','callee','selector','depth')):
    for field in seam_fields:
        if baseline.get(field)!=sham.get(field):
            return {'pass':False,'reason_code':'SHAM_SEAM_MISMATCH','field':field}
    if baseline.get('match_count')!=1 or sham.get('match_count')!=1:
        return {'pass':False,'reason_code':'SHAM_MATCH_COUNT_INVALID'}
    if sham.get('execution_preserved') is not True:
        return {'pass':False,'reason_code':'SHAM_EXECUTION_NOT_PRESERVED'}
    if sham.get('harm_vector')!=baseline.get('harm_vector'):
        return {'pass':False,'reason_code':'SHAM_HARM_NOT_PRESERVED'}
    return {'pass':True,'reason_code':'SAME_KIND_SHAM_PASS'}
