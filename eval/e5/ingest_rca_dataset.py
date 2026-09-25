"""Ingest the public RCA CSV as reported-loss labels, not measured harm."""
from __future__ import annotations
import csv, hashlib, io, json, re, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ZIP_PATH = Path('/tmp/defi_security_breach_rca.zip')
MANIFEST = ROOT / 'docs/m4_frozen_case_manifest.json'
OUT = ROOT / 'eval/results/e5_rcfh/rca_dataset_reported_loss.json'

def norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', s.lower())

def main() -> None:
    if not ZIP_PATH.exists():
        raise SystemExit('RCA dataset zip missing: /tmp/defi_security_breach_rca.zip')
    with zipfile.ZipFile(ZIP_PATH) as z:
        csv_name = next(n for n in z.namelist() if n.endswith('_all.csv'))
        raw = z.read(csv_name)
    text = raw.decode('utf-8-sig')
    records = list(csv.DictReader(io.StringIO(text)))
    manifest = json.loads(MANIFEST.read_text())
    matches = []
    for case in manifest['cases']:
        cid = case['case_id']
        tx = case.get('tx_hash','').lower()
        title = cid.removeprefix('defihacklabs-').rsplit('-', 3)[0]
        hits = []
        for row in records:
            poc = (row.get('POC') or '').lower()
            if tx and tx in poc:
                hits.append(('EXACT_TX_HASH', row))
            elif norm(title) and norm(title) in norm(row.get('Title') or ''):
                hits.append(('TITLE_CANDIDATE', row))
        # Prefer exact tx match; only retain a unique title candidate.
        exact = [r for c,r in hits if c == 'EXACT_TX_HASH']
        chosen = exact[0] if len(exact) == 1 else (hits[0][1] if not exact and len(hits) == 1 else None)
        confidence = 'EXACT_TX_HASH' if len(exact) == 1 else ('TITLE_CANDIDATE' if chosen else 'MISSING')
        matches.append({
            'case_id': cid, 'tx_hash': case.get('tx_hash'),
            'match_confidence': confidence,
            'reported_loss': chosen.get('Lost') if chosen else None,
            'reported_root_cause': chosen.get('Root cause') if chosen else None,
            'reported_type': chosen.get('Type') if chosen else None,
            'source_title': chosen.get('Title') if chosen else None,
            'source_poc': chosen.get('POC') if chosen else None,
        })
    result = {
        'schema_version': 1, 'artifact': 'e5-rca-dataset-reported-loss',
        'corpus_id': 'm4-frozen-20',
        'source': 'https://github.com/SunWeb3Sec/DeFi-Security-Breach-RCA',
        'source_dataset_file': csv_name,
        'source_zip_sha256': hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest(),
        'source_csv_sha256': hashlib.sha256(raw).hexdigest(),
        'source_record_count': len(records),
        'matches': matches,
        'semantics': 'reported incident loss only; not proof-bound measured harm or HarmVector',
        'reported_loss_matches': sum(x['reported_loss'] is not None for x in matches),
        'exact_tx_matches': sum(x['match_confidence'] == 'EXACT_TX_HASH' for x in matches),
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: result[k] for k in ('source_record_count','reported_loss_matches','exact_tx_matches','source_zip_sha256')}, indent=2))

if __name__ == '__main__': main()
