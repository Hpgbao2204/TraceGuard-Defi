"""Reproducible positive metadata enricher with bounded retry and atomic output."""
from __future__ import annotations
import argparse, hashlib, json, os, tempfile, time, urllib.error, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
URL_ENV = {'ethereum':'ARCHIVE_RPC','bsc':'QUICKNODE_BNB','arbitrum':'ARB_ARCHIVE_RPC','optimism':'QUICKNODE_OPT','base':'BASE_ARCHIVE_RPC'}
def rpc(url, method, params):
    body = json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode()
    req = urllib.request.Request(url, data=body, headers={'content-type':'application/json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read())
    if data.get('error'):
        raise RuntimeError(str(data['error'])[:240])
    return data.get('result')
def fetch(url, method, params, attempts=3):
    last = None
    for attempt in range(attempts):
        try:
            return rpc(url, method, params)
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                retry_after = getattr(exc, 'headers', {}).get('Retry-After') if isinstance(exc, urllib.error.HTTPError) else None
                delay = min(30, float(retry_after)) if retry_after and retry_after.isdigit() else min(30, 2 ** attempt)
                time.sleep(delay)
    raise last
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--only-tx', action='append'); ap.add_argument('--only-incident', action='append'); args = ap.parse_args()
    for line in (ROOT/'.env').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1); os.environ.setdefault(key, value.strip("'\""))
    reg_path = ROOT/'corpus/vnext/positive_registry_effective.jsonl'
    registry = [json.loads(line) for line in reg_path.read_text().splitlines() if line.strip()]
    wanted_tx = {x.lower() for x in (args.only_tx or [])}; wanted_inc = set(args.only_incident or [])
    existing_path = ROOT/'eval/vnext/positives/positive_metadata_v1.jsonl'
    existing = {}
    if existing_path.exists():
        existing = {x.get('incident_id'): x for x in (json.loads(line) for line in existing_path.read_text().splitlines() if line.strip()) if x.get('incident_id')}
    target_registry = registry
    if wanted_tx or wanted_inc:
        target_registry = [x for x in registry if (x.get('tx_hashes') or [None])[0].lower() in wanted_tx or x.get('incident_id') in wanted_inc]
    out_rows, rejects = [], []
    for item in target_registry:
        h = (item.get('tx_hashes') or [None])[0]; chain = item.get('chain'); url = os.environ.get(URL_ENV.get(chain, ''))
        try:
            if not h or not url: raise RuntimeError('RPC_NOT_CONFIGURED_OR_HASH_MISSING')
            tx = fetch(url, 'eth_getTransactionByHash', [h]); receipt = fetch(url, 'eth_getTransactionReceipt', [h])
            if not tx or not receipt: raise RuntimeError('TX_OR_RECEIPT_NOT_FOUND')
            block = int(tx['blockNumber'], 16); block_obj = fetch(url, 'eth_getBlockByNumber', [hex(block), False])
            if not block_obj or tx.get('blockHash') != block_obj.get('hash') or receipt.get('blockHash') != tx.get('blockHash'):
                raise RuntimeError('BLOCK_HASH_MISMATCH')
            if receipt.get('status') not in ('0x1', 1): raise RuntimeError('RECEIPT_NOT_SUCCESS')
            inp = tx.get('input') or '0x'; to = tx.get('to')
            out_rows.append({**item, 'block_number': block, 'block_hash': tx.get('blockHash'), 'tx_index': int(tx['transactionIndex'],16), 'timestamp': int(block_obj['timestamp'],16), 'receipt_status': receipt.get('status'), 'to': to, 'top_level_selector': inp[:10], 'metadata_provenance': 'onchain_rpc_crosscheck_v1'})
        except Exception as exc:
            rejects.append({'incident_id':item.get('incident_id'), 'tx_hash':h, 'chain':chain, 'error_class':str(exc)[:160], 'retryable': '429' in str(exc) or '5' in str(exc), 'attempts':3})
    if wanted_tx or wanted_inc:
        for item in registry:
            if item.get('incident_id') not in {x.get('incident_id') for x in target_registry} and item.get('incident_id') in existing:
                out_rows.append(existing[item['incident_id']])
    out_rows.sort(key=lambda x: x.get('incident_id',''))
    d = ROOT/'eval/vnext/positives'; d.mkdir(parents=True, exist_ok=True); path = d/'positive_metadata_v1.jsonl'; fd,tmp = tempfile.mkstemp(dir=d, prefix='.positive_metadata_', text=True); os.close(fd)
    Path(tmp).write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out_rows)); Path(tmp).replace(path)
    (d/'positive_metadata_rejections_v1.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rejects))
    manifest={'schema_version':1,'status':'READY' if len(out_rows)==len(registry) and not rejects else 'INCOMPLETE','requested':len(registry),'processed':len(target_registry),'materialized':len(out_rows),'rejected':len(rejects),'source_registry_sha256':hashlib.sha256(reg_path.read_bytes()).hexdigest(),'metadata_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (d/'positive_metadata_manifest_v1.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n'); print(json.dumps(manifest,indent=2,sort_keys=True))
if __name__ == '__main__': main()
