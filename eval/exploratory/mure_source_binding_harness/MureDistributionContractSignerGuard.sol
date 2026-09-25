// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Historical-runtime wrapper used only for a proof-bound replay.
/// It rejects contract-valued distribution sources and delegates every other
/// selector to the copied historical implementation.
contract MureDistributionContractSignerGuard {
    address private immutable historicalImplementation;

    struct DistributionRecord {
        address token;
        address source;
        address repository;
        address depositor;
        string poolName;
        uint256 amount;
        uint256 deadline;
    }

    constructor(address implementation_) {
        historicalImplementation = implementation_;
    }

    function distribute(DistributionRecord calldata distribution, address to, bytes calldata signature) external {
        require(distribution.source.code.length == 0, "contract signer/source rejected");
        _delegate(abi.encodeWithSelector(this.distribute.selector, distribution, to, signature));
    }

    fallback() external payable {
        _delegate(msg.data);
    }

    receive() external payable {
        _delegate(bytes("") );
    }

    function _delegate(bytes memory data) private {
        address implementation = historicalImplementation;
        assembly {
            let ok := delegatecall(gas(), implementation, add(data, 32), mload(data), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch ok
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }
}
