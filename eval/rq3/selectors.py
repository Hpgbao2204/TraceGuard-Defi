"""Known 4-byte selectors (each checked with keccak256 of the signature)."""
from __future__ import annotations

SELECTORS = {
    "0x70a08231": "balanceOf(address)",
    "0x095ea7b3": "approve(address,uint256)",
    "0xdd62ed3e": "allowance(address,address)",
    "0x01ffc9a7": "supportsInterface(bytes4)",
    "0x1626ba7e": "isValidSignature(bytes32,bytes)",
    "0xac9650d8": "multicall(bytes[])",
    "0xa9059cbb": "transfer(address,uint256)",
    "0x23b872dd": "transferFrom(address,address,uint256)",
    "0x18160ddd": "totalSupply()",
    "0xd0e30db0": "deposit()",
    "0x2e1a7d4d": "withdraw(uint256)",
    "0xc45a0155": "factory()",
    "0x0dfe1681": "token0()",
    "0xd21220a7": "token1()",
    "0x0902f1ac": "getReserves()",
    "0x6a627842": "mint(address)",
    "0x89afcb44": "burn(address)",
    "0x022c0d9f": "swap(uint256,uint256,address,bytes)",
    "0xbc25cf77": "skim(address)",
    "0xfff6cae9": "sync()",
    "0x10d1e85c": "uniswapV2Call(address,uint256,uint256,bytes)",
    "0x84800812": "pancakeCall(address,uint256,uint256,bytes)",
    "0xf04f2707": "receiveFlashLoan(address[],uint256[],uint256[],bytes)",  # Balancer vault callback
    "0x5c38449e": "flashLoan(address,address[],uint256[],bytes)",  # Balancer vault
    "0x920f5c84": "executeOperation(address[],uint256[],uint256[],address,bytes)",  # Aave V2/V3 flashLoan callback
    "0xee872558": "executeOperation(address,uint256,uint256,bytes)",  # Aave V1
    "0x23e30c8b": "onFlashLoan(address,address,uint256,uint256,bytes)",  # ERC-3156
    "0xe9cbafb0": "uniswapV3FlashCallback(uint256,uint256,bytes)",
    "0xfa461e33": "uniswapV3SwapCallback(int256,int256,bytes)",
    "0x490e6cbc": "flash(address,uint256,uint256,bytes)",
    "0x31f57072": "onMorphoFlashLoan(uint256,bytes)",
    "0x8b418713": "callFunction(address,(address,uint256),bytes)",  # dYdX
    "0xd06ca61f": "getAmountsOut(uint256,address[])",
    "0x38ed1739": "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
    "0x5c11d795": "swapExactTokensForTokensSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)",
    "0xe8e33700": "addLiquidity(address,address,uint256,uint256,uint256,uint256,address,uint256)",
    "0xbaa2abde": "removeLiquidity(address,address,uint256,uint256,uint256,address,uint256)",
    "0x50d25bcd": "latestAnswer()",
    "0xfeaf968c": "latestRoundData()",
}

BALANCE_OF = "0x70a08231"
# Selectors that carry no economic value: permissions and interface probes.
NON_ECONOMIC = {"0x095ea7b3": "approve", "0xdd62ed3e": "allowance", "0x01ffc9a7": "supportsInterface"}


def name(selector: str | None) -> str:
    if not selector:
        return "-"
    sig = SELECTORS.get(selector.lower())
    return sig.split("(")[0] if sig else selector


def holder(args: str | None) -> str | None:
    """The address argument of a one-address call such as balanceOf(address)."""
    if not args or len(args) < 64:
        return None
    return "0x" + args[24:64].lower()
