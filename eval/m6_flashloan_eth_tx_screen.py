"""Read-only first gate for proposed Ethereum flash-loan candidates."""
import json, os, urllib.request
from pathlib import Path

HASHES = {
    "Dough Finance":"0x92cdcc732eebf47200ea56123716e337f6ef7d5ad714a2295794fdc6031ebb2e",
    "Clober DEX":"0x8fcdfcded45100437ff94801090355f2f689941dca75de9a702e01670f361c04",
    "XPEPE":"0xbdec39a74e620fc624f90483aff067b17044f81138e6c30038daf7f873159db4",
    "UtopiaSphere":"0x1ddf415a4b18d25e87459ad1416077fe7398d5504171d4ca36e757b1a889f604",
    "Palmswap":"0x62dba55054fa628845fecded658ff5b1ec1c5823f1a5e0118601aa455a30eac9",
    "Euler Finance":"0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d",
    "Indexed Finance":"0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa",
    "Paribus":"0x0e29dcf4e9b211a811caf00fc8294024867bffe4ab2819cc1625d2e9d62390af",
    "FEG Token":"0x77cf448ceaf8f66e06d1537ef83218725670d3a509583ea0d161533fda56c063",
    "TCH":"0xa94338d8aa312ed4b97b2a4dcb27f632b1ade6f3abec667e3bf9f002a75dabe0",
    "Harvest Finance":"0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877",
    "KyberSwap Elastic":"0x396a83df7361519416a6dc960d394e689dd0f158095cbc6a6c387640716f5475",
}

def main():
    env = {}
    for line in (Path(__file__).parents[1]/".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1); env[k] = v.strip().strip('"').strip("'")
    url = env["ARCHIVE_RPC"]
    def call(method, params):
        req = urllib.request.Request(url, data=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode(), headers={"content-type":"application/json"})
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response).get("result")
    out = []
    for name, tx_hash in HASHES.items():
        tx = call("eth_getTransactionByHash", [tx_hash])
        row = {"name": name, "tx_hash": tx_hash, "chain_checked": "ethereum"}
        if tx:
            row.update({"status":"FOUND_ON_ETHEREUM", "block":int(tx["blockNumber"],16), "tx_index":int(tx["transactionIndex"],16), "from":tx["from"], "to":tx["to"]})
            receipt = call("eth_getTransactionReceipt", [tx_hash])
            row["receipt_status"] = int(receipt["status"],16) if receipt else None
            row["log_count"] = len(receipt.get("logs",[])) if receipt else None
        else:
            row["status"] = "NOT_FOUND_ON_ETHEREUM_CHAIN_MISMATCH_OR_UNAVAILABLE"
        out.append(row)
    path = Path(__file__).parents[1]/"eval/results/m6_flashloan_eth_tx_screen.json"
    path.write_text(json.dumps({"schema_version":1,"status":"CHAIN_GATE_ONLY","cases":out}, indent=2)+"\n")
    for row in out: print(row["name"], row["status"], row.get("block",""), row.get("receipt_status",""))
if __name__ == "__main__": main()
