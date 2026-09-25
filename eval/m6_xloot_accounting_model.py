"""Reference accounting model for the verified XLoot Staking source.

This model is deliberately independent of calldata deduplication.  It models
the entitlement rule: one reward entitlement per distinct XLoot id, using the
pre-redeem cursor and epoch rewards.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence


def _validate_inputs(
    ids: Sequence[int],
    next_redeem: Mapping[int, int],
    epoch_rewards: Sequence[int],
    next_epoch_id: int,
) -> None:
    """Reject missing observations instead of silently treating them as zero."""
    if next_epoch_id < 0 or next_epoch_id > len(epoch_rewards):
        raise ValueError("epoch reward observation is incomplete")
    missing = [token_id for token_id in dict.fromkeys(ids) if token_id not in next_redeem]
    if missing:
        raise ValueError(f"nextRedeem observation is incomplete for IDs: {missing}")


def authorized_payout(
    ids: Sequence[int],
    next_redeem: Mapping[int, int],
    epoch_rewards: Sequence[int],
    next_epoch_id: int,
) -> int:
    """Return payout authorized by the source-grounded one-use entitlement.

    Epoch ids are treated as zero-based indexes, matching the source loop
    ``for (j = fromEpoc; j < $.nextEpocId; j++)``.  IDs with no active cursor
    are not claimable under the source condition.
    """
    _validate_inputs(ids, next_redeem, epoch_rewards, next_epoch_id)
    total = 0
    for token_id in dict.fromkeys(ids):
        cursor = int(next_redeem.get(token_id, 0))
        if cursor > 0 and cursor < next_epoch_id:
            total += sum(epoch_rewards[cursor:next_epoch_id])
    return total


def actual_source_payout(
    ids: Sequence[int],
    next_redeem: Mapping[int, int],
    epoch_rewards: Sequence[int],
    next_epoch_id: int,
) -> int:
    """Model the current `_redeemable` loop before its post-loop cursor write."""
    _validate_inputs(ids, next_redeem, epoch_rewards, next_epoch_id)
    total = 0
    for token_id in ids:
        cursor = int(next_redeem.get(token_id, 0))
        if cursor > 0 and cursor < next_epoch_id:
            total += sum(epoch_rewards[cursor:next_epoch_id])
    return total


def accounting_excess(
    ids: Sequence[int],
    next_redeem: Mapping[int, int],
    epoch_rewards: Sequence[int],
    next_epoch_id: int,
) -> int:
    """Return source-loop overpayment relative to the independent rule."""
    return max(
        0,
        actual_source_payout(ids, next_redeem, epoch_rewards, next_epoch_id)
        - authorized_payout(ids, next_redeem, epoch_rewards, next_epoch_id),
    )


def repaired_payout(
    ids: Sequence[int],
    next_redeem: Mapping[int, int],
    epoch_rewards: Sequence[int],
    next_epoch_id: int,
) -> int:
    """Semantic repair: preserve input shape, account each ID once."""
    return authorized_payout(ids, next_redeem, epoch_rewards, next_epoch_id)


if __name__ == "__main__":
    # Small executable characterization check for journal/reviewer use.
    ids = [11, 11, 11, 12]
    cursors = {11: 1, 12: 2}
    rewards = [0, 10, 20, 30]
    assert authorized_payout(ids, cursors, rewards, 4) == 60 + 50
    assert actual_source_payout(ids, cursors, rewards, 4) == 3 * 60 + 50
    assert accounting_excess(ids, cursors, rewards, 4) == 120
    assert repaired_payout(ids, cursors, rewards, 4) == authorized_payout(ids, cursors, rewards, 4)
    varied_ids = [11, 12, 11, 13, 12]
    varied_cursors = {11: 1, 12: 2, 13: 0}
    varied_rewards = [0, 7, 19, 31]
    assert authorized_payout(varied_ids, varied_cursors, varied_rewards, 4) == 107
    assert actual_source_payout(varied_ids, varied_cursors, varied_rewards, 4) == 214
    assert accounting_excess(varied_ids, varied_cursors, varied_rewards, 4) == 107
    assert repaired_payout(varied_ids, varied_cursors, varied_rewards, 4) == 107
    print("m6_xloot_accounting_model: PASS")
