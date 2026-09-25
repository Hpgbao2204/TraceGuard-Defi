package main

import (
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/consensus/beacon"
	"github.com/ethereum/go-ethereum/consensus/ethash"
	"github.com/ethereum/go-ethereum/core"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/core/vm"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/params"
	"github.com/ethereum/go-ethereum/triedb"
	"github.com/holiman/uint256"
)

func testHeader(number uint64, parent common.Hash) types.Header {
	return types.Header{Number: new(big.Int).SetUint64(number), ParentHash: parent, Time: number, Difficulty: big.NewInt(1)}
}

func TestValidateAncestorHeaders(t *testing.T) {
	oldest := testHeader(8, common.Hash{8})
	middle := testHeader(9, oldest.Hash())
	current := testHeader(10, middle.Hash())
	if err := validateAncestorHeaders(&current, []types.Header{middle, oldest}); err != nil {
		t.Fatalf("valid chain rejected: %v", err)
	}
	broken := middle
	broken.ParentHash = common.Hash{99}
	if err := validateAncestorHeaders(&current, []types.Header{broken, oldest}); err == nil {
		t.Fatal("broken parent linkage accepted")
	}
}

func TestCompleteAncestorCoverageRequiredForFidelity(t *testing.T) {
	current := testHeader(10, common.Hash{9})
	parent := testHeader(9, common.Hash{8})
	if hasCompleteAncestorCoverage(&current, []types.Header{parent}) {
		t.Fatal("partial ancestor context marked complete")
	}
	ancestors := make([]types.Header, 10)
	for i := range ancestors {
		number := uint64(9 - i)
		parentHash := common.Hash{byte(number)}
		ancestors[i] = testHeader(number, parentHash)
	}
	if !hasCompleteAncestorCoverage(&current, ancestors) {
		t.Fatal("full pre-genesis ancestor context marked incomplete")
	}
}

func TestSameTransactionDeletionRequiresSuccessfulCreation(t *testing.T) {
	address := common.HexToAddress("0x10000000000000000000000000000000000000aa")
	missingCreation := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Exists: func() *bool { v := false; return &v }()},
	}})
	missingCreation.txIndex = 7
	missingCreation.destructTx[address] = 7
	if missingCreation.validSameTxDeletion(address) {
		t.Fatal("selfdestruct without successful creation was accepted")
	}

	sameTx := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Exists: func() *bool { v := false; return &v }()},
	}})
	sameTx.destructTx[address] = 7
	sameTx.deletionEligible[address] = 7
	if !sameTx.validSameTxDeletion(address) {
		t.Fatal("same-transaction create and selfdestruct was rejected")
	}

	differentTx := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Exists: func() *bool { v := false; return &v }()},
	}})
	differentTx.createdTx[address] = 6
	differentTx.destructTx[address] = 7
	if differentTx.validSameTxDeletion(address) {
		t.Fatal("cross-transaction deletion was accepted")
	}
}

func TestChainContextChecksRequestedHash(t *testing.T) {
	header := testHeader(10, common.Hash{1})
	ctx, err := loadChainContext("missing-ancestors.json", &header, params.AllEthashProtocolChanges)
	if err != nil {
		t.Fatal(err)
	}
	if ctx.GetHeader(header.Hash(), 10) == nil {
		t.Fatal("matching header lookup failed")
	}
	if ctx.GetHeader(common.Hash{2}, 10) != nil {
		t.Fatal("wrong hash lookup accepted")
	}
}

func TestAuthenticatedReadGuardRejectsUnknownStorage(t *testing.T) {
	address := common.HexToAddress("0x1000000000000000000000000000000000000001")
	known := common.HexToHash("0x01")
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Storage: map[string]string{known.Hex(): "0x02"}},
	}})
	guard.onOpcode(0, byte(vm.SLOAD), 0, 0, testOpContext{address: address, stack: []uint256.Int{*uint256.NewInt(known.Big().Uint64())}}, nil, 0, nil)
	if guard.violated {
		t.Fatal("known storage read rejected")
	}
	unknown := uint256.NewInt(3)
	guard.onOpcode(0, byte(vm.SLOAD), 0, 0, testOpContext{address: address, stack: []uint256.Int{*unknown}}, nil, 0, nil)
	if !guard.violated {
		t.Fatal("unknown storage read accepted")
	}
	guard = newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Storage: map[string]string{known.Hex(): "0x02"}},
	}})
	guard.onOpcode(0, byte(vm.SSTORE), 0, 0, testOpContext{address: address, stack: []uint256.Int{*uint256.NewInt(2), *uint256.NewInt(known.Big().Uint64())}}, nil, 0, nil)
	if guard.violated {
		t.Fatal("known SSTORE slot rejected")
	}
	guard.onOpcode(0, byte(vm.SSTORE), 0, 0, testOpContext{address: address, stack: []uint256.Int{*uint256.NewInt(1), *uint256.NewInt(3)}}, nil, 0, nil)
	if !guard.violated {
		t.Fatal("unknown SSTORE slot accepted")
	}
}

func TestAuthenticatedStateDBRejectsUnknownPrecheckAccount(t *testing.T) {
	known := common.HexToAddress("0x1001")
	st, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{known.Hex(): {}}})
	if err != nil {
		t.Fatal(err)
	}
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{known.Hex(): {}}})
	db := &authenticatedStateDB{StateDB: st, guard: guard}
	defer func() {
		if recovered := recover(); recovered == nil {
			t.Fatal("unknown account read did not fail closed")
		} else if _, ok := recovered.(unauthenticatedStateRead); !ok {
			t.Fatalf("unexpected panic type %T", recovered)
		}
	}()
	_ = db.GetBalance(common.HexToAddress("0x1002"))
}

func TestAuthenticatedStateDBBoundaryFailureCarriesStructuredCell(t *testing.T) {
	address := common.HexToAddress("0x1007")
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{}})
	db := &authenticatedStateDB{StateDB: nil, guard: guard}
	defer func() {
		recovered := recover()
		violation, ok := recovered.(unauthenticatedStateRead)
		if !ok {
			t.Fatalf("unexpected panic type %T", recovered)
		}
		guard.recordBoundaryFailure(violation)
		if len(guard.Failures) != 1 {
			t.Fatalf("got %d boundary failures, want 1", len(guard.Failures))
		}
		failure := guard.Failures[0]
		if failure.Method != "GetBalance" || failure.StorageContextAddress != address.Hex() {
			t.Fatalf("boundary identity lost: %+v", failure)
		}
		if failure.Slot != "" || failure.Phase != "state-boundary" {
			t.Fatalf("unexpected boundary fields: %+v", failure)
		}
	}()
	db.GetBalance(address)
}

func TestAuthenticatedStateDBBoundaryFailureCarriesStructuredSlot(t *testing.T) {
	address := common.HexToAddress("0x1008")
	slot := common.HexToHash("0x42")
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {StorageRoot: common.HexToHash("0x99").Hex(), Storage: map[string]string{}},
	}})
	st, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {StorageRoot: common.HexToHash("0x99").Hex(), Storage: map[string]string{}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	db := &authenticatedStateDB{StateDB: st, guard: guard}
	defer func() {
		recovered := recover()
		violation, ok := recovered.(unauthenticatedStateRead)
		if !ok {
			t.Fatalf("unexpected panic type %T", recovered)
		}
		guard.recordBoundaryFailure(violation)
		failure := guard.Failures[0]
		if failure.Method != "GetState" || failure.StorageContextAddress != address.Hex() || failure.Slot != slot.Hex() {
			t.Fatalf("boundary slot identity lost: %+v", failure)
		}
	}()
	db.GetState(address, slot)
}

func TestAuthenticatedStateDBRejectsUnknownHistoricalSlot(t *testing.T) {
	address := common.HexToAddress("0x1003")
	st, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {StorageRoot: common.HexToHash("0x99").Hex(), Storage: map[string]string{}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {StorageRoot: common.HexToHash("0x99").Hex(), Storage: map[string]string{}},
	}})
	db := &authenticatedStateDB{StateDB: st, guard: guard}
	defer func() {
		if recovered := recover(); recovered == nil {
			t.Fatal("unknown slot read did not fail closed")
		}
	}()
	_ = db.GetState(address, common.HexToHash("0x01"))
}

func TestAuthenticatedStateDBRejectsPersistentMutationOnUnknownAccount(t *testing.T) {
	known := common.HexToAddress("0x1004")
	st, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{known.Hex(): {}}})
	if err != nil {
		t.Fatal(err)
	}
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{known.Hex(): {}}})
	db := &authenticatedStateDB{StateDB: st, guard: guard}
	defer func() {
		if recovered := recover(); recovered == nil {
			t.Fatal("unknown account mutation did not fail closed")
		}
	}()
	db.AddBalance(common.HexToAddress("0x1005"), uint256.NewInt(1), tracing.BalanceIncreaseRewardTransactionFee)
}

func TestAuthenticatedStateDBRejectsPersistentMutationOnUnknownSlot(t *testing.T) {
	address := common.HexToAddress("0x1006")
	st, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {StorageRoot: common.HexToHash("0x77").Hex(), Storage: map[string]string{}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {StorageRoot: common.HexToHash("0x77").Hex(), Storage: map[string]string{}},
	}})
	db := &authenticatedStateDB{StateDB: st, guard: guard}
	defer func() {
		if recovered := recover(); recovered == nil {
			t.Fatal("unknown slot mutation did not fail closed")
		}
	}()
	db.SetState(address, common.HexToHash("0x02"), common.HexToHash("0x03"))
}

func TestStateDBInterfaceMethodsAreClassified(t *testing.T) {
	// Keep this inventory explicit: a go-ethereum upgrade must fail CI until
	// every newly added state operation is reviewed for historical reads.
	buckets := map[string]string{
		"CreateAccount": "persistent-mutator", "CreateContract": "persistent-mutator",
		"SubBalance": "persistent-mutator", "AddBalance": "persistent-mutator",
		"GetBalance": "persistent-read", "GetNonce": "persistent-read", "SetNonce": "persistent-mutator",
		"GetCodeHash": "persistent-read", "GetCode": "persistent-read", "SetCode": "persistent-mutator", "GetCodeSize": "persistent-read",
		"GetStateAndCommittedState": "persistent-read", "GetState": "persistent-read", "SetState": "persistent-mutator",
		"SelfDestruct": "persistent-mutator", "HasSelfDestructed": "lifecycle-reviewed",
		"Exist": "persistent-read", "Touch": "persistent-mutator", "IsNewContract": "lifecycle-reviewed", "Empty": "persistent-read",
		"AddRefund": "transaction-local", "SubRefund": "transaction-local", "GetRefund": "transaction-local",
		"GetTransientState": "transaction-local", "SetTransientState": "transaction-local",
		"AddressInAccessList": "transaction-local", "SlotInAccessList": "transaction-local",
		"AddAddressToAccessList": "transaction-local", "AddSlotToAccessList": "transaction-local",
		"Prepare": "lifecycle-reviewed", "RevertToSnapshot": "lifecycle-reviewed", "Snapshot": "lifecycle-reviewed",
		"AddLog": "transaction-local", "AddPreimage": "transaction-local", "Witness": "lifecycle-reviewed",
		"AccessEvents": "transaction-local", "Finalise": "lifecycle-reviewed", "SetTxContext": "transaction-local",
	}
	iface := reflect.TypeOf((*vm.StateDB)(nil)).Elem()
	for i := 0; i < iface.NumMethod(); i++ {
		name := iface.Method(i).Name
		if _, ok := buckets[name]; !ok {
			t.Errorf("vm.StateDB method %s has no reviewed bucket", name)
		}
	}
	for name := range buckets {
		if _, ok := iface.MethodByName(name); !ok {
			t.Errorf("classified method %s is not in vm.StateDB", name)
		}
	}
}

func TestPostStateAccountAcceptsNumericNonce(t *testing.T) {
	var account postStateAccount
	if err := json.Unmarshal([]byte(`{"balance":"0x1","nonce":133}`), &account); err != nil {
		t.Fatalf("numeric nonce rejected: %v", err)
	}
	if account.Nonce != "133" {
		t.Fatalf("nonce = %q, want 133", account.Nonce)
	}
}

func TestPostStateAccountAcceptsHexNonce(t *testing.T) {
	var account postStateAccount
	if err := json.Unmarshal([]byte(`{"nonce":"0x85"}`), &account); err != nil {
		t.Fatalf("hex nonce rejected: %v", err)
	}
	if account.Nonce != "0x85" {
		t.Fatalf("nonce = %q, want 0x85", account.Nonce)
	}
}

func TestAuthenticatedStateRejectsPreV3ProofArtifact(t *testing.T) {
	path := t.TempDir() + "/proofs.json"
	payload := `{"schema_version":2,"header":{"number":"0x0","hash":"0x0","stateRoot":"0x0"},"proofs":[]}`
	if err := os.WriteFile(path, []byte(payload), 0o600); err != nil {
		t.Fatal(err)
	}
	target := testHeader(1, common.Hash{})
	parent := testHeader(0, common.Hash{})
	if _, err := loadAuthenticatedInitialState(path, map[string]map[string]struct{}{}, &target, &parent); err == nil || !strings.Contains(err.Error(), "lacks authenticated code bytes") {
		t.Fatalf("pre-v3 proof artifact was accepted: %v", err)
	}
}

func TestMergeAccountsPreservesAuthenticatedAbsence(t *testing.T) {
	falseValue := false
	trace, _ := json.Marshal(map[string]account{
		"0x1": {Storage: map[string]string{"0x01": "0x02"}},
	})
	auth, _ := json.Marshal(map[string]account{
		"0x1": {Exists: &falseValue, Storage: map[string]string{
			"0x01": "0x0",
		}},
	})
	merged, err := mergeAccounts([]row{{Trace: trace}, {Trace: auth}})
	if err != nil {
		t.Fatal(err)
	}
	value := merged["0x1"]
	if value.Exists == nil || *value.Exists || len(value.Storage) != 0 || value.Balance != "" || value.Code != "" {
		t.Fatalf("absent account retained injected state: %+v", value)
	}
}

func TestMakeStatePreservesAbsentVsExistingEmptyAccount(t *testing.T) {
	absent := common.HexToAddress("0x126")
	existing := common.HexToAddress("0x127")
	falseValue := false
	trueValue := true
	st, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		absent.Hex():   {Exists: &falseValue},
		existing.Hex(): {Exists: &trueValue},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if st.Exist(absent) {
		t.Fatal("authenticated absent account was materialized")
	}
	if !st.Exist(existing) {
		t.Fatal("authenticated existing-empty account was not materialized")
	}
}

func TestPostStateAndProofCodeAcceptEmptyHexCode(t *testing.T) {
	var account postStateAccount
	if err := json.Unmarshal([]byte(`{"code":"0x"}`), &account); err != nil {
		t.Fatalf("empty code rejected: %v", err)
	}
	if account.Code != "0x" {
		t.Fatalf("code = %q, want 0x", account.Code)
	}
}

func TestPreExecutionDoesNotRequireSyntheticSystemCaller(t *testing.T) {
	parent := testHeader(9, common.Hash{9})
	header := testHeader(10, parent.Hash())
	header.ParentBeaconRoot = new(common.Hash)
	initial := AuthenticatedInitialState{Accounts: map[string]account{
		strings.ToLower(params.BeaconRootsAddress.Hex()): {
			Nonce: 1, Code: hexutil.Encode(params.BeaconRootsCode),
			Storage: map[string]string{
				common.BigToHash(new(big.Int).SetUint64(header.Time % 8191)).Hex():      "0x0",
				common.BigToHash(new(big.Int).SetUint64(header.Time%8191 + 8191)).Hex(): "0x0",
			},
		},
	}}
	if err := requirePreExecutionAccounts(initial, &header, &parent, params.AllEthashProtocolChanges); err != nil {
		t.Fatalf("synthetic system caller incorrectly required: %v", err)
	}
}

func TestAuthenticatedReadGuardChecksCallTarget(t *testing.T) {
	caller := common.HexToAddress("0x1")
	target := common.HexToAddress("0x2")
	for _, tc := range []struct {
		name  string
		op    vm.OpCode
		words int
	}{
		{"call", vm.CALL, 6},
		{"callcode", vm.CALLCODE, 6},
		{"delegatecall", vm.DELEGATECALL, 5},
		{"staticcall", vm.STATICCALL, 5},
	} {
		t.Run(tc.name, func(t *testing.T) {
			guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
				caller.Hex(): {}, target.Hex(): {},
			}})
			stack := make([]uint256.Int, tc.words)
			stack[len(stack)-2] = *uint256.NewInt(new(big.Int).SetBytes(target.Bytes()).Uint64())
			guard.onOpcode(0, byte(tc.op), 0, 0, testOpContext{address: caller, stack: stack}, nil, 0, nil)
			if guard.violated {
				t.Fatal("authenticated call target rejected")
			}
			stack[len(stack)-2] = *uint256.NewInt(3)
			guard.onOpcode(0, byte(tc.op), 0, 0, testOpContext{address: caller, stack: stack}, nil, 0, nil)
			if !guard.violated {
				t.Fatal("unauthenticated call target accepted")
			}
		})
	}
}

func TestAuthenticatedReadGuardRejectsShortCallStack(t *testing.T) {
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{})
	guard.onOpcode(0, byte(vm.CALL), 0, 0, testOpContext{stack: []uint256.Int{}}, nil, 0, nil)
	if !guard.violated {
		t.Fatal("short CALL stack was accepted")
	}
}

func TestAuthenticatedReadGuardIgnoresUnmonitoredOpcode(t *testing.T) {
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{})
	guard.onOpcode(0, byte(vm.STOP), 0, 0, testOpContext{}, nil, 0, nil)
	if guard.violated {
		t.Fatal("unmonitored zero-stack opcode was rejected")
	}
}

func TestAuthenticatedReadGuardAllowsStateAfterGethCreationEvidence(t *testing.T) {
	for _, op := range []vm.OpCode{vm.CREATE, vm.CREATE2} {
		address := common.HexToAddress("0x123")
		falseValue := false
		guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
			address.Hex(): {Exists: &falseValue},
		}})
		guard.onEnter(0, byte(op), common.Address{}, address, nil, 0, nil)
		if guard.violated {
			t.Fatalf("%s rejected proof-bound absent destination", op)
		}
		guard.onOpcode(0, byte(op), 0, 0, testOpContext{stack: make([]uint256.Int, 4)}, nil, 0, nil)
	}
	address := common.HexToAddress("0x123")
	falseValue := false
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Exists: &falseValue},
	}})
	guard.onCodeChange(address, common.Hash{}, nil, common.Hash{1}, []byte{0x60, 0x00})
	guard.onOpcode(0, byte(vm.SLOAD), 0, 0, testOpContext{address: address, stack: []uint256.Int{{}}}, nil, 0, nil)
	if guard.violated {
		t.Fatal("authenticated post-creation read rejected")
	}
}

func TestAuthenticatedReadGuardAllowsProofBoundPrefundedCreationDestination(t *testing.T) {
	for _, op := range []vm.OpCode{vm.CREATE, vm.CREATE2} {
		address := common.HexToAddress("0x456")
		guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
			address.Hex(): {Balance: "0x1", Nonce: 0, Code: "0x", Storage: map[string]string{"0x01": "0x02"}},
		}})
		guard.onEnter(0, byte(op), common.Address{}, address, nil, 0, nil)
		if guard.violated {
			t.Fatalf("%s rejected proof-bound prefunded destination", op)
		}
	}
}

func TestAuthenticatedReadGuardRejectsUnknownSlotOnNonEmptyCreatedAccount(t *testing.T) {
	address := common.HexToAddress("0x457")
	falseValue := false
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Exists: &falseValue, StorageRoot: common.Hash{1}.Hex()},
	}})
	guard.onEnter(0, byte(vm.CREATE2), common.Address{}, address, nil, 0, nil)
	guard.onOpcode(0, byte(vm.SLOAD), 0, 0, testOpContext{address: address, stack: []uint256.Int{{}}}, nil, 0, nil)
	if !guard.violated || len(guard.reasons) == 0 || !strings.Contains(guard.reasons[0], "dynamic-unproven-slot") {
		t.Fatalf("unknown slot on non-empty created account was accepted: %v", guard.reasons)
	}
}

func TestAuthenticatedReadFailureIncludesExecutionProvenance(t *testing.T) {
	address := common.HexToAddress("0x459")
	slot := common.HexToHash("0x12")
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{})
	guard.recordFailure(7, 1234, 2, address, vm.SLOAD, &slot, "missing")
	if len(guard.Failures) != 1 {
		t.Fatalf("failure count = %d, want 1", len(guard.Failures))
	}
	failure := guard.Failures[0]
	if failure.TxIndex != 7 || failure.PC != 1234 || failure.Depth != 2 ||
		failure.StorageContextAddress != address.Hex() || failure.Opcode != vm.SLOAD.String() ||
		failure.Slot != slot.Hex() || failure.Reason != "missing" {
		t.Fatalf("unexpected failure provenance: %+v", failure)
	}
}

func TestAuthenticatedReadGuardRejectsUnknownStoreOnNonEmptyCreatedAccount(t *testing.T) {
	address := common.HexToAddress("0x458")
	falseValue := false
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Exists: &falseValue, StorageRoot: common.Hash{1}.Hex()},
	}})
	guard.onEnter(0, byte(vm.CREATE2), common.Address{}, address, nil, 0, nil)
	guard.onOpcode(0, byte(vm.SSTORE), 0, 0, testOpContext{address: address, stack: []uint256.Int{{}, {}}}, nil, 0, nil)
	if !guard.violated || len(guard.reasons) == 0 || !strings.Contains(guard.reasons[0], "SSTORE:dynamic-unproven-slot") {
		t.Fatalf("unknown store on non-empty created account was accepted: %v", guard.reasons)
	}
}

func TestAuthenticatedReadGuardRejectsUnboundCreationDestination(t *testing.T) {
	for _, op := range []vm.OpCode{vm.CREATE, vm.CREATE2} {
		guard := newAuthenticatedReadGuard(AuthenticatedInitialState{})
		address := common.HexToAddress("0x456")
		guard.onEnter(0, byte(op), common.Address{}, address, nil, 0, nil)
		if !guard.violated {
			t.Fatalf("%s accepted destination without proof-bound state", op)
		}
		if len(guard.reasons) != 1 || !strings.Contains(guard.reasons[0], "destination-not-proof-bound") {
			t.Fatalf("%s missing closure reason: %v", op, guard.reasons)
		}
	}
}

func TestLogsEqualComparesSemanticFields(t *testing.T) {
	address := common.HexToAddress("0x123")
	left := []*types.Log{{Address: address, Topics: []common.Hash{{1}}, Data: []byte{2}}}
	right := []*types.Log{{Address: address, Topics: []common.Hash{{1}}, Data: []byte{2}, BlockNumber: 99, Index: 4}}
	if !logsEqual(left, right) {
		t.Fatal("equivalent semantic logs rejected")
	}
	right[0].Data = []byte{3}
	if logsEqual(left, right) {
		t.Fatal("different log data accepted")
	}
}

func TestPostStateMatchesAuthenticatedCells(t *testing.T) {
	address := common.HexToAddress("0x123")
	initial, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Balance: "0x2", Nonce: 1, Code: "0x6000", Storage: map[string]string{"0x01": "0x02"}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if !postStateMatches(initial, nil, map[string]postStateAccount{
		address.Hex(): {Balance: "0x2", Nonce: "0x1", Code: "0x6000", Storage: map[string]string{"0x01": "0x02"}},
	}) {
		t.Fatal("matching post-state cells rejected")
	}
	if postStateMatches(initial, nil, map[string]postStateAccount{
		address.Hex(): {Storage: map[string]string{"0x01": "0x03"}},
	}) {
		t.Fatal("mismatched post-state cell accepted")
	}
}

func TestPostStateMatchesClearedStorageSlot(t *testing.T) {
	address := common.HexToAddress("0x124")
	zeroState, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Storage: map[string]string{"0x01": "0x0"}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	pre := map[string]postStateAccount{address.Hex(): {Storage: map[string]string{"0x01": "0x02"}}}
	post := map[string]postStateAccount{address.Hex(): {Storage: map[string]string{}}}
	if !postStateMatches(zeroState, pre, post) {
		t.Fatal("cleared storage slot rejected")
	}

	nonzeroState, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Storage: map[string]string{"0x01": "0x02"}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if postStateMatches(nonzeroState, pre, post) {
		t.Fatal(" uncleared storage slot accepted")
	}
}

func TestPostStateMatchesFailsClosedForDeletedAccount(t *testing.T) {
	address := common.HexToAddress("0x125")
	st, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {Balance: "0x1"},
	}})
	if err != nil {
		t.Fatal(err)
	}
	pre := map[string]postStateAccount{address.Hex(): {Balance: "0x1"}}
	if postStateMatches(st, pre, map[string]postStateAccount{}) {
		t.Fatal("deleted account accepted without deletion evidence")
	}
}

func TestLoadPoststatesRejectsMissingOrMismatchedEvidence(t *testing.T) {
	dir := t.TempDir()
	path := dir + "/poststates.json"
	if _, err := loadPoststates(path, []string{"0x1"}); err == nil {
		t.Fatal("missing poststate evidence accepted")
	}
	data, err := json.Marshal([]postStateRow{{Index: 1, TxHash: "0x1"}})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadPoststates(path, []string{"0x1"}); err == nil {
		t.Fatal("mismatched poststate row accepted")
	}
}

func TestAuthenticatedReadGuardChecksSelfBalance(t *testing.T) {
	address := common.HexToAddress("0x100")
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		address.Hex(): {},
	}})
	guard.onOpcode(0, byte(vm.SELFBALANCE), 0, 0, testOpContext{address: address}, nil, 0, nil)
	if guard.violated {
		t.Fatal("authenticated SELFBALANCE read rejected")
	}
	guard = newAuthenticatedReadGuard(AuthenticatedInitialState{})
	guard.onOpcode(0, byte(vm.SELFBALANCE), 0, 0, testOpContext{address: address}, nil, 0, nil)
	if !guard.violated {
		t.Fatal("unauthenticated SELFBALANCE read accepted")
	}
}

func TestEVMBlockHashReadsCanonicalAncestors(t *testing.T) {
	oldest := testHeader(1, common.Hash{1})
	previous := testHeader(2, oldest.Hash())
	current := testHeader(3, previous.Hash())
	ctx := chainContext{header: &current, config: params.AllEthashProtocolChanges,
		byNumber: map[uint64]*types.Header{1: &oldest, 2: &previous, 3: &current},
		byHash:   map[common.Hash]*types.Header{oldest.Hash(): &oldest, previous.Hash(): &previous, current.Hash(): &current},
		complete: true}
	contract := common.HexToAddress("0x100")
	for _, depth := range []uint64{1, 2} {
		code := fmt.Sprintf("0x60%02x43034060005260206000f3", depth)
		initial, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
			contract.Hex(): {Code: code},
		}})
		if err != nil {
			t.Fatal(err)
		}
		evm := vm.NewEVM(core.NewEVMBlockContext(&current, ctx, &current.Coinbase), initial, params.AllEthashProtocolChanges, vm.Config{})
		input := []byte{}
		got, _, err := evm.Call(common.Address{}, contract, input, vm.NewGasBudget(1_000_000, 0), uint256.NewInt(0))
		if err != nil {
			t.Fatalf("depth %d: %v", depth, err)
		}
		want := previous.Hash()
		if depth == 2 {
			want = oldest.Hash()
		}
		if len(got) != 32 || common.BytesToHash(got) != want {
			t.Fatalf("depth %d: got %x, want %s", depth, got, want.Hex())
		}
	}
}

func TestPreExecutionSystemAccountsAreRequiredWhenActive(t *testing.T) {
	parent := testHeader(10, common.Hash{1})
	current := testHeader(11, parent.Hash())
	beacon := common.Hash{9}
	current.ParentBeaconRoot = &beacon
	initial := AuthenticatedInitialState{Accounts: map[string]account{}}
	if err := requirePreExecutionAccounts(initial, &current, &parent, params.AllEthashProtocolChanges); err == nil {
		t.Fatal("missing beacon system accounts accepted")
	}
	initial.Accounts[strings.ToLower(params.SystemAddress.Hex())] = account{}
	initial.Accounts[strings.ToLower(params.BeaconRootsAddress.Hex())] = account{
		Code: hexutil.Encode(params.BeaconRootsCode),
		Storage: map[string]string{
			common.BigToHash(new(big.Int).SetUint64(current.Time % 8191)).Hex():      "0x0",
			common.BigToHash(new(big.Int).SetUint64(current.Time%8191 + 8191)).Hex(): "0x0",
		},
	}
	if err := requirePreExecutionAccounts(initial, &current, &parent, params.AllEthashProtocolChanges); err != nil {
		t.Fatalf("complete beacon system accounts rejected: %v", err)
	}
}

func TestAuthorizationAddressesRecoversEIP7702Authority(t *testing.T) {
	key, err := crypto.GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	auth, err := types.SignSetCode(key, types.SetCodeAuthorization{
		ChainID: *uint256.NewInt(1), Address: common.HexToAddress("0x1234"), Nonce: 7,
	})
	if err != nil {
		t.Fatal(err)
	}
	tx := types.NewTx(&types.SetCodeTx{
		ChainID: uint256.NewInt(1), Nonce: 1, GasTipCap: uint256.NewInt(1),
		GasFeeCap: uint256.NewInt(2), Gas: 100000, To: common.HexToAddress("0x5678"),
		Value: uint256.NewInt(0), AuthList: []types.SetCodeAuthorization{auth},
	})
	got, err := authorizationAddresses([]types.Transaction{*tx})
	if err != nil {
		t.Fatal(err)
	}
	want := crypto.PubkeyToAddress(key.PublicKey).Hex()
	if len(got["authorities"]) != 1 || !strings.EqualFold(got["authorities"][0], want) {
		t.Fatalf("authority = %v, want %s", got["authorities"], want)
	}
	if len(got["code_targets"]) != 1 || !strings.EqualFold(got["code_targets"][0], auth.Address.Hex()) {
		t.Fatalf("code target = %v, want %s", got["code_targets"], auth.Address.Hex())
	}
}

func TestEIP7702AuthorityPreservesAbsentVsExistingEmptyState(t *testing.T) {
	key, err := crypto.GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	auth, err := types.SignSetCode(key, types.SetCodeAuthorization{
		ChainID: *uint256.NewInt(1), Address: common.HexToAddress("0x1234"), Nonce: 7,
	})
	if err != nil {
		t.Fatal(err)
	}
	tx := types.NewTx(&types.SetCodeTx{
		ChainID: uint256.NewInt(1), Nonce: 1, GasTipCap: uint256.NewInt(1),
		GasFeeCap: uint256.NewInt(2), Gas: 100000, To: common.HexToAddress("0x5678"),
		AuthList: []types.SetCodeAuthorization{auth},
	})
	addresses, err := authorizationAddresses([]types.Transaction{*tx})
	if err != nil {
		t.Fatal(err)
	}
	authority := common.HexToAddress(addresses["authorities"][0])
	ab := false
	existing := true
	initial, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		authority.Hex():                     {Exists: &ab},
		common.HexToAddress("0x9999").Hex(): {Exists: &existing},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if initial.Exist(authority) {
		t.Fatal("absent EIP-7702 authority was materialized")
	}
	if !initial.Exist(common.HexToAddress("0x9999")) {
		t.Fatal("existing-empty EIP-7702 authority state was not materialized")
	}
}

func TestSyntheticMessageWithDataPreservesSenderAndChangesOnlyData(t *testing.T) {
	key, err := crypto.GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	to := common.HexToAddress("0x1234")
	tx := types.NewTx(&types.LegacyTx{Nonce: 4, GasPrice: big.NewInt(7), Gas: 100000,
		To: &to, Value: big.NewInt(9), Data: []byte{0x01}})
	// Sign the baseline solely so TransactionToMessage can recover its sender.
	signed, err := types.SignTx(tx, types.NewEIP155Signer(big.NewInt(1)), key)
	if err != nil {
		t.Fatal(err)
	}
	msg, err := syntheticMessageWithData(signed, types.NewEIP155Signer(big.NewInt(1)), nil, []byte{0xaa, 0xbb})
	if err != nil {
		t.Fatal(err)
	}
	want, err := types.Sender(types.NewEIP155Signer(big.NewInt(1)), signed)
	if err != nil {
		t.Fatal(err)
	}
	if msg.From != want || !strings.EqualFold(msg.To.Hex(), to.Hex()) || msg.Nonce != signed.Nonce() {
		t.Fatalf("message identity changed: from=%s to=%v nonce=%d", msg.From.Hex(), msg.To, msg.Nonce)
	}
	if !strings.EqualFold(hexutil.Encode(msg.Data), "0xaabb") {
		t.Fatalf("message data = %s", hexutil.Encode(msg.Data))
	}
}

func TestVerifyPreExecutionStateRejectsMissingSystemWrite(t *testing.T) {
	parent := testHeader(10, common.Hash{1})
	header := testHeader(11, parent.Hash())
	beacon := common.Hash{9}
	header.ParentBeaconRoot = &beacon
	initial, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		params.BeaconRootsAddress.Hex(): {
			Code: hexutil.Encode(params.BeaconRootsCode),
		},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if err := verifyPreExecutionState(initial, &header, &parent, params.AllEthashProtocolChanges); err == nil {
		t.Fatal("missing beacon system write accepted")
	}
}

func TestVerifyPreExecutionStateRequiresBothBeaconSlots(t *testing.T) {
	parent := testHeader(10, common.Hash{1})
	header := testHeader(11, parent.Hash())
	beacon := common.Hash{9}
	header.ParentBeaconRoot = &beacon
	initial, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		params.BeaconRootsAddress.Hex(): {},
	}})
	if err != nil {
		t.Fatal(err)
	}
	index := header.Time % 8191
	initial.SetState(params.BeaconRootsAddress,
		common.BigToHash(new(big.Int).SetUint64(index)),
		common.BigToHash(new(big.Int).SetUint64(header.Time)))
	if err := verifyPreExecutionState(initial, &header, &parent, params.AllEthashProtocolChanges); err == nil {
		t.Fatal("missing beacon root slot accepted")
	}
	initial.SetState(params.BeaconRootsAddress,
		common.BigToHash(new(big.Int).SetUint64(index+8191)), beacon)
	if err := verifyPreExecutionState(initial, &header, &parent, params.AllEthashProtocolChanges); err != nil {
		t.Fatalf("complete beacon writes rejected: %v", err)
	}
}

func TestGeneratedBlockPersistsBeaconRootAndTimestamp(t *testing.T) {
	config := *params.MergedTestChainConfig
	genesis := &core.Genesis{
		Config: &config,
		Alloc: types.GenesisAlloc{
			params.BeaconRootsAddress: {Nonce: 1, Code: params.BeaconRootsCode},
		},
		GasLimit: 10_000_000,
	}
	db, blocks, _ := core.GenerateChainWithGenesis(genesis, beacon.New(ethash.NewFaker()), 1,
		func(_ int, gen *core.BlockGen) { gen.SetParentBeaconRoot(common.Hash{9}) })
	defer db.Close()
	trieDB := triedb.NewDatabase(db, triedb.HashDefaults)
	defer trieDB.Close()
	st, err := state.New(blocks[0].Root(), state.NewDatabase(trieDB, state.NewCodeDB(db)))
	if err != nil {
		t.Fatal(err)
	}
	index := blocks[0].Time() % 8191
	if got := st.GetState(params.BeaconRootsAddress, common.BigToHash(new(big.Int).SetUint64(index))); got != common.BigToHash(new(big.Int).SetUint64(blocks[0].Time())) {
		t.Fatalf("timestamp slot = %s", got.Hex())
	}
	if got := st.GetState(params.BeaconRootsAddress, common.BigToHash(new(big.Int).SetUint64(index+8191))); got != (common.Hash{9}) {
		t.Fatalf("beacon root slot = %s", got.Hex())
	}
}

func TestGeneratedBlockPersistsParentHashHistory(t *testing.T) {
	config := *params.MergedTestChainConfig
	config.PragueTime = new(uint64)
	genesis := &core.Genesis{
		Config: &config,
		Alloc: types.GenesisAlloc{
			params.HistoryStorageAddress: {Nonce: 1, Code: params.HistoryStorageCode},
		},
		GasLimit: 10_000_000,
	}
	db, blocks, _ := core.GenerateChainWithGenesis(genesis, beacon.New(ethash.NewFaker()), 1,
		func(_ int, _ *core.BlockGen) {})
	defer db.Close()
	trieDB := triedb.NewDatabase(db, triedb.HashDefaults)
	defer trieDB.Close()
	st, err := state.New(blocks[0].Root(), state.NewDatabase(trieDB, state.NewCodeDB(db)))
	if err != nil {
		t.Fatal(err)
	}
	slot := common.BigToHash(new(big.Int).SetUint64(blocks[0].NumberU64() - 1))
	if got := st.GetState(params.HistoryStorageAddress, slot); got != blocks[0].ParentHash() {
		t.Fatalf("history slot = %s, want %s", got.Hex(), blocks[0].ParentHash().Hex())
	}
}

func TestHistoryStorageUsesPreviousBlockRingIndexAbove8191(t *testing.T) {
	parent := testHeader(8192, common.Hash{8})
	header := testHeader(8193, parent.Hash())
	config := *params.MergedTestChainConfig
	zero := uint64(0)
	config.PragueTime = &zero
	initial, err := makeState(AuthenticatedInitialState{Accounts: map[string]account{
		params.HistoryStorageAddress.Hex(): {
			Code: hexutil.Encode(params.HistoryStorageCode),
			Storage: map[string]string{
				common.BigToHash(new(big.Int).SetUint64((header.Number.Uint64() - 1) % 8191)).Hex(): "0x0",
			},
		},
	}})
	if err != nil {
		t.Fatal(err)
	}
	// The assertion is intentionally on the wrapped ring index: for block
	// 8193, Geth writes parent hash at slot 1, not slot 2.
	if err := verifyPreExecutionState(initial, &header, &parent, &config); err == nil {
		t.Fatal("zero history slot unexpectedly matched parent hash")
	}
	initial.SetState(params.HistoryStorageAddress,
		common.BigToHash(new(big.Int).SetUint64((header.Number.Uint64()-1)%8191)), parent.Hash())
	if err := verifyPreExecutionState(initial, &header, &parent, &config); err != nil {
		t.Fatalf("previous-block ring slot rejected: %v", err)
	}
}

type testOpContext struct {
	address common.Address
	stack   []uint256.Int
}

func (c testOpContext) MemoryData() []byte       { return nil }
func (c testOpContext) StackData() []uint256.Int { return c.stack }
func (c testOpContext) Caller() common.Address   { return common.Address{} }
func (c testOpContext) Address() common.Address  { return c.address }
func (c testOpContext) CallValue() *uint256.Int  { return uint256.NewInt(0) }
func (c testOpContext) CallInput() []byte        { return nil }
func (c testOpContext) ContractCode() []byte     { return nil }

func TestAddDiscoveredStoragePreservesExistingFootprint(t *testing.T) {
	discovered := map[string]map[string]struct{}{
		"0x0000000000000000000000000000000000000001": {
			strings.ToLower(common.HexToHash("0x01").Hex()): {},
		},
	}
	addDiscoveredStorage(discovered, "0x1", map[string]string{"0x02": "0x0"})
	if _, ok := discovered["0x0000000000000000000000000000000000000001"][strings.ToLower(common.HexToHash("0x01").Hex())]; !ok {
		t.Fatal("existing normal-prestate slot was discarded")
	}
	if _, ok := discovered["0x0000000000000000000000000000000000000001"][strings.ToLower(common.HexToHash("0x02").Hex())]; !ok {
		t.Fatal("poststate slot was not merged")
	}
}

func TestSyntheticCodeRequiresProofBoundAbsentReservedShadow(t *testing.T) {
	shadow := common.HexToAddress("0x000000000000000000000000000000000000f1a3")
	present := true
	guard := newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		shadow.Hex(): {Exists: boolPtr(false)},
	}})
	guard.allowSyntheticCode(shadow)
	if guard.violated {
		t.Fatal("proof-bound absent reserved shadow was rejected")
	}

	guard = newAuthenticatedReadGuard(AuthenticatedInitialState{Accounts: map[string]account{
		shadow.Hex(): {Exists: &present},
	}})
	guard.allowSyntheticCode(shadow)
	if !guard.violated {
		t.Fatal("existing reserved shadow was accepted for synthetic code")
	}

	guard = newAuthenticatedReadGuard(AuthenticatedInitialState{})
	guard.allowSyntheticCode(shadow)
	if !guard.violated {
		t.Fatal("unproofed reserved shadow was accepted for synthetic code")
	}
}
