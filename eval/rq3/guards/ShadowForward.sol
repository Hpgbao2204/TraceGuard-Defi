// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice Guard-restoration wrapper. The replay installs this code at the vulnerable contract and copies
/// the contract's original runtime to SHADOW (an address proven empty at the state block). After its check,
/// the wrapper forwards the call unchanged by DELEGATECALL, so storage, msg.sender and msg.value are those
/// of the original execution; only the restored check is new.
abstract contract ShadowForward {
    address internal constant SHADOW = 0x000000000000000000000000000000000000F1A1;

    function _forward() internal {
        assembly {
            calldatacopy(0, 0, calldatasize())
            let ok := delegatecall(gas(), SHADOW, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch ok
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }

    function _word(uint256 offset) internal pure returns (uint256 w) {
        assembly { w := calldataload(offset) }
    }
}
