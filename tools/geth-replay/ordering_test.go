package main

import (
	"crypto/ecdsa"
	"encoding/json"
	"math/big"
	"strings"
	"testing"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/core/vm"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/params"
)

// Synthetic single-pool fixture. The pool keeps one reserve in slot 0; a
// call with a 32-byte amount takes that amount out of the reserve (reverting
// when the reserve is short) and logs the new reserve. When the new reserve
// is above 0x50 the pool also reads slot 1, which is never part of the proof
// footprint: that path is only reachable in a counterfactual order and must
// fail closed.
//
//	00 PUSH1 0 SLOAD            r
//	03 PUSH1 0 CALLDATALOAD     r a
//	06 DUP2 DUP2 GT             r a (a>r)
//	09 PUSH1 0x28 JUMPI         -> revert
//	0c SWAP1 SUB                n=r-a
//	0e DUP1 PUSH1 0x50 LT ISZERO
//	13 PUSH1 0x1a JUMPI         -> store unless n>0x50
//	16 PUSH1 1 SLOAD POP        unproven read
//	1a JUMPDEST DUP1 PUSH1 0 SSTORE
//	1f PUSH1 0 MSTORE PUSH1 0x20 PUSH1 0 LOG0 STOP
//	28 JUMPDEST PUSH1 0 DUP1 REVERT
const orderingPoolCode = "0x6000546000358181116028579003806050101560" + "1a57600154505b8060005560005260206000a0005b600080fd"

var (
	orderingPool     = common.HexToAddress("0x00000000000000000000000000000000000000aa")
	orderingCoinbase = common.HexToAddress("0x00000000000000000000000000000000000000cb")
)

type orderingFixture struct {
	config  *params.ChainConfig
	header  types.Header
	initial AuthenticatedInitialState
	txs     []*types.Transaction
}

// newOrderingFixture builds three transactions on one pool: 0 front-run,
// 1 intermediate, 2 victim (target). senders[i] picks the key for tx i so a
// test can reuse one sender across transactions.
func newOrderingFixture(t *testing.T, amounts [3]uint64, senders [3]int) orderingFixture {
	t.Helper()
	config := params.MergedTestChainConfig
	header := types.Header{Number: big.NewInt(1), GasLimit: 30_000_000, Time: 1, Difficulty: big.NewInt(0),
		BaseFee: big.NewInt(1_000_000_000), Coinbase: orderingCoinbase, MixDigest: common.Hash{1}}
	zero := uint64(0)
	header.ExcessBlobGas, header.BlobGasUsed = &zero, &zero
	keys := make([]*ecdsaKey, 3)
	for i := range keys {
		keys[i] = newTestKey(t, byte(i+1))
	}
	accounts := map[string]account{
		orderingPool.Hex(): {Code: orderingPoolCode, Balance: "0x0",
			Storage: map[string]string{common.Hash{}.Hex(): common.BigToHash(big.NewInt(100)).Hex()}},
		orderingCoinbase.Hex(): {Balance: "0x0"},
	}
	for _, key := range keys {
		accounts[key.address.Hex()] = account{Balance: "0x56bc75e2d63100000"}
	}
	signer := types.LatestSigner(config)
	nonces := map[int]uint64{}
	var txs []*types.Transaction
	for i, amount := range amounts {
		key := keys[senders[i]]
		data := common.BigToHash(new(big.Int).SetUint64(amount)).Bytes()
		tx := types.MustSignNewTx(key.private, signer, &types.DynamicFeeTx{ChainID: config.ChainID,
			Nonce: nonces[senders[i]], GasTipCap: big.NewInt(1), GasFeeCap: big.NewInt(2_000_000_000),
			Gas: 100_000, To: &orderingPool, Data: data})
		nonces[senders[i]]++
		txs = append(txs, tx)
	}
	return orderingFixture{config: config, header: header, initial: AuthenticatedInitialState{Accounts: accounts}, txs: txs}
}

// replay mirrors main's prefix loop on the fixture: drop, execute guarded,
// record into the ordering report, and fail closed on an unauthenticated read.
func (f orderingFixture) replay(t *testing.T, ordering *orderingReport, baseline []baselineOutcome) ([]result, replayTiming) {
	t.Helper()
	st, err := makeState(f.initial)
	if err != nil {
		t.Fatal(err)
	}
	guard := newAuthenticatedReadGuard(f.initial)
	gasPool := core.NewGasPool(f.header.GasLimit)
	ctx := chainContext{header: &f.header, config: f.config, byNumber: map[uint64]*types.Header{1: &f.header},
		byHash: map[common.Hash]*types.Header{f.header.Hash(): &f.header}}
	target := len(f.txs) - 1
	var results []result
	var evmReplay, targetEVM time.Duration
	for i, tx := range f.txs {
		guard.txIndex = i
		if ordering != nil && ordering.isDropped(i) {
			ordering.recordDropped(i, tx.Hash().Hex(), baseline[i])
			continue
		}
		config := vm.Config{Tracer: &tracing.Hooks{OnOpcode: guard.onOpcode}}
		evm := vm.NewEVM(core.NewEVMBlockContext(&f.header, ctx, &f.header.Coinbase), &authenticatedStateDB{StateDB: st, guard: guard}, f.config, config)
		logStart := len(st.Logs())
		start := time.Now()
		receipt, _, applyErr := applyTransactionGuarded(evm, gasPool, st, &f.header, tx, guard)
		elapsed := time.Since(start)
		evmReplay += elapsed
		if i == target {
			targetEVM = elapsed
		}
		r := result{Index: i, Hash: tx.Hash().Hex()}
		if applyErr != nil {
			r.Error = applyErr.Error()
		} else {
			r.ActualGas = receipt.GasUsed
			r.ActualOK = receipt.Status == types.ReceiptStatusSuccessful
			r.Logs = append([]*types.Log(nil), st.Logs()[logStart:]...)
		}
		results = append(results, r)
		if ordering != nil {
			ordering.recordExecuted(r, baseline[i], elapsed)
			if guard.violated {
				ordering.failClosed(i, guard.reasons)
				break
			}
		} else if guard.violated {
			t.Fatalf("baseline replay of tx %d read unauthenticated state: %v", i, guard.reasons)
		}
	}
	if ordering != nil {
		ordering.finalize()
	}
	return results, replayTiming{EVMReplay: durationMS(evmReplay), TargetEVM: durationMS(targetEVM)}
}

// observed runs the original order and turns it into the receipts baseline
// the engine compares against.
func (f orderingFixture) observed(t *testing.T) []baselineOutcome {
	t.Helper()
	results, _ := f.replay(t, nil, nil)
	if len(results) != len(f.txs) {
		t.Fatalf("baseline executed %d of %d txs", len(results), len(f.txs))
	}
	out := make([]baselineOutcome, len(results))
	for i, r := range results {
		if r.Error != "" {
			t.Fatalf("baseline tx %d invalid: %s", i, r.Error)
		}
		out[i] = baselineOutcome{Status: r.ActualOK, Gas: r.ActualGas, Logs: r.Logs}
	}
	return out
}

func reserveLogged(t *testing.T, logs []*types.Log) uint64 {
	t.Helper()
	if len(logs) != 1 {
		t.Fatalf("expected one reserve log, got %d", len(logs))
	}
	return new(big.Int).SetBytes(logs[0].Data).Uint64()
}

func TestParseDropIndices(t *testing.T) {
	got, err := parseDropIndices([]string{"3", "0,1"}, 5)
	if err != nil || len(got) != 3 || got[0] != 0 || got[1] != 1 || got[2] != 3 {
		t.Fatalf("got %v, %v", got, err)
	}
	for _, bad := range [][]string{{"5"}, {"-1"}, {"7"}, {"1", "1"}, {"x"}, {""}} {
		if _, err := parseDropIndices(bad, 5); err == nil {
			t.Fatalf("expected %v to be rejected", bad)
		}
	}
	if got, err := parseDropIndices(nil, 5); err != nil || len(got) != 0 {
		t.Fatalf("no drops: got %v, %v", got, err)
	}
}

func TestDropFrontRunChangesVictimAndFlagsIntermediate(t *testing.T) {
	// Baseline: 100 -60-> 40 -30-> 10 -5-> 5.
	f := newOrderingFixture(t, [3]uint64{60, 30, 5}, [3]int{0, 1, 2})
	baseline := f.observed(t)
	if got := reserveLogged(t, baseline[2].Logs); got != 5 {
		t.Fatalf("baseline victim reserve %d, want 5", got)
	}
	report := newOrderingReport([]int{0}, 2)
	results, timing := f.replay(t, report, baseline)
	if !report.Comparable || report.FailClosed {
		t.Fatalf("expected comparable run, got %+v", report)
	}
	if len(report.Prefix) != 3 || report.Prefix[0].Role != "dropped" || report.Prefix[0].Executed {
		t.Fatalf("dropped tx not recorded: %+v", report.Prefix)
	}
	// Counterfactual: 100 -30-> 70 -5-> 65.
	victim := results[len(results)-1]
	if victim.Index != 2 || reserveLogged(t, victim.Logs) != 65 {
		t.Fatalf("victim did not see the counterfactual reserve: %+v", victim)
	}
	if !report.Prefix[2].DiffersFromBaseline || report.Prefix[2].Role != "target" {
		t.Fatalf("target should differ from baseline: %+v", report.Prefix[2])
	}
	if !report.Confounded || len(report.Confounds) != 1 || report.Confounds[0].Index != 1 ||
		!containsString(report.Confounds[0].Kinds, confoundLogsChanged) {
		t.Fatalf("intermediate change not reported as confound: %+v", report.Confounds)
	}
	// Coarse clocks (about 0.5-1 ms on Windows) can report 0 for this tiny
	// fixture, so only the ordering of the figures is checked.
	if timing.EVMReplay < 0 || timing.TargetEVM < 0 || timing.TargetEVM > timing.EVMReplay {
		t.Fatalf("implausible timing %+v", timing)
	}
}

func TestDropFrontRunIntermediateNowSucceedsIsConfound(t *testing.T) {
	// Baseline: 100 -60-> 40; tx1 wants 50 and reverts; victim 40 -5-> 35.
	f := newOrderingFixture(t, [3]uint64{60, 50, 5}, [3]int{0, 1, 2})
	baseline := f.observed(t)
	if baseline[1].Status {
		t.Fatal("fixture: intermediate should revert in the observed order")
	}
	report := newOrderingReport([]int{0}, 2)
	results, _ := f.replay(t, report, baseline)
	if !report.Comparable {
		t.Fatalf("expected comparable run: %+v", report)
	}
	if len(report.Confounds) != 1 || !containsString(report.Confounds[0].Kinds, confoundNowSucceeds) {
		t.Fatalf("expected now_succeeds confound, got %+v", report.Confounds)
	}
	// Counterfactual: 100 -50-> 50 -5-> 45.
	if got := reserveLogged(t, results[len(results)-1].Logs); got != 45 {
		t.Fatalf("victim reserve %d, want 45", got)
	}
}

func TestDropReachingUnprovenSlotFailsClosed(t *testing.T) {
	// Baseline: 100 -60-> 40 -10-> 30 -5-> 25, slot 1 never read.
	// Without tx0, tx1 leaves 90 > 0x50 and reads slot 1, outside the proof.
	f := newOrderingFixture(t, [3]uint64{60, 10, 5}, [3]int{0, 1, 2})
	baseline := f.observed(t)
	report := newOrderingReport([]int{0}, 2)
	results, _ := f.replay(t, report, baseline)
	if !report.FailClosed || report.Comparable {
		t.Fatalf("expected fail-closed, got %+v", report)
	}
	if report.FailClosedTxIndex == nil || *report.FailClosedTxIndex != 1 {
		t.Fatalf("fail-closed at wrong tx: %+v", report.FailClosedTxIndex)
	}
	if len(report.FailClosedReasons) == 0 || !strings.Contains(report.FailClosedReasons[0], "slot:0x0000000000000000000000000000000000000000000000000000000000000001") {
		t.Fatalf("reason does not name the unproven slot: %v", report.FailClosedReasons)
	}
	for _, r := range results {
		if r.Index == 2 {
			t.Fatal("target executed after fail-closed")
		}
	}
	if report.IncomparableCause != "unauthenticated_state_read_after_drop" {
		t.Fatalf("incomparable reason %q", report.IncomparableCause)
	}
}

func TestDropSameSenderMakesLaterTxInvalid(t *testing.T) {
	// tx0 and tx1 share a sender; dropping tx0 leaves tx1 with a nonce gap.
	// Baseline: 100 -60-> 40 -10-> 30 -30-> 0. Counterfactual victim: 100 -30-> 70.
	f := newOrderingFixture(t, [3]uint64{60, 10, 30}, [3]int{0, 0, 2})
	baseline := f.observed(t)
	report := newOrderingReport([]int{0}, 2)
	f.replay(t, report, baseline)
	if len(report.Confounds) != 1 || !containsString(report.Confounds[0].Kinds, confoundInvalid) {
		t.Fatalf("expected invalid confound, got %+v", report.Confounds)
	}
	if !report.Comparable {
		t.Fatalf("an invalid intermediate is a confound, not an incomparable target: %+v", report)
	}
}

func TestDropUnrelatedToVictimLeavesVictimUnchanged(t *testing.T) {
	// Dropping the intermediate when it reverted in the observed order leaves
	// the victim's outcome identical: no effect, no confound.
	f := newOrderingFixture(t, [3]uint64{60, 50, 5}, [3]int{0, 1, 2})
	baseline := f.observed(t)
	report := newOrderingReport([]int{1}, 2)
	f.replay(t, report, baseline)
	if !report.Comparable || report.Confounded {
		t.Fatalf("expected clean comparable run: %+v", report)
	}
	if report.Prefix[2].DiffersFromBaseline {
		t.Fatalf("victim should match baseline: %+v", report.Prefix[2])
	}
}

func TestOrderingOutputCarriesDroppedIndicesAndTiming(t *testing.T) {
	report := newOrderingReport([]int{0}, 2)
	report.finalize()
	out := output{DroppedIndices: report.DroppedIndices, OrderingIntervention: report,
		Timing: replayTiming{EVMReplay: 1.5, TargetEVM: 0.5, Note: replayTimingNote}}
	b, err := json.Marshal(out)
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(b, &decoded); err != nil {
		t.Fatal(err)
	}
	timing, ok := decoded["timing_ms"].(map[string]any)
	if !ok || timing["evm_replay"] != 1.5 {
		t.Fatalf("timing_ms missing: %s", b)
	}
	if _, ok := decoded["dropped_indices"]; !ok {
		t.Fatalf("dropped_indices missing: %s", b)
	}
	intervention := decoded["ordering_intervention"].(map[string]any)
	if intervention["comparable"] != false || intervention["incomparable_reason"] != "target_not_executed" {
		t.Fatalf("empty run must not be comparable: %s", b)
	}
	// A run without -drop-tx keeps timing but omits the intervention block.
	b, _ = json.Marshal(output{})
	if strings.Contains(string(b), "ordering_intervention") || !strings.Contains(string(b), "timing_ms") {
		t.Fatalf("baseline output shape: %s", b)
	}
}

func containsString(values []string, want string) bool {
	for _, value := range values {
		if value == want {
			return true
		}
	}
	return false
}

type ecdsaKey struct {
	private *ecdsa.PrivateKey
	address common.Address
}

func newTestKey(t *testing.T, seed byte) *ecdsaKey {
	t.Helper()
	raw := make([]byte, 32)
	raw[31] = seed
	key, err := crypto.ToECDSA(raw)
	if err != nil {
		t.Fatal(err)
	}
	return &ecdsaKey{private: key, address: crypto.PubkeyToAddress(key.PublicKey)}
}

func TestLeanHooksKeepLedgerInputsOnly(t *testing.T) {
	hooks, revertData, balances := newLeanHooks()
	if hooks.OnOpcode != nil || hooks.OnEnter != nil || hooks.OnStorageChange != nil || hooks.OnLog != nil {
		t.Fatal("lean tracer must not record frames, storage, opcodes or duplicate logs")
	}
	sender := common.HexToAddress("0x01")
	hooks.OnBalanceChange(sender, big.NewInt(10), big.NewInt(7), tracing.BalanceDecreaseGasBuy)
	hooks.OnExit(1, []byte{0xaa}, 0, nil, true)
	if *revertData != "" {
		t.Fatal("inner revert must not be reported as top-level revert data")
	}
	hooks.OnExit(0, []byte{0x08, 0xc3, 0x79, 0xa0}, 0, nil, true)
	if *revertData != "0x08c379a0" {
		t.Fatalf("top-level revert data %q", *revertData)
	}
	if len(*balances) != 1 || (*balances)[0].Current != "7" {
		t.Fatalf("balance changes %+v", *balances)
	}
}
