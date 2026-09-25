package main

import (
	"math/big"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/tracing"
)

// newLeanHooks is the -lean target tracer: only what the victim-harm ledger
// needs. Logs come from the StateDB, so no OnLog hook is installed; ETH
// movements come from balance changes; top-level revert data is kept for the
// verdict. No call frames, storage changes or opcode events are recorded, so
// the per-opcode cost is only the authenticated read guard.
func newLeanHooks() (*tracing.Hooks, *string, *[]balanceChange) {
	revertData := ""
	balanceChanges := make([]balanceChange, 0)
	hooks := &tracing.Hooks{
		OnExit: func(depth int, output []byte, _ uint64, _ error, reverted bool) {
			if depth == 0 && reverted && len(output) > 0 {
				revertData = hexutil.Encode(output)
			}
		},
		OnBalanceChange: func(addr common.Address, previous, current *big.Int, _ tracing.BalanceChangeReason) {
			balanceChanges = append(balanceChanges, balanceChange{Address: addr.Hex(), Previous: previous.String(), Current: current.String()})
		},
	}
	return hooks, &revertData, &balanceChanges
}
