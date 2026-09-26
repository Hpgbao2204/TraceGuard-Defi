// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "./ShadowForward.sol";

/// @notice MureDistribution (proxy 0x36508371..., implementation 0xec9c8e3b..., May 2026). `distribute`
/// takes a distribution record, a caller-supplied signer and a signature, validates the signature against
/// that signer (ERC-1271 for contracts), and then pulls `record.from`'s tokens by transferFrom. The signer
/// is never tied to the account whose tokens move, so an attacker-deployed signer that accepts any
/// signature authorizes a transfer from any holder that approved the distribution contract. The restored
/// check requires the signer to be the holder whose tokens are distributed. The implementation is not
/// source-verified; the argument layout is decoded from the attack calldata: distribute(record, signer,
/// signature) with record = (token, operator, from, to, name, amount, deadline).
contract MureSignerGuard is ShadowForward {
    bytes4 internal constant DISTRIBUTE = 0x5d4f9ff8;

    fallback() external payable {
        if (msg.sig == DISTRIBUTE) {
            uint256 record = 4 + _word(4);
            address signer = address(uint160(_word(4 + 32)));
            address from = address(uint160(_word(record + 2 * 32)));
            require(signer == from, "MureDistribution: signer not authorized");
        }
        _forward();
    }
}
