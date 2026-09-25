"""Read-only net ERC-20 balance preflight for the Dough target."""
import json
import urllib.request
from pathlib import Path

TX = "0x92cdcc732eebf47200ea56123716e337f6ef7d5ad714a2295794fdc6031ebb2e"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ADDRESSES = [
    "0x000000d40b595b94918a28b27d1e2c66f43a51d3",
    "0x3bf0c6ef79334727a6652e90818649645e4ae5e8",
    "0x67104175fc5fabbdb5a1876c3914e04b94c71741",
    "0x11a8dc866c5d03ff06bb74565b6575537b215978",
    "0x2913d90d94c9833b11a3e77f136da03075c04a0f",
    "0xba12222222228d8ba445958a75a0704d566bf2c8",
    "0x98c23e9d8f34fefb1b7bd6a91b7ff122f4e16f5c",
    "0x534a3bb1ecb886ce9e7632e33d97bf22f838d085",
]

def main():
    env = {}
    for line in (Path(__file__).parents[1] / ".env").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            env[key] = value.strip().strip('"').strip("'")
    url = env["ARCHIVE_RPC"]
    def call(method, params):
        request = urllib.request.Request(url, data=json.dumps({"jsonrpc":"2.0", "id":1, "method":method, "params":params}).encode(), headers={"content-type":"application/json"})
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response).get("result")
    tx = call("eth_getTransactionByHash", [TX])
    block = int(tx["blockNumber"], 16)
    receipt = call("eth_getTransactionReceipt", [TX])
    transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    flows = []
    for log in receipt["logs"]:
        if log["topics"][0].lower() == transfer_topic and len(log["topics"]) >= 3:
            flows.append({"token":log["address"].lower(), "from":"0x"+log["topics"][1][-40:].lower(), "to":"0x"+log["topics"][2][-40:].lower(), "amount_raw":int(log["data"],16), "log_index":int(log["logIndex"],16)})
    observations = []
    for token in [USDC, WETH]:
        for address in ADDRESSES:
            data = "0x70a08231" + "0" * 24 + address[2:]
            before = int(call("eth_call", [{"to":token,"data":data}, hex(block-1)]), 16)
            after = int(call("eth_call", [{"to":token,"data":data}, hex(block)]), 16)
            observations.append({"token":token,"address":address,"before_raw":before,"after_raw":after,"delta_raw":after-before})
    result = {"schema_version":1,"status":"HARM_ENTITY_PENDING","tx_hash":TX,"block":block,"tx_index":int(tx["transactionIndex"],16),"transfer_flows":flows,"balance_observations":observations,"missing":["independent protected-entity adjudication","frozen harm aggregation/valuation policy"]}
    path = Path(__file__).parents[1] / "eval/results/m6_dough_harm_preflight.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print("wrote", path, "flows", len(flows), "balances", len(observations))

if __name__ == "__main__":
    main()
