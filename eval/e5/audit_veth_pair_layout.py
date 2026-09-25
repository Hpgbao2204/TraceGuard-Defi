#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PRE=ROOT/'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/prestates.json'
OUT=ROOT/'eval/results/e5_rcfh/veth_buyquote_dose_probe/pair_storage_layout_audit.json'
def main():
    layout={
      '0x0-0x4':'inherited ERC20 metadata/mappings (exact packing fork-dependent)',
      '0x5':'factory address', '0x6':'token0 address', '0x7':'token1 address',
      '0x8':'packed reserve0/reserve1/blockTimestampLast',
      '0x9':'price0CumulativeLast', '0xa':'price1CumulativeLast',
      '0xb':'kLast', '0xc':'unlocked/reentrancy guard'
    }
    x=json.loads(PRE.read_text())[57]['trace']['0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d']
    code=x['code'].lower(); selectors={s:[i//2 for i in range(len(code)-8) if code[i:i+8]==s] for s in ['022c0d9f','6a627842','0902f1ac','fff6cae9']}
    out={'status':'PAIR_LAYOUT_CLASSIFIED_STORAGE_PATCH_SCOPE_NOT_AUTHORIZED','case_id':'defihacklabs-veth-2024-11-14','known_uniswap_v2_layout':layout,'runtime_selector_inventory':selectors,'candidate_reverse_swap_state':['0x8','balanceOf(pair) for token0/token1 during swap'], 'excluded_from_reserve_only_patch':['0x9','0xa','0xb','0xc','LP totalSupply/balanceOf/allowance mappings'], 'caveat':'The slot mapping is a standard UniswapV2Pair layout cross-check, not proof that pair.mint alone writes each slot in this transaction. The pair runtime is a fork/custom deployment; frame-scoped SSTORE attribution is still required before authorizing a storage patch.', 'source_sha256':hashlib.sha256(PRE.read_bytes()).hexdigest()}
    OUT.write_text(json.dumps(out,indent=2)+'\n'); print(OUT); print(hashlib.sha256(OUT.read_bytes()).hexdigest())
if __name__=='__main__': main()
