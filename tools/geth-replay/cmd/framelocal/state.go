package main

import "github.com/ethereum/go-ethereum/common"

// AuthenticatedInitialState is the proof-bound state representation used by
// the frame-local executable. The frame-local port intentionally keeps this
// type local so the default B2 runner remains unchanged.
type AuthenticatedInitialState struct {
	Accounts  map[string]account
	StateRoot common.Hash
	Block     uint64
}
