"""Immutable corpus identity checks for new fixed-20 artifacts."""
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MAN=ROOT/'docs/m4_frozen_case_manifest.json'
def frozen_case_ids(): return sorted(x['case_id'] for x in json.loads(MAN.read_text())['cases'])
def case_ids_sha256(ids): return hashlib.sha256(('\n'.join(sorted(ids))+'\n').encode()).hexdigest()
def corpus_metadata():
    ids=frozen_case_ids()
    return {'corpus_id':'m4-frozen-20','corpus_sha256':json.loads(MAN.read_text())['case_set_sha256'],'case_ids_sha256':case_ids_sha256(ids)}
def assert_frozen20(case_ids, artifact_scope):
    if 'frozen-20' not in artifact_scope: return corpus_metadata()
    expected=set(frozen_case_ids()); actual=set(case_ids)
    if actual!=expected: raise ValueError(f'FROZEN20_CORPUS_MISMATCH missing={sorted(expected-actual)} extra={sorted(actual-expected)}')
    return corpus_metadata()
