pragma solidity ^0.8.20;

contract MureDistributionContractSignerSham {
    address immutable historicalImplementation;
    constructor(address implementation_) { historicalImplementation = implementation_; }
    fallback() external payable {
        address impl = historicalImplementation;
        assembly {
            calldatacopy(0, 0, calldatasize())
            let ok := delegatecall(gas(), impl, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch ok case 0 { revert(0, returndatasize()) } default { return(0, returndatasize()) }
        }
    }
    receive() external payable {}
}
