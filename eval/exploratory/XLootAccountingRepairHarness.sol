// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @dev Executable characterization of the verified XLoot accounting rule.
/// It deliberately omits token transfers and proxy storage: this is not a
/// replacement for historical runtime replay.
contract XLootAccountingRepairHarness {
    function sourcePayout(uint256[] calldata ids, uint256 reward)
        external pure returns (uint256 total)
    {
        for (uint256 i; i < ids.length; ++i) total += reward;
    }

    function dedupPayout(uint256[] calldata ids, uint256 reward)
        external pure returns (uint256 total)
    {
        for (uint256 i; i < ids.length; ++i) {
            bool seen;
            for (uint256 j; j < i; ++j) if (ids[j] == ids[i]) { seen = true; break; }
            if (!seen) total += reward;
        }
    }

    /// @dev Shape-preserving repair: duplicate occurrences are no-op for
    /// accounting, while the original calldata remains available to callers.
    function repairedPayout(uint256[] calldata ids, uint256 reward)
        external pure returns (uint256 total)
    {
        for (uint256 i; i < ids.length; ++i) {
            bool seen;
            for (uint256 j; j < i; ++j) if (ids[j] == ids[i]) { seen = true; break; }
            if (!seen) total += reward;
        }
    }
}
