pragma solidity ^0.8.20;

import "./XLootAccountingRepairHarness.sol";

contract XLootAccountingRepairHarnessTest {
    function testRepeatedIds() external {
        uint256[] memory ids = new uint256[](6);
        ids[0] = 128; ids[1] = 144; ids[2] = 128;
        ids[3] = 145; ids[4] = 144; ids[5] = 128;
        XLootAccountingRepairHarness h = new XLootAccountingRepairHarness();
        require(h.sourcePayout(ids, 1) == 6);
        require(h.dedupPayout(ids, 1) == 3);
        require(h.repairedPayout(ids, 1) == 3);
    }
}
