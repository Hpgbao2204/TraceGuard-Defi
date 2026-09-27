package main

// State-diff comparison for prefix transactions. The ordering confound J(D)
// compares every intermediate transaction's status, gas, logs, and state diff
// with the observed order. The observed diff is the transaction's diffMode
// prestateTracer row (poststates.json); postStateMatches checks that the
// replayed transaction leaves every item of that diff at its observed value,
// and the write tracker below checks that it net-writes no item outside it.

import (
	"math/big"
	"sort"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/crypto"
)

// writeTracker records the value each item had before its first write in one
// transaction, so that net writes can be told apart from writes that were
// undone within the same transaction.
type writeTracker struct {
	balances map[common.Address]*big.Int
	nonces   map[common.Address]uint64
	codes    map[common.Address]common.Hash
	storage  map[common.Address]map[common.Hash]common.Hash
}

func newWriteTracker() *writeTracker {
	return &writeTracker{
		balances: make(map[common.Address]*big.Int),
		nonces:   make(map[common.Address]uint64),
		codes:    make(map[common.Address]common.Hash),
		storage:  make(map[common.Address]map[common.Hash]common.Hash),
	}
}

// attach chains the tracker onto hooks that may already be set.
func (w *writeTracker) attach(h *tracing.Hooks) {
	prevBalance := h.OnBalanceChange
	h.OnBalanceChange = func(addr common.Address, prev, next *big.Int, reason tracing.BalanceChangeReason) {
		if _, seen := w.balances[addr]; !seen {
			w.balances[addr] = new(big.Int).Set(prev)
		}
		if prevBalance != nil {
			prevBalance(addr, prev, next, reason)
		}
	}
	prevNonce := h.OnNonceChange
	h.OnNonceChange = func(addr common.Address, prev, next uint64) {
		if _, seen := w.nonces[addr]; !seen {
			w.nonces[addr] = prev
		}
		if prevNonce != nil {
			prevNonce(addr, prev, next)
		}
	}
	prevCode := h.OnCodeChange
	h.OnCodeChange = func(addr common.Address, prevCodeHash common.Hash, prevCodeBytes []byte, codeHash common.Hash, code []byte) {
		if _, seen := w.codes[addr]; !seen {
			w.codes[addr] = prevCodeHash
		}
		if prevCode != nil {
			prevCode(addr, prevCodeHash, prevCodeBytes, codeHash, code)
		}
	}
	prevStorage := h.OnStorageChange
	h.OnStorageChange = func(addr common.Address, slot common.Hash, prev, next common.Hash) {
		slots := w.storage[addr]
		if slots == nil {
			slots = make(map[common.Hash]common.Hash)
			w.storage[addr] = slots
		}
		if _, seen := slots[slot]; !seen {
			slots[slot] = prev
		}
		if prevStorage != nil {
			prevStorage(addr, slot, prev, next)
		}
	}
}

// diffMismatches compares what the transaction did to state with what it did
// in the observed order: the items it changed (net of its own undo) and, for
// each, the amount of the change. Balances, nonces, and storage words compare
// as differences (storage modulo 2^256), code as the resulting code hash, so a
// transaction that performs the same writes on a state that an earlier drop
// shifted (a fee recipient's balance, a token balance also moved by the dropped
// transaction) is unchanged, while one that writes other items or other
// amounts is not. The observed change of an item is post minus pre in the
// diffMode prestateTracer row; an item missing on one side is zero there.
func (w *writeTracker) diffMismatches(st *state.StateDB, pre, post map[string]postStateAccount) []string {
	observedBal := make(map[common.Address]*big.Int)
	observedNonce := make(map[common.Address]*big.Int)
	observedCode := make(map[common.Address]common.Hash)
	observedSlot := make(map[common.Address]map[common.Hash]*big.Int)
	word := func(raw string) *big.Int { return common.HexToHash(raw).Big() }
	slotMap := func(a common.Address) map[common.Hash]*big.Int {
		m := observedSlot[a]
		if m == nil {
			m = make(map[common.Hash]*big.Int)
			observedSlot[a] = m
		}
		return m
	}
	for raw, after := range post {
		a := common.HexToAddress(raw)
		before := pre[raw]
		if after.Balance != "" {
			observedBal[a] = new(big.Int).Sub(quantity(after.Balance), quantity(before.Balance))
		}
		if after.Nonce != "" {
			observedNonce[a] = new(big.Int).Sub(quantity(after.Nonce), quantity(before.Nonce))
		}
		if after.Code != "" {
			code, _ := hexutil.Decode(after.Code)
			observedCode[a] = crypto.Keccak256Hash(code)
		}
		for rawSlot, value := range after.Storage {
			prev := "0x0"
			if before.Storage != nil {
				if v, ok := before.Storage[rawSlot]; ok {
					prev = v
				}
			}
			slotMap(a)[common.HexToHash(rawSlot)] = wordDelta(word(value), word(prev))
		}
	}
	// diffMode keeps only changed slots in pre; a slot there but not in post
	// was cleared, and an account in pre but not in post was deleted.
	for raw, before := range pre {
		a := common.HexToAddress(raw)
		after, inPost := post[raw]
		if !inPost && before.Balance != "" && quantity(before.Balance).Sign() != 0 {
			observedBal[a] = new(big.Int).Neg(quantity(before.Balance))
		}
		for rawSlot, value := range before.Storage {
			if _, kept := after.Storage[rawSlot]; kept {
				continue
			}
			slotMap(a)[common.HexToHash(rawSlot)] = wordDelta(new(big.Int), word(value))
		}
	}

	var out []string
	zero := new(big.Int)
	get := func(m map[common.Address]*big.Int, a common.Address) *big.Int {
		if v, ok := m[a]; ok {
			return v
		}
		return zero
	}
	// balances and nonces: every address changed on either side
	balAddrs := make(map[common.Address]struct{})
	for a := range observedBal {
		balAddrs[a] = struct{}{}
	}
	for a := range w.balances {
		balAddrs[a] = struct{}{}
	}
	for a := range balAddrs {
		actual := zero
		if before, ok := w.balances[a]; ok {
			actual = new(big.Int).Sub(st.GetBalance(a).ToBig(), before)
		}
		if actual.Cmp(get(observedBal, a)) != 0 {
			out = append(out, "balance:"+strings.ToLower(a.Hex()))
		}
	}
	nonceAddrs := make(map[common.Address]struct{})
	for a := range observedNonce {
		nonceAddrs[a] = struct{}{}
	}
	for a := range w.nonces {
		nonceAddrs[a] = struct{}{}
	}
	for a := range nonceAddrs {
		actual := zero
		if before, ok := w.nonces[a]; ok {
			actual = new(big.Int).Sub(new(big.Int).SetUint64(st.GetNonce(a)), new(big.Int).SetUint64(before))
		}
		if actual.Cmp(get(observedNonce, a)) != 0 {
			out = append(out, "nonce:"+strings.ToLower(a.Hex()))
		}
	}
	emptyCode := crypto.Keccak256Hash(nil)
	codeAddrs := make(map[common.Address]struct{})
	for a := range observedCode {
		codeAddrs[a] = struct{}{}
	}
	for a := range w.codes {
		codeAddrs[a] = struct{}{}
	}
	for a := range codeAddrs {
		current := crypto.Keccak256Hash(st.GetCode(a))
		before, tracked := w.codes[a]
		if before == (common.Hash{}) {
			before = emptyCode
		}
		changed := tracked && current != before
		want, observed := observedCode[a]
		if changed != observed || (observed && current != want) {
			out = append(out, "code:"+strings.ToLower(a.Hex()))
		}
	}
	slotKeys := make(map[common.Address]map[common.Hash]struct{})
	add := func(a common.Address, k common.Hash) {
		if slotKeys[a] == nil {
			slotKeys[a] = make(map[common.Hash]struct{})
		}
		slotKeys[a][k] = struct{}{}
	}
	for a, m := range observedSlot {
		for k := range m {
			add(a, k)
		}
	}
	for a, m := range w.storage {
		for k := range m {
			add(a, k)
		}
	}
	for a, keys := range slotKeys {
		for k := range keys {
			actual := zero
			if before, ok := w.storage[a][k]; ok {
				actual = wordDelta(st.GetState(a, k).Big(), before.Big())
			}
			want := zero
			if m := observedSlot[a]; m != nil {
				if v, ok := m[k]; ok {
					want = v
				}
			}
			if actual.Cmp(want) != 0 {
				out = append(out, "storage:"+strings.ToLower(a.Hex())+":"+k.Hex())
			}
		}
	}
	sort.Strings(out)
	return out
}

var twoTo256 = new(big.Int).Lsh(big.NewInt(1), 256)

// wordDelta is after minus before modulo 2^256.
func wordDelta(after, before *big.Int) *big.Int {
	d := new(big.Int).Sub(after, before)
	return d.Mod(d, twoTo256)
}
