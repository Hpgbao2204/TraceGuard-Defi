// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "./ShadowForward.sol";

interface IAccessControlLike {
    function hasRole(bytes32 role, address account) external view returns (bool);
}

/// @notice MureDistribution (proxy 0x36508371..., implementation 0xec9c8e3b9cbe..., May 2026; verified source).
/// `distribute(record, [to,] signature)` reads the signer from `PoolMetadata(record.source).poolState(...)`,
/// verifies the signature against that signer, and then moves `record.amount` of `record.token` from
/// `record.repository` by transferFrom. `record.source` is supplied by the caller and only checked for
/// ERC-165 support, so an attacker-deployed source names itself as signer and accepts any signature
/// (DeFiHackLabs: fake ERC-1271 signer). The contract already ties sources to their operators in
/// `moveDistribution` (`validManager`: the source's IAccessControl must grant POOL_OPERATOR_ROLE); the
/// restored check applies the same rule to `distribute`: the account whose tokens move must be a pool
/// operator of the source that supplies the signer.
/// record = (token, source, repository, depositor, poolName, amount, deadline).
contract MureSignerGuard is ShadowForward {
    bytes4 internal constant DISTRIBUTE_TO = 0x5d4f9ff8; // distribute(record, address to, bytes signature)
    bytes4 internal constant DISTRIBUTE = 0xb61549c0; // distribute(record, bytes signature)
    bytes32 internal constant POOL_OPERATOR_ROLE = keccak256("POOL_OPERATOR");

    fallback() external payable {
        if (msg.sig == DISTRIBUTE_TO || msg.sig == DISTRIBUTE) {
            uint256 record = 4 + _word(4);
            address source = address(uint160(_word(record + 32)));
            address repository = address(uint160(_word(record + 2 * 32)));
            (bool ok, bytes memory ret) = source.staticcall(
                abi.encodeCall(IAccessControlLike.hasRole, (POOL_OPERATOR_ROLE, repository)));
            require(ok && ret.length >= 32 && abi.decode(ret, (bool)), "MureDistribution: unauthorized source");
        }
        _forward();
    }
}
