// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "./ShadowForward.sol";

interface IOwnable {
    function owner() external view returns (address);
}

/// @notice vETH launchpad factory (0x62f250cf..., Nov. 2024). VirtualToken.takeLoan is restricted to valid
/// factories (`onlyValidFactory`), but this valid factory exposes the privileged function 0x6c0472da, which
/// takes a vETH loan and adds it as liquidity to a Uniswap V2 pair, to any caller. The attacker used it to
/// inflate the pairs' constant product and drain them. The restored check is the missing `onlyOwner` on
/// that function; the factory is Ownable (owner() is read through the original code).
contract VethFactoryOwnerGuard is ShadowForward {
    bytes4 internal constant PRIVILEGED = 0x6c0472da;

    fallback() external payable {
        if (msg.sig == PRIVILEGED) {
            require(msg.sender == IOwnable(address(this)).owner(), "Ownable: caller is not the owner");
        }
        _forward();
    }
}
