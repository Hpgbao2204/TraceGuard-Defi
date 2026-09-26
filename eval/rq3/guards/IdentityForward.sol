// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "./ShadowForward.sol";

/// @notice Control for the guard restorations: the same wrapper without a check. Installed at the same
/// address with the same shadow copy, it must reproduce the baseline (no revert, unchanged loss), which
/// shows that the wrapping itself does not change the outcome.
contract IdentityForward is ShadowForward {
    fallback() external payable {
        _forward();
    }
}
