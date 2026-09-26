// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "./ShadowForward.sol";

/// @notice RnsPay (0x4c7f92d7..., Mar. 2025). RnsPay keeps an owner-managed allowlist `exchanges` and an
/// `enable()` setter, but `_convert` calls `payment.dexRouterContractAddress` with caller-supplied calldata
/// without consulting it, so a caller can make RnsPay call `USDC.transferFrom(victim, attacker, amount)`
/// against any account that approved RnsPay. The restored check is the missing
/// `require(exchanges[payment.dexRouterContractAddress])` in `pay`.
contract RnsPayExchangeGuard is ShadowForward {
    bytes4 internal constant PAY = 0xe232fa9f; // pay((string,uint256,uint256,uint256,address,address,address,address,address,uint8,bytes,uint256))
    uint256 internal constant EXCHANGES_SLOT = 2; // Ownable._owner = 0, Ownable2Step._pendingOwner = 1

    fallback() external payable {
        if (msg.sig == PAY) {
            uint256 head = 4 + _word(4); // start of the Payment tuple
            address router = address(uint160(_word(head + 5 * 32))); // dexRouterContractAddress
            if (router != address(0)) {
                bytes32 slot = keccak256(abi.encode(router, EXCHANGES_SLOT));
                uint256 enabled;
                assembly { enabled := sload(slot) }
                require(enabled != 0, "RnsPay: exchange not allowed");
            }
        }
        _forward();
    }
}
