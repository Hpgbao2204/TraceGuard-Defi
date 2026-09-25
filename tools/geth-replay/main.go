package main

// B2 baseline probe: execute each transaction with go-ethereum's real EVM
// using that transaction's own prestateTracer snapshot.  This first milestone
// is intentionally labelled "prestate-isolated": it validates chain rules,
// header fields, and per-transaction gas/status before we add a sequential
// state builder.  It must not be mistaken for the final prefix replayer.

import (
	"bufio"
	stdcontext "context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"math/big"
	"os"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/consensus"
	"github.com/ethereum/go-ethereum/core"
	"github.com/ethereum/go-ethereum/core/rawdb"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/core/types/bal"
	"github.com/ethereum/go-ethereum/core/vm"
	"github.com/ethereum/go-ethereum/params"
	"github.com/ethereum/go-ethereum/triedb"
	"github.com/holiman/uint256"
)

type row struct {
	Index int             `json:"index"`
	Hash  string          `json:"tx_hash"`
	Trace json.RawMessage `json:"trace"`
}

type account struct {
	Balance     string            `json:"balance"`
	Nonce       uint64            `json:"nonce"`
	Code        string            `json:"code"`
	Storage     map[string]string `json:"storage"`
	StorageRoot string            `json:"storage_root,omitempty"`
	// Exists is populated for accounts whose authenticated proof distinguishes
	// an absent account from an EIP-161-empty account.  That distinction affects
	// EIP-7702's state-dependent gas refund.
	Exists *bool `json:"exists,omitempty"`
}

type postStateAccount struct {
	Balance string            `json:"balance"`
	Nonce   string            `json:"nonce"`
	Code    string            `json:"code"`
	Storage map[string]string `json:"storage"`
}

// UnmarshalJSON accepts the representations emitted by different
// prestateTracer/provider versions.  Quantities are kept as strings after
// decoding so the rest of the runner has one representation.
func (a *postStateAccount) UnmarshalJSON(data []byte) error {
	var raw struct {
		Balance json.RawMessage   `json:"balance"`
		Nonce   json.RawMessage   `json:"nonce"`
		Code    string            `json:"code"`
		Storage map[string]string `json:"storage"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	var err error
	if a.Balance, err = jsonQuantityString(raw.Balance); err != nil {
		return fmt.Errorf("balance: %w", err)
	}
	if a.Nonce, err = jsonQuantityString(raw.Nonce); err != nil {
		return fmt.Errorf("nonce: %w", err)
	}
	a.Code = raw.Code
	a.Storage = raw.Storage
	return nil
}

func jsonQuantityString(raw json.RawMessage) (string, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return "", nil
	}
	if raw[0] == '"' {
		var value string
		if err := json.Unmarshal(raw, &value); err != nil {
			return "", err
		}
		return value, nil
	}
	var number json.Number
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return "", err
	}
	number, ok := value.(json.Number)
	if !ok {
		return "", fmt.Errorf("expected string or number, got %s", raw)
	}
	return number.String(), nil
}

type postStateRow struct {
	Index     int                         `json:"index"`
	TxHash    string                      `json:"tx_hash"`
	Prestate  map[string]postStateAccount `json:"prestate"`
	Poststate map[string]postStateAccount `json:"poststate"`
	Calltrace map[string]any              `json:"calltrace"`
}

func loadPoststates(path string, txHashes []string) ([]postStateRow, error) {
	var rows []postStateRow
	if err := readJSON(path, &rows); err != nil {
		return nil, fmt.Errorf("read poststate evidence: %w", err)
	}
	if len(rows) != len(txHashes) {
		return nil, fmt.Errorf("poststate context counts do not match: got %d, want %d", len(rows), len(txHashes))
	}
	for i, row := range rows {
		if row.Index != i || !strings.EqualFold(row.TxHash, txHashes[i]) {
			return nil, fmt.Errorf("poststate row %d does not match transaction", i)
		}
	}
	return rows, nil
}

func addDiscoveredStorage(discovered map[string]map[string]struct{}, rawAddress string, storage map[string]string) {
	address := strings.ToLower(common.HexToAddress(rawAddress).Hex())
	requested := discovered[address]
	if requested == nil {
		requested = make(map[string]struct{})
		discovered[address] = requested
	}
	for rawSlot := range storage {
		requested[strings.ToLower(common.HexToHash(rawSlot).Hex())] = struct{}{}
	}
}

func addCallTraceDiscovery(value any, discovered map[string]map[string]struct{}) {
	obj, ok := value.(map[string]any)
	if ok {
		typ, _ := obj["type"].(string)
		if strings.EqualFold(typ, "CREATE") || strings.EqualFold(typ, "CREATE2") {
			if raw, ok := obj["to"].(string); ok && common.IsHexAddress(raw) {
				address := strings.ToLower(common.HexToAddress(raw).Hex())
				if _, exists := discovered[address]; !exists {
					discovered[address] = make(map[string]struct{})
				}
			}
		}
		for _, child := range obj {
			addCallTraceDiscovery(child, discovered)
		}
		return
	}
	if list, ok := value.([]any); ok {
		for _, child := range list {
			addCallTraceDiscovery(child, discovered)
		}
	}
}

// AuthenticatedInitialState is the only state representation accepted by the
// StateDB builder. Its accounts have passed proof/value binding first.
type AuthenticatedInitialState struct {
	Accounts  map[string]account
	StateRoot common.Hash
	Block     uint64
}

const goEthereumVersion = "v1.17.5"

func mergeAccounts(rows []row) (map[string]account, error) {
	merged := make(map[string]account)
	seenNonce := make(map[string]bool)
	for _, item := range rows {
		var incoming map[string]account
		if err := json.Unmarshal(item.Trace, &incoming); err != nil {
			return nil, err
		}
		for address, value := range incoming {
			current := merged[address]
			// An authenticated absence is authoritative.  Trace discovery may
			// still list requested zero storage slots for a non-existent account;
			// those are proof queries, not state to inject.
			if value.Exists != nil && !*value.Exists {
				merged[address] = account{Exists: value.Exists}
				continue
			}
			if current.Balance == "" && value.Balance != "" {
				current.Balance = value.Balance
			}
			if current.Code == "" && value.Code != "" {
				current.Code = value.Code
			}
			if !seenNonce[address] {
				current.Nonce = value.Nonce
				seenNonce[address] = true
			}
			if current.Storage == nil {
				current.Storage = make(map[string]string)
			}
			for slot, storageValue := range value.Storage {
				if _, exists := current.Storage[slot]; !exists {
					current.Storage[slot] = storageValue
				}
			}
			if value.Exists != nil {
				current.Exists = value.Exists
			}
			merged[address] = current
		}
	}
	return merged, nil
}

func authorizationAddresses(txs []types.Transaction) (map[string][]string, error) {
	authorities := make(map[string]struct{})
	codeTargets := make(map[string]struct{})
	for _, tx := range txs {
		for _, authorization := range tx.SetCodeAuthorizations() {
			authority, err := authorization.Authority()
			if err != nil {
				return nil, fmt.Errorf("recover EIP-7702 authority for %s: %w", tx.Hash(), err)
			}
			authorities[strings.ToLower(authority.Hex())] = struct{}{}
			codeTargets[strings.ToLower(authorization.Address.Hex())] = struct{}{}
		}
	}
	toSorted := func(values map[string]struct{}) []string {
		addresses := make([]string, 0, len(values))
		for address := range values {
			addresses = append(addresses, address)
		}
		sort.Strings(addresses)
		return addresses
	}
	required := make(map[string]struct{}, len(authorities)+len(codeTargets))
	for address := range authorities {
		required[address] = struct{}{}
	}
	for address := range codeTargets {
		required[address] = struct{}{}
	}
	return map[string][]string{
		"authorities":  toSorted(authorities),
		"code_targets": toSorted(codeTargets),
		"required":     toSorted(required),
	}, nil
}

type result struct {
	Index               int                       `json:"index"`
	Hash                string                    `json:"tx_hash"`
	ExpectedGas         uint64                    `json:"expected_gas"`
	ActualGas           uint64                    `json:"actual_gas"`
	GasMatch            bool                      `json:"gas_match"`
	ExpectedOK          bool                      `json:"expected_status"`
	ActualOK            bool                      `json:"actual_status"`
	StatusMatch         bool                      `json:"status_match"`
	LogsMatch           bool                      `json:"logs_match"`
	PostStateMatch      bool                      `json:"post_state_match"`
	Error               string                    `json:"error,omitempty"`
	RevertData          string                    `json:"revert_data,omitempty"`
	CallTrace           []callFrame               `json:"call_trace,omitempty"`
	Logs                []*types.Log              `json:"logs,omitempty"`
	BalanceChanges      []balanceChange           `json:"balance_changes,omitempty"`
	OpcodeTail          []opcodeEvent             `json:"opcode_tail,omitempty"`
	OpcodeTelemetry     []opcodeEvent             `json:"opcode_telemetry,omitempty"`
	StorageChanges      []storageChange           `json:"storage_changes,omitempty"`
	UnauthenticatedRead bool                      `json:"unauthenticated_read,omitempty"`
	Intervention        *callInterventionEvidence `json:"call_intervention,omitempty"`
}

type callInterventionEvidence struct {
	Caller              string                 `json:"caller"`
	Callee              string                 `json:"callee"`
	Selector            string                 `json:"selector"`
	CallType            string                 `json:"call_type"`
	Depth               int                    `json:"depth"`
	MatchCount          int                    `json:"match_count"`
	SelectedOccurrences []int                  `json:"selected_occurrences,omitempty"`
	AppliedOccurrences  []int                  `json:"applied_occurrences,omitempty"`
	Action              string                 `json:"action"`
	ApplicationVerified bool                   `json:"application_verified"`
	CallbackAttempted   bool                   `json:"callback_attempted,omitempty"`
	CallbackCaller      string                 `json:"callback_caller,omitempty"`
	CallbackTo          string                 `json:"callback_to,omitempty"`
	CallbackInput       string                 `json:"callback_input,omitempty"`
	CallbackError       string                 `json:"callback_error,omitempty"`
	MatchedInput        string                 `json:"matched_input,omitempty"`
	MatchedDepth        int                    `json:"matched_depth,omitempty"`
	MatchedOutput       string                 `json:"matched_output,omitempty"`
	OriginalValue       string                 `json:"original_value,omitempty"`
	RewrittenValue      string                 `json:"rewritten_value,omitempty"`
	FirstRevertDepth    int                    `json:"first_revert_depth,omitempty"`
	FirstRevertData     string                 `json:"first_revert_data,omitempty"`
	StoragePatches      []storagePatchEvidence `json:"storage_patches,omitempty"`
}

type storagePatchEvidence struct {
	Address  string `json:"address"`
	Slot     string `json:"slot"`
	Before   string `json:"before"`
	After    string `json:"after"`
	ReadBack string `json:"read_back"`
}

type balanceChange struct {
	Address  string `json:"address"`
	Previous string `json:"previous"`
	Current  string `json:"current"`
}

type storageChange struct {
	Address  string `json:"address"`
	Slot     string `json:"slot"`
	Previous string `json:"previous"`
	Current  string `json:"current"`
}

type callFrame struct {
	FrameID       string `json:"frame_id,omitempty"`
	ParentFrameID string `json:"parent_frame_id,omitempty"`
	Event         string `json:"event"`
	Depth         int    `json:"depth"`
	Type          string `json:"type,omitempty"`
	From          string `json:"from,omitempty"`
	To            string `json:"to,omitempty"`
	Input         string `json:"input,omitempty"`
	Gas           uint64 `json:"gas,omitempty"`
	Value         string `json:"value,omitempty"`
	GasUsed       uint64 `json:"gas_used,omitempty"`
	Output        string `json:"output,omitempty"`
	Error         string `json:"error,omitempty"`
	Reverted      bool   `json:"reverted,omitempty"`
}

type opcodeEvent struct {
	FrameID            string   `json:"frame_id,omitempty"`
	Caller             string   `json:"caller,omitempty"`
	Address            string   `json:"address,omitempty"`
	CallValue          string   `json:"call_value,omitempty"`
	CallInput          string   `json:"call_input,omitempty"`
	Code               string   `json:"code,omitempty"`
	Value              string   `json:"value,omitempty"`
	PC                 uint64   `json:"pc"`
	Op                 string   `json:"op"`
	Gas                uint64   `json:"gas"`
	Cost               uint64   `json:"cost"`
	Depth              int      `json:"depth"`
	StackTop           []string `json:"stack_top,omitempty"`
	Stack              []string `json:"stack,omitempty"`
	Memory             string   `json:"memory,omitempty"`
	ReturnData         string   `json:"return_data,omitempty"`
	ReturnDataSource   string   `json:"return_data_source_frame,omitempty"`
	MemoryAtCallOffset string   `json:"memory_at_call_offset,omitempty"`
	Error              string   `json:"error,omitempty"`
	StorageContext     string   `json:"storage_context,omitempty"`
	StorageSlot        string   `json:"storage_slot,omitempty"`
	StorageValue       string   `json:"storage_value,omitempty"`
	CallTraceIndex     int      `json:"call_trace_index,omitempty"`
}

func targetLogs(all []*types.Log, prefixCount int) []*types.Log {
	if prefixCount < 0 || prefixCount > len(all) {
		return nil
	}
	return append([]*types.Log(nil), all[prefixCount:]...)
}

func logsEqual(left, right []*types.Log) bool {
	if len(left) != len(right) {
		return false
	}
	for i := range left {
		if left[i] == nil || right[i] == nil {
			if left[i] != right[i] {
				return false
			}
			continue
		}
		if left[i].Address != right[i].Address ||
			!slices.Equal(left[i].Topics, right[i].Topics) ||
			!slices.Equal(left[i].Data, right[i].Data) {
			return false
		}
	}
	return true
}

func postStateMatches(st *state.StateDB, pre, post map[string]postStateAccount, guard ...*authenticatedReadGuard) bool {
	for rawAddress, expected := range post {
		address := common.HexToAddress(rawAddress)
		if expected.Balance != "" && st.GetBalance(address).ToBig().Cmp(quantity(expected.Balance)) != 0 {
			return false
		}
		if expected.Nonce != "" {
			if quantity(expected.Nonce).Uint64() != st.GetNonce(address) {
				return false
			}
		}
		if expected.Code != "" {
			code, err := hexutil.Decode(expected.Code)
			if err != nil || !slices.Equal(code, st.GetCode(address)) {
				return false
			}
		}
		for rawSlot, rawValue := range expected.Storage {
			if st.GetState(address, common.HexToHash(rawSlot)) != common.HexToHash(rawValue) {
				return false
			}
		}
	}
	// In diffMode, a pre-state storage cell absent from post means the cell
	// was cleared. Verify that clear explicitly instead of treating post as a
	// complete snapshot.
	for rawAddress, before := range pre {
		address := common.HexToAddress(rawAddress)
		after, accountPresent := post[rawAddress]
		if !accountPresent {
			if len(guard) == 0 || !guard[0].validSameTxDeletion(address) || st.Exist(address) {
				return false
			}
			continue
		}
		for rawSlot := range before.Storage {
			if _, retained := after.Storage[rawSlot]; !retained && st.GetState(address, common.HexToHash(rawSlot)) != (common.Hash{}) {
				return false
			}
		}
	}
	return true
}

func newCallHooks(compact bool) (*tracing.Hooks, *[]callFrame, *string, *[]balanceChange, *[]storageChange, *[]*types.Log, *[]opcodeEvent) {
	frames := make([]callFrame, 0)
	revertData := ""
	balanceChanges := make([]balanceChange, 0)
	storageChanges := make([]storageChange, 0)
	logs := make([]*types.Log, 0)
	opcodes := make([]opcodeEvent, 0)
	frameIndexByDepth := make(map[int]int)
	frameIDByDepth := make(map[int]string)
	pendingReturnData := make(map[string]struct {
		data   string
		source string
	})
	nextFrameID := 0
	seenFrame := make(map[string]bool)
	hooks := &tracing.Hooks{
		OnEnter: func(depth int, typ byte, from common.Address, to common.Address, input []byte, gas uint64, value *big.Int) {
			nextFrameID++
			frameID := fmt.Sprintf("f%06d", nextFrameID)
			frameIDByDepth[depth] = frameID
			frameIndexByDepth[depth] = len(frames)
			frames = append(frames, callFrame{FrameID: frameID, ParentFrameID: frameIDByDepth[depth-1], Event: "enter", Depth: depth,
				Type: vm.OpCode(typ).String(), From: from.Hex(), To: to.Hex(),
				Input: hexutil.Encode(input), Gas: gas, Value: value.String()})
		},
		OnExit: func(depth int, output []byte, gasUsed uint64, err error, reverted bool) {
			frame := callFrame{FrameID: frameIDByDepth[depth], Event: "exit", Depth: depth, GasUsed: gasUsed,
				Output: hexutil.Encode(output), Reverted: reverted}
			if err != nil {
				frame.Error = err.Error()
			}
			if depth == 0 && reverted && len(output) > 0 {
				revertData = hexutil.Encode(output)
			}
			if depth > 0 {
				if parent := frameIDByDepth[depth-1]; parent != "" {
					pendingReturnData[parent] = struct{ data, source string }{data: hexutil.Encode(output), source: frameIDByDepth[depth]}
				}
			}
			frames = append(frames, frame)
			delete(frameIndexByDepth, depth)
			delete(frameIDByDepth, depth)
		},
		OnBalanceChange: func(addr common.Address, previous, current *big.Int, _ tracing.BalanceChangeReason) {
			balanceChanges = append(balanceChanges, balanceChange{Address: addr.Hex(), Previous: previous.String(), Current: current.String()})
		},
		OnStorageChange: func(addr common.Address, slot common.Hash, previous, current common.Hash) {
			storageChanges = append(storageChanges, storageChange{Address: addr.Hex(), Slot: slot.Hex(), Previous: previous.Hex(), Current: current.Hex()})
		},
		OnLog: func(log *types.Log) { logs = append(logs, log) },
	}
	hooks.OnOpcode = func(pc uint64, op byte, gas, cost uint64, scope tracing.OpContext, data []byte, depth int, err error) {
		e := opcodeEvent{PC: pc, Op: vm.OpCode(op).String(), Gas: gas, Cost: cost, Depth: depth}
		// Geth reports opcode depth one level inside the frame passed to
		// OnEnter. Prefer that parent frame; retain the direct lookup for
		// tracers/configurations that report identical depths.
		if idx, ok := frameIndexByDepth[depth-1]; ok && depth > 0 {
			e.CallTraceIndex = idx
			e.FrameID = frameIDByDepth[depth-1]
		} else if idx, ok := frameIndexByDepth[depth]; ok {
			e.CallTraceIndex = idx
			e.FrameID = frameIDByDepth[depth]
		}
		if pending, ok := pendingReturnData[e.FrameID]; ok {
			e.ReturnData = pending.data
			e.ReturnDataSource = pending.source
			delete(pendingReturnData, e.FrameID)
		}
		if scope != nil {
			e.Caller = scope.Caller().Hex()
			e.Address = scope.Address().Hex()
			e.CallValue = scope.CallValue().Hex()
			if !seenFrame[e.FrameID] && len(scope.ContractCode()) > 0 {
				e.Code = hexutil.Encode(scope.ContractCode())
			}
			if !compact || !seenFrame[e.FrameID] {
				e.CallInput = hexutil.Encode(scope.CallInput())
				seenFrame[e.FrameID] = true
			}
			e.StorageContext = scope.Address().Hex()
			if op >= byte(vm.PUSH1) && op <= byte(vm.PUSH32) {
				size := int(op-byte(vm.PUSH1)) + 1
				code := scope.ContractCode()
				start := pc + 1
				if start+uint64(size) <= uint64(len(code)) {
					e.Value = hexutil.Encode(code[start : start+uint64(size)])
				}
			}
			switch vm.OpCode(op) {
			case vm.CODESIZE:
				e.Value = fmt.Sprintf("0x%x", len(scope.ContractCode()))
			case vm.CALLDATASIZE:
				e.Value = fmt.Sprintf("0x%x", len(scope.CallInput()))
			case vm.RETURNDATASIZE:
				e.Value = fmt.Sprintf("0x%x", len(data))
			}
			stack := scope.StackData()
			for _, v := range stack {
				e.Stack = append(e.Stack, v.String())
			}
			start := len(stack) - 8
			if start < 0 {
				start = 0
			}
			for _, v := range stack[start:] {
				e.StackTop = append(e.StackTop, v.String())
			}
			if vm.OpCode(op) == vm.SLOAD && len(stack) >= 1 {
				e.StorageSlot = stack[len(stack)-1].String()
			}
			if vm.OpCode(op) == vm.SSTORE && len(stack) >= 2 {
				e.StorageValue = stack[len(stack)-2].String()
				e.StorageSlot = stack[len(stack)-1].String()
			}
			mem := scope.MemoryData()
			if !compact && len(mem) > 0 && (vm.OpCode(op) == vm.MLOAD || vm.OpCode(op) == vm.MSTORE || vm.OpCode(op) == vm.MSTORE8 || vm.OpCode(op) == vm.CALL || vm.OpCode(op) == vm.CALLCODE || vm.OpCode(op) == vm.DELEGATECALL || vm.OpCode(op) == vm.STATICCALL || vm.OpCode(op) == vm.RETURNDATACOPY) {
				e.Memory = hexutil.Encode(mem)
			}
			if (vm.OpCode(op) == vm.STATICCALL || vm.OpCode(op) == vm.CALL || vm.OpCode(op) == vm.CALLCODE || vm.OpCode(op) == vm.DELEGATECALL) && len(stack) >= 5 {
				offset := stack[len(stack)-4].Uint64()
				if vm.OpCode(op) == vm.CALL || vm.OpCode(op) == vm.CALLCODE {
					offset = stack[len(stack)-4].Uint64()
				}
				if offset+32 <= uint64(len(mem)) {
					e.MemoryAtCallOffset = hexutil.Encode(mem[offset : offset+32])
				}
			}
		}
		if err != nil {
			e.Error = err.Error()
		}
		if len(opcodes) >= 1000000 {
			opcodes = opcodes[1:]
		}
		opcodes = append(opcodes, e)
	}
	return hooks, &frames, &revertData, &balanceChanges, &storageChanges, &logs, &opcodes
}

type authenticatedReadGuard struct {
	accounts         map[common.Address]map[common.Hash]struct{}
	emptyStorage     map[common.Address]bool
	storageRootKnown map[common.Address]bool
	absent           map[common.Address]struct{}
	created          map[common.Address]struct{}
	written          map[common.Address]map[common.Hash]struct{}
	violated         bool
	reasons          []string
	Failures         []readFailure
	txIndex          int
	createdTx        map[common.Address]int
	destructTx       map[common.Address]int
	deletionEligible map[common.Address]int
}

type readFailure struct {
	Phase                 string `json:"phase"`
	Method                string `json:"method"`
	TxIndex               int    `json:"tx_index"`
	PC                    uint64 `json:"pc"`
	Depth                 int    `json:"depth"`
	StorageContextAddress string `json:"storage_context_address"`
	Opcode                string `json:"opcode"`
	Slot                  string `json:"slot,omitempty"`
	Reason                string `json:"reason"`
}

type mutationApplication struct {
	Kind            string `json:"kind"`
	Address         string `json:"address,omitempty"`
	Source          string `json:"source,omitempty"`
	Slot            string `json:"slot,omitempty"`
	TargetIndex     int    `json:"target_index"`
	PrefixCompleted int    `json:"prefix_completed"`
	Before          string `json:"before"`
	After           string `json:"after"`
}

// authenticatedStateDB prevents Geth's transaction precheck and
// PreExecution paths from silently observing sparse-state defaults. Opcode
// hooks run too late to protect those reads, so unknown historical state is a
// typed abort at the vm.StateDB boundary.
type authenticatedStateDB struct {
	vm.StateDB
	guard *authenticatedReadGuard
}

type unauthenticatedStateRead struct {
	Phase   string
	Method  string
	Address common.Address
	Slot    *common.Hash
	Detail  string
}

func (e unauthenticatedStateRead) Error() string {
	if e.Detail != "" {
		return "unauthenticated state read: " + e.Detail
	}
	if e.Slot != nil {
		return fmt.Sprintf("unauthenticated state read: %s %s:%s", e.Method, e.Address.Hex(), e.Slot.Hex())
	}
	return fmt.Sprintf("unauthenticated state read: %s %s", e.Method, e.Address.Hex())
}

func (g *authenticatedReadGuard) recordBoundaryFailure(err unauthenticatedStateRead) {
	g.violated = true
	g.reasons = append(g.reasons, err.Error())
	phase := err.Phase
	if phase == "" {
		phase = "state-boundary"
	}
	failure := readFailure{Phase: phase, Method: err.Method, TxIndex: g.txIndex,
		StorageContextAddress: err.Address.Hex(), Reason: err.Error()}
	if err.Slot != nil {
		failure.Slot = err.Slot.Hex()
	}
	g.Failures = append(g.Failures, failure)
}

func (s *authenticatedStateDB) requireAccount(method string, addr common.Address) {
	if _, ok := s.guard.accounts[addr]; ok {
		return
	}
	if _, ok := s.guard.created[addr]; ok {
		return
	}
	panic(unauthenticatedStateRead{Phase: "state-boundary", Method: method,
		Address: addr, Detail: fmt.Sprintf("%s account %s", method, addr.Hex())})
}

func (s *authenticatedStateDB) GetBalance(addr common.Address) *uint256.Int {
	s.requireAccount("GetBalance", addr)
	return s.StateDB.GetBalance(addr)
}
func (s *authenticatedStateDB) GetNonce(addr common.Address) uint64 {
	s.requireAccount("GetNonce", addr)
	return s.StateDB.GetNonce(addr)
}
func (s *authenticatedStateDB) GetCode(addr common.Address) []byte {
	s.requireAccount("GetCode", addr)
	return s.StateDB.GetCode(addr)
}
func (s *authenticatedStateDB) GetCodeHash(addr common.Address) common.Hash {
	s.requireAccount("GetCodeHash", addr)
	return s.StateDB.GetCodeHash(addr)
}
func (s *authenticatedStateDB) GetCodeSize(addr common.Address) int {
	s.requireAccount("GetCodeSize", addr)
	return s.StateDB.GetCodeSize(addr)
}
func (s *authenticatedStateDB) Exist(addr common.Address) bool {
	s.requireAccount("Exist", addr)
	return s.StateDB.Exist(addr)
}
func (s *authenticatedStateDB) Empty(addr common.Address) bool {
	s.requireAccount("Empty", addr)
	return s.StateDB.Empty(addr)
}
func (s *authenticatedStateDB) GetState(addr common.Address, slot common.Hash) common.Hash {
	s.requireAccount("GetState", addr)
	if slots, ok := s.guard.accounts[addr]; ok {
		if _, proven := slots[slot]; !proven && !s.guard.emptyStorage[addr] && s.guard.storageRootKnown[addr] {
			panic(unauthenticatedStateRead{Phase: "state-boundary", Method: "GetState",
				Address: addr, Slot: &slot})
		}
	}
	return s.StateDB.GetState(addr, slot)
}
func (s *authenticatedStateDB) GetStateAndCommittedState(addr common.Address, slot common.Hash) (common.Hash, common.Hash) {
	return s.GetState(addr, slot), func() common.Hash {
		_, committed := s.StateDB.GetStateAndCommittedState(addr, slot)
		return committed
	}()
}

func (s *authenticatedStateDB) requireSlot(method string, addr common.Address, slot common.Hash) {
	s.requireAccount(method, addr)
	if _, dynamic := s.guard.created[addr]; dynamic {
		if s.guard.storageRootKnown[addr] && !s.guard.emptyStorage[addr] {
			if _, proven := s.guard.accounts[addr][slot]; !proven {
				if _, written := s.guard.written[addr][slot]; !written {
					panic(unauthenticatedStateRead{Phase: "state-boundary", Method: method,
						Address: addr, Slot: &slot})
				}
			}
		}
		return
	}
	if !s.guard.emptyStorage[addr] && s.guard.storageRootKnown[addr] {
		if _, proven := s.guard.accounts[addr][slot]; !proven {
			panic(unauthenticatedStateRead{Phase: "state-boundary", Method: method,
				Address: addr, Slot: &slot})
		}
	}
}

func (s *authenticatedStateDB) AddBalance(addr common.Address, amount *uint256.Int, reason tracing.BalanceChangeReason) uint256.Int {
	s.requireAccount("AddBalance", addr)
	return s.StateDB.AddBalance(addr, amount, reason)
}
func (s *authenticatedStateDB) SubBalance(addr common.Address, amount *uint256.Int, reason tracing.BalanceChangeReason) uint256.Int {
	s.requireAccount("SubBalance", addr)
	return s.StateDB.SubBalance(addr, amount, reason)
}
func (s *authenticatedStateDB) SetNonce(addr common.Address, nonce uint64, reason tracing.NonceChangeReason) {
	s.requireAccount("SetNonce", addr)
	s.StateDB.SetNonce(addr, nonce, reason)
}
func (s *authenticatedStateDB) SetCode(addr common.Address, code []byte, reason tracing.CodeChangeReason) []byte {
	s.requireAccount("SetCode", addr)
	return s.StateDB.SetCode(addr, code, reason)
}
func (s *authenticatedStateDB) SetState(addr common.Address, slot, value common.Hash) common.Hash {
	s.requireSlot("SetState", addr, slot)
	return s.StateDB.SetState(addr, slot, value)
}
func (s *authenticatedStateDB) CreateAccount(addr common.Address) {
	s.requireAccount("CreateAccount", addr)
	s.StateDB.CreateAccount(addr)
}
func (s *authenticatedStateDB) CreateContract(addr common.Address) {
	s.requireAccount("CreateContract", addr)
	s.StateDB.CreateContract(addr)
}
func (s *authenticatedStateDB) SelfDestruct(addr common.Address) {
	s.requireAccount("SelfDestruct", addr)
	s.guard.destructTx[addr] = s.guard.txIndex
	if s.StateDB.IsNewContract(addr) {
		s.guard.deletionEligible[addr] = s.guard.txIndex
	}
	s.StateDB.SelfDestruct(addr)
}
func (s *authenticatedStateDB) Touch(addr common.Address) {
	s.requireAccount("Touch", addr)
	s.StateDB.Touch(addr)
}

func applyTransactionGuarded(evm *vm.EVM, gasPool *core.GasPool, st *state.StateDB, header *types.Header, tx *types.Transaction, guard *authenticatedReadGuard) (receipt *types.Receipt, access *bal.ConstructionBlockAccessList, err error) {
	defer func() {
		if recovered := recover(); recovered != nil {
			if violation, ok := recovered.(unauthenticatedStateRead); ok {
				guard.recordBoundaryFailure(violation)
				err = violation
				return
			}
			panic(recovered)
		}
	}()
	return core.ApplyTransaction(evm, gasPool, st, header, tx)
}

func applyMessageGuarded(evm *vm.EVM, gasPool *core.GasPool, st *state.StateDB, header *types.Header, tx *types.Transaction, msg *core.Message, guard *authenticatedReadGuard) (receipt *types.Receipt, access *bal.ConstructionBlockAccessList, err error) {
	defer func() {
		if recovered := recover(); recovered != nil {
			if violation, ok := recovered.(unauthenticatedStateRead); ok {
				guard.recordBoundaryFailure(violation)
				err = violation
				return
			}
			panic(recovered)
		}
	}()
	return core.ApplyTransactionWithEVM(msg, gasPool, st, header.Number, header.Hash(), header.Time, tx, evm)
}

func preExecutionGuarded(evm *vm.EVM, parentBeaconRoot *common.Hash, parent *types.Header, config *params.ChainConfig, number *big.Int, timestamp uint64, guard *authenticatedReadGuard) (err error) {
	defer func() {
		if recovered := recover(); recovered != nil {
			if violation, ok := recovered.(unauthenticatedStateRead); ok {
				guard.recordBoundaryFailure(violation)
				err = violation
				return
			}
			panic(recovered)
		}
	}()
	core.PreExecution(stdcontext.Background(), parentBeaconRoot, parent, config, evm, number, timestamp)
	return nil
}

func isUnauthenticatedStateError(err error) bool {
	var violation unauthenticatedStateRead
	return errors.As(err, &violation)
}

func newAuthenticatedReadGuard(initial AuthenticatedInitialState) *authenticatedReadGuard {
	guard := &authenticatedReadGuard{accounts: make(map[common.Address]map[common.Hash]struct{}), emptyStorage: make(map[common.Address]bool), storageRootKnown: make(map[common.Address]bool), absent: make(map[common.Address]struct{}), created: make(map[common.Address]struct{}), written: make(map[common.Address]map[common.Hash]struct{}), createdTx: make(map[common.Address]int), destructTx: make(map[common.Address]int), deletionEligible: make(map[common.Address]int)}
	for rawAddress, account := range initial.Accounts {
		address := common.HexToAddress(rawAddress)
		slots := make(map[common.Hash]struct{}, len(account.Storage))
		for rawSlot := range account.Storage {
			slots[common.HexToHash(rawSlot)] = struct{}{}
		}
		guard.accounts[address] = slots
		if account.StorageRoot != "" && strings.EqualFold(account.StorageRoot, types.EmptyRootHash.Hex()) {
			guard.emptyStorage[address] = true
		}
		if account.StorageRoot != "" {
			guard.storageRootKnown[address] = true
		}
		if account.Exists != nil && !*account.Exists {
			guard.absent[address] = struct{}{}
		}
	}
	return guard
}

func (g *authenticatedReadGuard) onCodeChange(address common.Address, _ common.Hash, _ []byte, _ common.Hash, code []byte) {
	// Geth supplies the resulting address and successful code materialization;
	// fork-specific CREATE/CREATE2 collision rules remain Geth's authority.
	if _, absent := g.absent[address]; absent && len(code) > 0 {
		g.created[address] = struct{}{}
		g.createdTx[address] = g.txIndex
		g.accounts[address] = make(map[common.Hash]struct{})
	}
}

func (g *authenticatedReadGuard) validSameTxDeletion(address common.Address) bool {
	_, initiallyAbsent := g.absent[address]
	destructed, destructedOK := g.destructTx[address]
	eligible, eligibleOK := g.deletionEligible[address]
	return initiallyAbsent && eligibleOK && destructedOK && eligible == destructed
}

func (g *authenticatedReadGuard) allowSyntheticCode(address common.Address) {
	if !isReservedSyntheticAddress(address) {
		g.violated = true
		g.reasons = append(g.reasons, fmt.Sprintf("synthetic-code-address-not-reserved:%s", address.Hex()))
		return
	}
	if _, known := g.accounts[address]; !known {
		g.violated = true
		g.reasons = append(g.reasons, fmt.Sprintf("synthetic-code-address-not-proof-bound:%s", address.Hex()))
		return
	}
	if _, absent := g.absent[address]; !absent {
		g.violated = true
		g.reasons = append(g.reasons, fmt.Sprintf("synthetic-code-address-not-proven-absent:%s", address.Hex()))
		return
	}
	// The absent account was authenticated at b-1. Its code may now be
	// installed as a synthetic shadow at the target boundary.
	g.created[address] = struct{}{}
}

func isReservedSyntheticAddress(address common.Address) bool {
	return address == common.HexToAddress("0x000000000000000000000000000000000000f1a1") ||
		address == common.HexToAddress("0x000000000000000000000000000000000000f1a2") ||
		address == common.HexToAddress("0x000000000000000000000000000000000000f1a3")
}

func (g *authenticatedReadGuard) onEnter(_ int, typ byte, _ common.Address, to common.Address, _ []byte, _ uint64, _ *big.Int) {
	if vm.OpCode(typ) != vm.CREATE && vm.OpCode(typ) != vm.CREATE2 {
		return
	}
	if _, authenticated := g.accounts[to]; !authenticated {
		g.violated = true
		g.reasons = append(g.reasons, fmt.Sprintf("%s:destination-not-proof-bound:%s", vm.OpCode(typ), to.Hex()))
		return
	}
	// Geth remains authoritative for nonce/code/storage collision semantics.
	// Preserve any authenticated historical storage for prefunded destinations;
	// a newly created account may retain that storage under the active fork.
	g.created[to] = struct{}{}
}

func (g *authenticatedReadGuard) checkAccount(address common.Address) {
	if _, ok := g.accounts[address]; !ok {
		g.violated = true
		g.reasons = append(g.reasons, fmt.Sprintf("account:%s", address.Hex()))
	}
}

func (g *authenticatedReadGuard) recordFailure(txIndex int, pc uint64, depth int, address common.Address, op vm.OpCode, slot *common.Hash, reason string) {
	failure := readFailure{TxIndex: txIndex, PC: pc, Depth: depth,
		StorageContextAddress: address.Hex(), Opcode: op.String(), Reason: reason}
	if slot != nil {
		failure.Slot = slot.Hex()
	}
	g.Failures = append(g.Failures, failure)
}

func (g *authenticatedReadGuard) onOpcode(pc uint64, op byte, _ uint64, _ uint64, scope tracing.OpContext, _ []byte, depth int, _ error) {
	if scope == nil {
		g.violated = true
		g.reasons = append(g.reasons, "opcode:nil-scope")
		return
	}
	stack := scope.StackData()
	switch vm.OpCode(op) {
	case vm.SLOAD, vm.SSTORE:
		if len(stack) < 1 {
			g.violated = true
			g.reasons = append(g.reasons, fmt.Sprintf("%s:short-stack", vm.OpCode(op)))
			return
		}
		slots, ok := g.accounts[scope.Address()]
		if !ok {
			g.violated = true
			g.reasons = append(g.reasons, fmt.Sprintf("%s:account:%s", vm.OpCode(op), scope.Address().Hex()))
			return
		}
		if _, dynamic := g.created[scope.Address()]; dynamic {
			slot := common.BytesToHash(stack[len(stack)-1].Bytes())
			if vm.OpCode(op) == vm.SSTORE {
				if g.storageRootKnown[scope.Address()] && !g.emptyStorage[scope.Address()] {
					if _, proven := slots[slot]; !proven {
						g.violated = true
						reason := fmt.Sprintf("SSTORE:dynamic-unproven-slot:%s:%s", scope.Address().Hex(), slot.Hex())
						g.reasons = append(g.reasons, reason)
						g.recordFailure(g.txIndex, pc, depth, scope.Address(), vm.SSTORE, &slot, reason)
						return
					}
				}
				if g.written[scope.Address()] == nil {
					g.written[scope.Address()] = make(map[common.Hash]struct{})
				}
				g.written[scope.Address()][slot] = struct{}{}
			}
			if !g.storageRootKnown[scope.Address()] || g.emptyStorage[scope.Address()] {
				return
			}
			if _, ok := slots[slot]; ok {
				return
			}
			if _, ok := g.written[scope.Address()][slot]; ok {
				return
			}
			g.violated = true
			slot = common.BytesToHash(stack[len(stack)-1].Bytes())
			reason := fmt.Sprintf("%s:dynamic-unproven-slot:%s:%s", vm.OpCode(op), scope.Address().Hex(), slot.Hex())
			g.reasons = append(g.reasons, reason)
			g.recordFailure(g.txIndex, pc, depth, scope.Address(), vm.OpCode(op), &slot, reason)
			return
		}
		if _, ok := slots[common.BytesToHash(stack[len(stack)-1].Bytes())]; !ok {
			g.violated = true
			slot := common.BytesToHash(stack[len(stack)-1].Bytes())
			reason := fmt.Sprintf("%s:account:%s:slot:%s", vm.OpCode(op), scope.Address().Hex(), slot.Hex())
			g.reasons = append(g.reasons, reason)
			g.recordFailure(g.txIndex, pc, depth, scope.Address(), vm.OpCode(op), &slot, reason)
		}
	case vm.SELFBALANCE:
		g.checkAccount(scope.Address())
	case vm.BALANCE, vm.EXTCODESIZE, vm.EXTCODEHASH:
		if len(stack) < 1 {
			g.violated = true
			return
		}
		g.checkAccount(common.BytesToAddress(stack[len(stack)-1].Bytes()))
	case vm.EXTCODECOPY:
		if len(stack) < 4 {
			g.violated = true
			return
		}
		// EXTCODECOPY pops address first; StackData is bottom-to-top, so
		// address is the top item.  The other three operands are memory/code
		// offsets and length (using len-4 falsely turns length into an address).
		g.checkAccount(common.BytesToAddress(stack[len(stack)-1].Bytes()))
	case vm.CALL, vm.CALLCODE:
		if len(stack) < 2 {
			g.violated = true
			return
		}
		// StackData is ordered bottom-to-top. CALL pops gas first, then
		// the destination address.
		g.checkAccount(common.BytesToAddress(stack[len(stack)-2].Bytes()))
	case vm.DELEGATECALL, vm.STATICCALL:
		if len(stack) < 2 {
			g.violated = true
			return
		}
		// DELEGATECALL and STATICCALL also pop gas before destination.
		g.checkAccount(common.BytesToAddress(stack[len(stack)-2].Bytes()))
	case vm.EXTDELEGATECALL, vm.EXTSTATICCALL:
		// EOF external-call opcodes have fork-specific stack semantics. Until
		// their operand layout is explicitly modeled, fail closed.
		g.violated = true
	case vm.CREATE, vm.CREATE2:
		// Successful creation is observed through onCodeChange. Do not
		// independently reimplement fork-specific collision semantics.
	case vm.SELFDESTRUCT:
		if len(stack) < 1 {
			g.violated = true
			return
		}
		g.checkAccount(common.BytesToAddress(stack[len(stack)-1].Bytes()))
	}
}

type stringListFlag []string

func (f *stringListFlag) String() string { return strings.Join(*f, ",") }
func (f *stringListFlag) Set(value string) error {
	*f = append(*f, value)
	return nil
}

type output struct {
	Mode                       string                `json:"mode"`
	ReplayMode                 string                `json:"replay_mode"`
	ChainRules                 map[string]any        `json:"chain_rules"`
	BlockNumber                string                `json:"block_number"`
	Results                    []result              `json:"per_tx"`
	TotalGas                   uint64                `json:"total_actual_gas"`
	TotalExpect                uint64                `json:"total_expected_gas"`
	AllGasMatch                bool                  `json:"all_gas_match"`
	AllStatus                  bool                  `json:"all_status_match"`
	AllLogsMatch               bool                  `json:"all_logs_match"`
	IsolatedGate               bool                  `json:"isolated_baseline_gate"`
	StateRoot                  string                `json:"state_root_actual"`
	ExpectedRoot               string                `json:"state_root_expected"`
	StateRootMatch             bool                  `json:"state_root_match"`
	PrestateProofVerified      bool                  `json:"prestate_proof_verified"`
	ProofAccounts              int                   `json:"proof_accounts_verified"`
	ProofStorage               int                   `json:"proof_storage_cells_verified"`
	TargetIndex                int                   `json:"target_index"`
	PrefixGasMatch             bool                  `json:"prefix_gas_match"`
	Mutation                   bool                  `json:"mutation"`
	MutationNote               string                `json:"mutation_note,omitempty"`
	Acceptance                 bool                  `json:"acceptance_gate"`
	BlockContextComplete       bool                  `json:"block_context_complete"`
	PreExecutionApplied        bool                  `json:"pre_execution_applied"`
	PostStateEvidenceAvailable bool                  `json:"post_state_evidence_available"`
	RelevantPostStateMatch     bool                  `json:"relevant_post_state_match"`
	ReadGuardReasons           []string              `json:"authenticated_read_failures,omitempty"`
	ReadFailures               []readFailure         `json:"authenticated_read_failure_details,omitempty"`
	MutationApplication        []mutationApplication `json:"mutation_application,omitempty"`
	DroppedIndices             []int                 `json:"dropped_indices,omitempty"`
	OrderingIntervention       *orderingReport       `json:"ordering_intervention,omitempty"`
	Timing                     replayTiming          `json:"timing_ms"`
	Note                       string                `json:"note"`
}

type chainContext struct {
	header   *types.Header
	byNumber map[uint64]*types.Header
	byHash   map[common.Hash]*types.Header
	config   *params.ChainConfig
	complete bool
}

func (c chainContext) Engine() consensus.Engine { return nil }

func (c chainContext) CurrentHeader() *types.Header { return c.header }

func (c chainContext) GetHeader(hash common.Hash, number uint64) *types.Header {
	if header, ok := c.byNumber[number]; ok {
		if hash != (common.Hash{}) && header.Hash() != hash {
			return nil
		}
		return header
	}
	if c.header != nil && c.header.Number.Uint64() == number {
		if hash != (common.Hash{}) && c.header.Hash() != hash {
			return nil
		}
		return c.header
	}
	return nil
}

func (c chainContext) GetHeaderByHash(hash common.Hash) *types.Header {
	if header, ok := c.byHash[hash]; ok {
		return header
	}
	if c.header != nil && c.header.Hash() == hash {
		return c.header
	}
	return nil
}

func (c chainContext) GetHeaderByNumber(number uint64) *types.Header {
	return c.GetHeader(common.Hash{}, number)
}

func validateAncestorHeaders(current *types.Header, ancestors []types.Header) error {
	if len(ancestors) > 256 {
		return fmt.Errorf("ancestor context contains %d headers; maximum is 256", len(ancestors))
	}
	seenNumbers := make(map[uint64]common.Hash, len(ancestors)+1)
	seenHashes := make(map[common.Hash]uint64, len(ancestors)+1)
	register := func(header *types.Header) error {
		number := header.Number.Uint64()
		hash := header.Hash()
		if previous, ok := seenNumbers[number]; ok && previous != hash {
			return fmt.Errorf("conflicting hashes for block %d", number)
		}
		if previous, ok := seenHashes[hash]; ok && previous != number {
			return fmt.Errorf("hash %s maps to multiple block numbers", hash.Hex())
		}
		seenNumbers[number] = hash
		seenHashes[hash] = number
		return nil
	}
	if err := register(current); err != nil {
		return err
	}
	for i := range ancestors {
		header := &ancestors[i]
		if header.Number == nil || header.Number.Sign() < 0 || header.Number.Uint64() >= current.Number.Uint64() {
			return fmt.Errorf("invalid ancestor number at index %d", i)
		}
		if err := register(header); err != nil {
			return err
		}
		expected := current.Number.Uint64() - uint64(i) - 1
		if header.Number.Uint64() != expected {
			return fmt.Errorf("ancestor index %d has block %d; expected %d", i, header.Number.Uint64(), expected)
		}
		if i == 0 {
			if current.ParentHash != header.Hash() {
				return fmt.Errorf("current parent hash does not match ancestor[0]")
			}
		} else if ancestors[i-1].ParentHash != header.Hash() {
			return fmt.Errorf("broken ancestor linkage at index %d", i)
		}
	}
	return nil
}

func hasCompleteAncestorCoverage(current *types.Header, ancestors []types.Header) bool {
	if current == nil || current.Number == nil {
		return false
	}
	required := current.Number.Uint64()
	if required > 256 {
		required = 256
	}
	return uint64(len(ancestors)) == required
}

func loadChainContext(path string, current *types.Header, config *params.ChainConfig) (chainContext, error) {
	context := chainContext{header: current, byNumber: map[uint64]*types.Header{}, byHash: map[common.Hash]*types.Header{}, config: config}
	context.byNumber[current.Number.Uint64()] = current
	context.byHash[current.Hash()] = current
	var ancestors []types.Header
	if err := readJSON(path, &ancestors); err != nil {
		if os.IsNotExist(err) {
			return context, nil
		}
		return context, err
	}
	if err := validateAncestorHeaders(current, ancestors); err != nil {
		return context, err
	}
	context.complete = hasCompleteAncestorCoverage(current, ancestors)
	for i := range ancestors {
		header := &ancestors[i]
		context.byNumber[header.Number.Uint64()] = header
		context.byHash[header.Hash()] = header
	}
	return context, nil
}

func (c chainContext) Config() *params.ChainConfig { return c.config }

func readJSON(path string, out any) error {
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(b, out)
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func quantity(s string) *big.Int {
	s = strings.TrimSpace(s)
	if s == "" || s == "0x" {
		return new(big.Int)
	}
	n := new(big.Int)
	if strings.HasPrefix(s, "0x") {
		n.SetString(s[2:], 16)
	} else {
		n.SetString(s, 10)
	}
	return n
}

func makeState(initial AuthenticatedInitialState) (*state.StateDB, error) {
	disk := rawdb.NewMemoryDatabase()
	trie := triedb.NewDatabase(disk, nil)
	db := state.NewDatabase(trie, nil)
	st, err := state.New(types.EmptyRootHash, db)
	if err != nil {
		return nil, err
	}
	for address, a := range initial.Accounts {
		addr := common.HexToAddress(address)
		if a.Exists != nil && !*a.Exists {
			// Do not materialize an authenticated absent account.  In particular,
			// EIP-7702 applies a different refund when the authority existed at
			// transaction start, so CreateAccount here would change gas semantics.
			continue
		}
		st.CreateAccount(addr)
		st.SetNonce(addr, a.Nonce, tracing.NonceChangeUnspecified)
		st.SetBalance(addr, uint256.MustFromBig(quantity(a.Balance)), tracing.BalanceChangeUnspecified)
		if a.Code != "" && a.Code != "0x" {
			code, err := hexutil.Decode(a.Code)
			if err != nil {
				return nil, err
			}
			st.SetCode(addr, code, tracing.CodeChangeUnspecified)
		}
		for slot, value := range a.Storage {
			st.SetState(addr, common.HexToHash(slot), common.HexToHash(value))
		}
	}
	// SSTORE gas/refund rules depend on the committed/original storage value,
	// not only on StateDB's dirty overlay.  Commit the injected snapshot and
	// reopen it so the EVM sees these values as historical state.
	root, err := st.Commit(0, false, false)
	if err != nil {
		return nil, err
	}
	return state.New(root, db)
}

func requirePreExecutionAccounts(initial AuthenticatedInitialState, header, parent *types.Header, config *params.ChainConfig) error {
	requiresBeacon := header.ParentBeaconRoot != nil
	requiresHistory := config.IsPrague(header.Number, header.Time) || config.IsUBT(header.Number, header.Time)
	if !requiresBeacon && !requiresHistory {
		return nil
	}
	// params.SystemAddress is the synthetic caller of protocol-level
	// pre-execution and need not exist in the historical state.  Only system
	// contracts/storage that PreExecution actually reads or writes belong in
	// the authenticated initial-state requirement.
	required := make([]common.Address, 0, 2)
	if requiresBeacon {
		required = append(required, params.BeaconRootsAddress)
	}
	if requiresHistory {
		required = append(required, params.HistoryStorageAddress)
	}
	for _, address := range required {
		a, ok := initial.Accounts[strings.ToLower(address.Hex())]
		if !ok {
			return fmt.Errorf("pre-execution requires proof-bound system account %s", address.Hex())
		}
		if a.Exists != nil && !*a.Exists {
			return fmt.Errorf("pre-execution system account %s is absent", address.Hex())
		}
	}
	if requiresBeacon {
		a := initial.Accounts[strings.ToLower(params.BeaconRootsAddress.Hex())]
		if strings.ToLower(a.Code) != strings.ToLower(hexutil.Encode(params.BeaconRootsCode)) {
			return fmt.Errorf("beacon roots system code is not proof-bound")
		}
		index := header.Time % 8191
		for _, slot := range []common.Hash{
			common.BigToHash(new(big.Int).SetUint64(index)),
			common.BigToHash(new(big.Int).SetUint64(index + 8191)),
		} {
			if _, ok := a.Storage[strings.ToLower(slot.Hex())]; !ok {
				return fmt.Errorf("beacon roots slot %s is not proof-bound", slot.Hex())
			}
		}
	}
	if requiresHistory {
		a := initial.Accounts[strings.ToLower(params.HistoryStorageAddress.Hex())]
		if strings.ToLower(a.Code) != strings.ToLower(hexutil.Encode(params.HistoryStorageCode)) {
			return fmt.Errorf("history storage system code is not proof-bound")
		}
		slot := common.BigToHash(new(big.Int).SetUint64((header.Number.Uint64() - 1) % 8191)).Hex()
		if _, ok := a.Storage[strings.ToLower(slot)]; !ok {
			return fmt.Errorf("history storage slot %s is not proof-bound", slot)
		}
	}
	_ = parent
	return nil
}

func verifyPreExecutionState(st *state.StateDB, header, parent *types.Header,
	config *params.ChainConfig) error {
	if header.ParentBeaconRoot != nil {
		index := header.Time % 8191
		timestampSlot := common.BigToHash(new(big.Int).SetUint64(index))
		rootSlot := common.BigToHash(new(big.Int).SetUint64(index + 8191))
		if got := st.GetState(params.BeaconRootsAddress, rootSlot); got != *header.ParentBeaconRoot {
			return fmt.Errorf("beacon roots value write mismatch: got %s, want %s", got.Hex(), header.ParentBeaconRoot.Hex())
		}
		if got := st.GetState(params.BeaconRootsAddress, timestampSlot); got != common.BigToHash(new(big.Int).SetUint64(header.Time)) {
			return fmt.Errorf("beacon roots timestamp write mismatch: got %s, want %x", got.Hex(), header.Time)
		}
	}
	if config.IsPrague(header.Number, header.Time) || config.IsUBT(header.Number, header.Time) {
		slot := common.BigToHash(new(big.Int).SetUint64((header.Number.Uint64() - 1) % 8191))
		got := st.GetState(params.HistoryStorageAddress, slot)
		if got != parent.Hash() {
			return fmt.Errorf("history storage pre-execution write mismatch: got %s, want %s", got.Hex(), parent.Hash().Hex())
		}
	}
	return nil
}

func parseOverride(value string) (common.Address, string, error) {
	parts := strings.SplitN(value, "=", 2)
	if len(parts) != 2 {
		return common.Address{}, "", fmt.Errorf("override must be address=value: %s", value)
	}
	return common.HexToAddress(strings.TrimSpace(parts[0])), strings.TrimSpace(parts[1]), nil
}

func decodeTargetData(tx *types.Transaction, data string) ([]byte, error) {
	// TransactionToMessage preserves the original envelope metadata while
	// replacing only Message.Data, so typed transactions can use the same
	// proof-bound target-data path as legacy transactions.
	decoded, err := hexutil.Decode(data)
	if err != nil {
		return nil, err
	}
	return decoded, nil
}

func containsInt(values []int, want int) bool {
	return slices.Contains(values, want)
}

func allOccurrencesMatched(matchCount int, selected []int) bool {
	if len(selected) == 0 {
		return false
	}
	return matchCount >= selected[len(selected)-1]
}

func syntheticMessageWithData(tx *types.Transaction, signer types.Signer, baseFee *big.Int, data []byte) (*core.Message, error) {
	msg, err := core.TransactionToMessage(tx, signer, baseFee)
	if err != nil {
		return nil, err
	}
	msg.Data = append([]byte(nil), data...)
	return msg, nil
}

func main() {
	startedAt := time.Now()
	context := flag.String("context", "", "B2 context directory")
	outputPath := flag.String("output", "", "output JSON")
	listAuthorities := flag.Bool("list-authorities", false, "print recovered EIP-7702 authorities and exit")
	chainID := flag.Uint64("chain-id", mainnetChainID, "chain ID (1=Ethereum Mainnet, 43114=experimental Avalanche C-Chain)")
	proofPath := flag.String("proofs", "", "prestate_proofs.json (optional)")
	replayMode := flag.String("replay-mode", "frozen-validation", "replay mode: discovery or frozen-validation")
	extraFootprintPath := flag.String("extra-footprint", "", "JSON address -> storage-slot list discovered by a prior replay")
	targetIndex := flag.Int("target-index", -1, "target transaction index; defaults to last")
	targetData := flag.String("target-data", "", "replacement calldata for target tx")
	targetBalance := flag.String("target-balance", "", "exploratory pre-target balance override address=value")
	emitOpcodeTelemetry := flag.Bool("emit-opcode-telemetry", false, "emit full opcode provenance telemetry for the target transaction")
	compactOpcodeTelemetry := flag.Bool("compact-opcode-telemetry", false, "omit repeated full memory/calldata snapshots from opcode telemetry")
	opcodeTelemetryNDJSON := flag.String("opcode-telemetry-ndjson", "", "write target opcode telemetry as newline-delimited JSON sidecar and omit it from aggregate output")
	interventionCaller := flag.String("intervention-caller", "", "strict pre-dispatch CALL caller")
	interventionCallee := flag.String("intervention-callee", "", "strict pre-dispatch CALL callee")
	interventionSelector := flag.String("intervention-selector", "", "strict pre-dispatch CALL selector")
	interventionDepth := flag.Int("intervention-depth", -1, "strict pre-dispatch CALL depth")
	interventionType := flag.String("intervention-type", "CALL", "strict pre-dispatch call type: CALL, DELEGATECALL, or STATICCALL")
	interventionAction := flag.String("intervention-action", "", "provider-local action: revert, observe_only, substitute, substitute_passthrough, rewrite_input, rewrite_value, rewrite_input_value, callback_trampoline, or callback_trampoline_transfer")
	var interventionStoragePatch stringListFlag
	interventionOccurrence := flag.Int("intervention-occurrence", 1, "1-based matching occurrence to intervene on")
	var interventionOccurrences stringListFlag
	interventionOutput := flag.String("intervention-output", "", "ABI-encoded return data for substitute action")
	interventionInput := flag.String("intervention-input", "", "replacement calldata for rewrite_input action")
	interventionValue := flag.String("intervention-value", "", "replacement CALL value in wei for rewrite_value action")
	interventionCallbackTo := flag.String("intervention-callback-to", "", "callback destination for callback_trampoline")
	interventionCallbackInput := flag.String("intervention-callback-input", "", "frozen callback calldata for callback_trampoline")
	interventionCapitalToken := flag.String("intervention-capital-token", "", "ERC-20 token for callback_trampoline_transfer")
	interventionCapitalAmount := flag.String("intervention-capital-amount", "", "ERC-20 amount for callback_trampoline_transfer")
	var dropTx stringListFlag
	flag.Var(&dropTx, "drop-tx", "prefix transaction index to remove before replaying the rest unchanged (repeatable or comma-separated)")
	var targetCode stringListFlag
	var targetCodeCopy stringListFlag
	var targetStorage stringListFlag
	flag.Var(&targetCode, "target-code", "address=runtime-bytecode override (repeatable)")
	flag.Var(&targetCodeCopy, "target-code-copy", "destination=source current runtime-code copy (repeatable)")
	flag.Var(&targetStorage, "target-storage", "address:slot=value override (repeatable)")
	flag.Var(&interventionStoragePatch, "intervention-storage-patch", "call-site storage patch address:slot=value (repeatable; requires storage_patch action)")
	flag.Var(&interventionOccurrences, "intervention-occurrences", "comma-separated or repeatable 1-based matching occurrences to intervene on")
	flag.Parse()
	selectedOccurrences := []int{*interventionOccurrence}
	if len(interventionOccurrences) > 0 {
		selectedOccurrences = nil
		for _, raw := range interventionOccurrences {
			for _, part := range strings.Split(raw, ",") {
				value, parseErr := strconv.Atoi(strings.TrimSpace(part))
				if parseErr != nil || value < 1 {
					panic("--intervention-occurrences must contain positive integers")
				}
				selectedOccurrences = append(selectedOccurrences, value)
			}
		}
		sort.Ints(selectedOccurrences)
		for i := 1; i < len(selectedOccurrences); i++ {
			if selectedOccurrences[i] == selectedOccurrences[i-1] {
				panic("--intervention-occurrences contains duplicate occurrence")
			}
		}
	}
	if *replayMode != "discovery" && *replayMode != "frozen-validation" {
		panic("--replay-mode must be discovery or frozen-validation")
	}
	chainProfile, err := profileForChainID(*chainID)
	if err != nil {
		panic(err)
	}
	chainConfig, err := getChainConfig(*chainID)
	if err != nil {
		panic(err)
	}
	if *context == "" || (!*listAuthorities && *outputPath == "") {
		panic("--context is required; --output is required unless --list-authorities is used")
	}
	var header types.Header
	if err := readJSON(*context+"/block.json", &header); err != nil {
		panic(err)
	}
	var txs []types.Transaction
	var rawTxs []json.RawMessage
	if err := readJSON(*context+"/transactions.json", &rawTxs); err != nil {
		panic(err)
	}
	for _, raw := range rawTxs {
		var tx types.Transaction
		if err := tx.UnmarshalJSON(raw); err != nil {
			panic(err)
		}
		txs = append(txs, tx)
	}
	if *listAuthorities {
		addresses, err := authorizationAddresses(txs)
		if err != nil {
			panic(err)
		}
		if err := json.NewEncoder(os.Stdout).Encode(map[string]any{
			"go_ethereum_version": goEthereumVersion,
			"authorities":         addresses["authorities"],
			"code_targets":        addresses["code_targets"],
			"required_accounts":   addresses["required"],
		}); err != nil {
			panic(err)
		}
		return
	}
	var receipts []struct {
		Index   int    `json:"index"`
		TxHash  string `json:"tx_hash"`
		Receipt struct {
			Status  string       `json:"status"`
			GasUsed string       `json:"gasUsed"`
			Logs    []*types.Log `json:"logs"`
		} `json:"receipt"`
	}
	if err := readJSON(*context+"/receipts.json", &receipts); err != nil {
		panic(err)
	}
	var traces []row
	if err := readJSON(*context+"/prestates.json", &traces); err != nil {
		panic(err)
	}
	if len(txs) != len(receipts) || len(txs) != len(traces) {
		panic("context counts do not match")
	}
	txHashes := make([]string, len(txs))
	for i := range txs {
		txHashes[i] = txs[i].Hash().Hex()
	}
	poststates, err := loadPoststates(*context+"/poststates.json", txHashes)
	if err != nil {
		panic("proof-bound replay requires valid poststates.json: " + err.Error())
	}
	if *targetIndex < 0 {
		*targetIndex = len(txs) - 1
	}
	if *targetIndex < 0 || *targetIndex >= len(txs) {
		panic("target-index outside context")
	}
	droppedIndices, err := parseDropIndices(dropTx, *targetIndex)
	if err != nil {
		panic(err)
	}
	var ordering *orderingReport
	if len(droppedIndices) > 0 {
		ordering = newOrderingReport(droppedIndices, *targetIndex)
	}
	merged, err := mergeAccounts(traces)
	if err != nil {
		panic(err)
	}
	if authPath := *context + "/authorization_accounts.json"; fileExists(authPath) {
		var authAccounts map[string]account
		if err := readJSON(authPath, &authAccounts); err != nil {
			panic(err)
		}
		authPayload, err := json.Marshal(authAccounts)
		if err != nil {
			panic(err)
		}
		merged, err = mergeAccounts(append(traces, row{Trace: authPayload}))
		if err != nil {
			panic(err)
		}
	}
	if *proofPath != "" {
		addresses := make([]string, 0, len(merged))
		for address := range merged {
			addresses = append(addresses, address)
		}
		existence, err := proofAccountExistence(*proofPath, addresses)
		if err != nil {
			panic(err)
		}
		for address, exists := range existence {
			a := merged[address]
			if !exists {
				// The proof's non-existence is authoritative.  Discovery traces
				// can contain requested zero/default fields for an absent account;
				// none of those may be materialized into StateDB.
				a = account{}
			}
			a.Exists = &exists
			merged[address] = a
		}
	}
	if *proofPath == "" {
		panic("proof-bound replay requires --proofs")
	}
	chainCtx, err := loadChainContext(*context+"/ancestors.json", &header, chainConfig)
	if err != nil {
		panic(err)
	}
	parent := chainCtx.byNumber[header.Number.Uint64()-1]
	if parent == nil {
		panic("proof-bound replay requires canonical parent header")
	}
	discovered := make(map[string]map[string]struct{}, len(merged))
	for address, value := range merged {
		slots := make(map[string]struct{}, len(value.Storage))
		for slot := range value.Storage {
			slots[strings.ToLower(common.HexToHash(slot).Hex())] = struct{}{}
		}
		discovered[strings.ToLower(common.HexToAddress(address).Hex())] = slots
	}
	for _, item := range targetCode {
		address, _, parseErr := parseOverride(item)
		if parseErr != nil {
			panic(parseErr)
		}
		if isReservedSyntheticAddress(address) {
			discovered[strings.ToLower(address.Hex())] = make(map[string]struct{})
		}
	}
	for _, item := range targetCodeCopy {
		parts := strings.SplitN(item, "=", 2)
		if len(parts) != 2 {
			panic("target-code-copy must be destination=source")
		}
		destination := common.HexToAddress(parts[0])
		if isReservedSyntheticAddress(destination) {
			discovered[strings.ToLower(destination.Hex())] = make(map[string]struct{})
		}
	}
	for _, row := range poststates {
		for address, value := range row.Prestate {
			addDiscoveredStorage(discovered, address, value.Storage)
		}
		for address, value := range row.Poststate {
			addDiscoveredStorage(discovered, address, value.Storage)
		}
		addCallTraceDiscovery(row.Calltrace, discovered)
	}
	if *extraFootprintPath != "" {
		var extra map[string][]string
		if err := readJSON(*extraFootprintPath, &extra); err != nil {
			panic(fmt.Errorf("read extra footprint: %w", err))
		}
		for rawAddress, slots := range extra {
			address := strings.ToLower(common.HexToAddress(rawAddress).Hex())
			requested := discovered[address]
			if requested == nil {
				requested = make(map[string]struct{})
				discovered[address] = requested
			}
			for _, rawSlot := range slots {
				requested[strings.ToLower(common.HexToHash(rawSlot).Hex())] = struct{}{}
			}
		}
	}
	initial, err := loadAuthenticatedInitialState(*proofPath, discovered, &header, parent)
	if err != nil {
		panic(err)
	}
	if err := requirePreExecutionAccounts(initial, &header, parent, chainConfig); err != nil {
		panic(err)
	}
	st, err := makeState(initial)
	if err != nil {
		panic(err)
	}
	gasPool := core.NewGasPool(header.GasLimit)
	preBlockContext := core.NewEVMBlockContext(&header, chainCtx, &header.Coinbase)
	readGuard := newAuthenticatedReadGuard(initial)
	readGuard.txIndex = -1
	guardedState := &authenticatedStateDB{StateDB: st, guard: readGuard}
	preEVM := vm.NewEVM(preBlockContext, guardedState, chainConfig, vm.Config{})
	if err := preExecutionGuarded(preEVM, header.ParentBeaconRoot, parent, chainConfig, header.Number, header.Time, readGuard); err != nil {
		panic("pre-execution rejected by authenticated state boundary: " + err.Error())
	}
	if err := verifyPreExecutionState(st, &header, parent, chainConfig); err != nil {
		panic(err)
	}

	rules := chainConfig.Rules(header.Number, false, header.Time)
	resultOutput := output{Mode: "sequential-relevant-substate", ReplayMode: *replayMode, BlockNumber: header.Number.String(), ChainRules: map[string]any{
		"chain_id": chainProfile.ID, "chain_name": chainProfile.Name,
		"go_ethereum_version": goEthereumVersion,
		"experimental":        chainProfile.Experimental,
		"istanbul":            rules.IsIstanbul, "berlin": rules.IsBerlin, "london": rules.IsLondon,
		"header_time": header.Time, "header_gas_limit": header.GasLimit,
		"difficulty": header.Difficulty.String(), "base_fee_nil": header.BaseFee == nil,
	}, AllGasMatch: true, AllStatus: true, AllLogsMatch: true, PostStateEvidenceAvailable: true, RelevantPostStateMatch: true, TargetIndex: *targetIndex,
		Note: "One shared StateDB seeded only from the proof-bound authenticated initial state. Global state root is out of scope; unauthenticated account/storage reads invalidate fidelity acceptance."}
	resultOutput.BlockContextComplete = chainCtx.complete && parent != nil
	resultOutput.PreExecutionApplied = true
	resultOutput.Mutation = *targetData != "" || len(targetCode) > 0 || len(targetCodeCopy) > 0 || len(targetStorage) > 0
	if resultOutput.Mutation {
		resultOutput.MutationNote = "target override applied after prefix transactions"
	}
	if ordering != nil {
		resultOutput.DroppedIndices = ordering.DroppedIndices
		resultOutput.OrderingIntervention = ordering
		resultOutput.Note += " Ordering intervention: dropped prefix transactions are not executed, so fidelity gates are expected to fail; compare against the context receipts via ordering_intervention."
	}
	baselineFor := func(i int) baselineOutcome {
		return baselineOutcome{Status: receipts[i].Receipt.Status == "0x1", Gas: quantity(receipts[i].Receipt.GasUsed).Uint64(), Logs: receipts[i].Receipt.Logs}
	}
	var evmReplay, targetEVM time.Duration
	resultOutput.Timing.ContextLoad = durationMS(time.Since(startedAt))
	targetPrefixLogCount := -1
	for i, tx := range txs[:*targetIndex+1] {
		readGuard.txIndex = i
		if ordering != nil && ordering.isDropped(i) {
			baseline := baselineFor(i)
			ordering.recordDropped(i, tx.Hash().Hex(), baseline)
			resultOutput.Results = append(resultOutput.Results, result{Index: i, Hash: tx.Hash().Hex(), ExpectedGas: baseline.Gas, ExpectedOK: baseline.Status, Error: "dropped by ordering intervention"})
			resultOutput.AllGasMatch = false
			resultOutput.AllStatus = false
			resultOutput.AllLogsMatch = false
			resultOutput.RelevantPostStateMatch = false
			continue
		}
		var txEVM time.Duration
		var messageOverride *core.Message
		if i == *targetIndex && *targetData != "" {
			var data []byte
			data, err = decodeTargetData(&tx, *targetData)
			if err != nil {
				resultOutput.Results = append(resultOutput.Results, result{Index: i, Hash: tx.Hash().Hex(), Error: err.Error()})
				resultOutput.AllGasMatch = false
				resultOutput.AllStatus = false
				continue
			}
			signer := types.MakeSigner(chainConfig, header.Number, header.Time)
			messageOverride, err = syntheticMessageWithData(&tx, signer, header.BaseFee, data)
			if err != nil {
				resultOutput.Results = append(resultOutput.Results, result{Index: i, Hash: tx.Hash().Hex(), Error: err.Error()})
				resultOutput.AllGasMatch = false
				resultOutput.AllStatus = false
				continue
			}
			resultOutput.MutationApplication = append(resultOutput.MutationApplication, mutationApplication{
				Kind: "data", TargetIndex: *targetIndex, PrefixCompleted: i,
				Before: hexutil.Encode(tx.Data()), After: hexutil.Encode(data),
			})
		}
		if i == *targetIndex {
			if *targetBalance != "" {
				addr, value, err := parseOverride(*targetBalance)
				if err != nil {
					panic(err)
				}
				before := st.GetBalance(addr).ToBig().String()
				st.SetBalance(addr, uint256.MustFromBig(quantity(value)), tracing.BalanceChangeUnspecified)
				resultOutput.MutationApplication = append(resultOutput.MutationApplication, mutationApplication{Kind: "balance", Address: addr.Hex(), TargetIndex: *targetIndex, PrefixCompleted: i, Before: before, After: quantity(value).String()})
			}
			// StateDB accumulates logs from the sequential prefix and target.
			// Record the prefix length before applying the target so output
			// contains only logs emitted by this transaction.
			targetPrefixLogCount = len(st.Logs())
			for _, item := range targetCodeCopy {
				parts := strings.SplitN(item, "=", 2)
				if len(parts) != 2 {
					panic("target-code-copy must be destination=source")
				}
				destination := common.HexToAddress(parts[0])
				source := common.HexToAddress(parts[1])
				if !isReservedSyntheticAddress(destination) {
					panic(fmt.Sprintf("target-code-copy destination is not reserved: %s", destination.Hex()))
				}
				readGuard.allowSyntheticCode(destination)
				if readGuard.violated {
					panic("target-code-copy destination is not proof-bound absent")
				}
				before := hexutil.Encode(st.GetCode(destination))
				current := hexutil.Encode(st.GetCode(source))
				st.SetCode(destination, common.FromHex(current), tracing.CodeChangeUnspecified)
				resultOutput.MutationApplication = append(resultOutput.MutationApplication, mutationApplication{
					Kind: "code-copy", Address: destination.Hex(), Source: source.Hex(),
					TargetIndex: *targetIndex, PrefixCompleted: i, Before: before, After: current,
				})
			}
			for _, item := range targetCode {
				address, code, parseErr := parseOverride(item)
				if parseErr != nil {
					panic(parseErr)
				}
				decoded, decodeErr := hexutil.Decode(code)
				if decodeErr != nil {
					panic(decodeErr)
				}
				if isReservedSyntheticAddress(address) {
					readGuard.allowSyntheticCode(address)
				}
				before := hexutil.Encode(st.GetCode(address))
				st.SetCode(address, decoded, tracing.CodeChangeUnspecified)
				resultOutput.MutationApplication = append(resultOutput.MutationApplication, mutationApplication{
					Kind: "code", Address: address.Hex(), TargetIndex: *targetIndex,
					PrefixCompleted: i, Before: before, After: hexutil.Encode(decoded),
				})
			}
			for _, item := range targetStorage {
				parts := strings.SplitN(item, "=", 2)
				if len(parts) != 2 {
					panic("target-storage must be address:slot=value")
				}
				left := strings.SplitN(parts[0], ":", 2)
				if len(left) != 2 {
					panic("target-storage must be address:slot=value")
				}
				address := common.HexToAddress(left[0])
				slot := common.HexToHash(left[1])
				before := st.GetState(address, slot)
				after := common.HexToHash(parts[1])
				st.SetState(address, slot, after)
				resultOutput.MutationApplication = append(resultOutput.MutationApplication, mutationApplication{
					Kind: "storage", Address: address.Hex(), Slot: slot.Hex(), TargetIndex: *targetIndex,
					PrefixCompleted: i, Before: before.Hex(), After: after.Hex(),
				})
			}
		}
		var expectedGas *big.Int
		var expectedOK bool
		expectedGas = quantity(receipts[i].Receipt.GasUsed)
		expectedOK = receipts[i].Receipt.Status == "0x1"
		r := result{Index: i, Hash: tx.Hash().Hex(), ExpectedGas: expectedGas.Uint64(), ExpectedOK: expectedOK, PostStateMatch: false}
		var runErr error
		if err == nil {
			config := vm.Config{}
			var frames *[]callFrame
			var revertData *string
			var balanceChanges *[]balanceChange
			var storageChanges *[]storageChange
			var logs *[]*types.Log
			var opcodes *[]opcodeEvent
			if i == *targetIndex {
				var hooks *tracing.Hooks
				hooks, frames, revertData, balanceChanges, storageChanges, logs, opcodes = newCallHooks(*compactOpcodeTelemetry)
				originalOnOpcode := hooks.OnOpcode
				hooks.OnOpcode = func(pc uint64, op byte, gas, cost uint64, scope tracing.OpContext, data []byte, depth int, hookErr error) {
					originalOnOpcode(pc, op, gas, cost, scope, data, depth, hookErr)
					readGuard.onOpcode(pc, op, gas, cost, scope, data, depth, hookErr)
				}
				config.Tracer = hooks
			} else {
				config.Tracer = &tracing.Hooks{OnOpcode: readGuard.onOpcode}
			}
			config.Tracer.OnCodeChange = readGuard.onCodeChange
			originalOnEnter := config.Tracer.OnEnter
			config.Tracer.OnEnter = func(depth int, typ byte, from, to common.Address, input []byte, gas uint64, value *big.Int) {
				readGuard.onEnter(depth, typ, from, to, input, gas, value)
				if originalOnEnter != nil {
					originalOnEnter(depth, typ, from, to, input, gas, value)
				}
			}
			blockContext := core.NewEVMBlockContext(&header, chainCtx, &header.Coinbase)
			evm := vm.NewEVM(blockContext, &authenticatedStateDB{StateDB: st, guard: readGuard}, chainConfig, config)
			var intervention *callInterventionEvidence
			if i == *targetIndex && *interventionAction != "" {
				if (*interventionAction != "revert" && *interventionAction != "observe_only" && *interventionAction != "substitute" && *interventionAction != "substitute_passthrough" && *interventionAction != "rewrite_input" && *interventionAction != "rewrite_value" && *interventionAction != "rewrite_input_value" && *interventionAction != "callback_trampoline" && *interventionAction != "callback_trampoline_transfer" && *interventionAction != "storage_patch") || (*interventionType != "CALL" && *interventionType != "DELEGATECALL" && *interventionType != "STATICCALL") || *interventionCaller == "" || *interventionCallee == "" || *interventionSelector == "" || *interventionDepth < 0 || *interventionOccurrence < 1 || (*interventionAction == "storage_patch" && len(interventionStoragePatch) == 0) || ((*interventionAction == "substitute" || *interventionAction == "substitute_passthrough") && *interventionOutput == "") || ((*interventionAction == "rewrite_input" || *interventionAction == "rewrite_input_value") && *interventionInput == "") || ((*interventionAction == "rewrite_value" || *interventionAction == "rewrite_input_value") && (*interventionValue == "" || *interventionType != "CALL")) || ((*interventionAction == "callback_trampoline" || *interventionAction == "callback_trampoline_transfer") && (*interventionCallbackTo == "" || *interventionCallbackInput == "")) || (*interventionAction == "callback_trampoline_transfer" && (*interventionCapitalToken == "" || *interventionCapitalAmount == "")) {
					panic("incomplete call intervention descriptor")
				}
				intervention = &callInterventionEvidence{Caller: common.HexToAddress(*interventionCaller).Hex(), Callee: common.HexToAddress(*interventionCallee).Hex(), Selector: strings.ToLower(*interventionSelector), Depth: *interventionDepth, Action: *interventionAction, CallType: *interventionType, SelectedOccurrences: append([]int(nil), selectedOccurrences...)}
				var trampolineTo common.Address
				var trampolineInput []byte
				var capitalToken common.Address
				var capitalAmount *uint256.Int
				if *interventionAction == "callback_trampoline" || *interventionAction == "callback_trampoline_transfer" {
					var err error
					trampolineTo = common.HexToAddress(*interventionCallbackTo)
					trampolineInput, err = hexutil.Decode(*interventionCallbackInput)
					if err != nil || len(trampolineInput) < 4 {
						panic("invalid callback trampoline descriptor")
					}
					if *interventionAction == "callback_trampoline_transfer" {
						capitalToken = common.HexToAddress(*interventionCapitalToken)
						capitalAmount, err = uint256.FromHex(*interventionCapitalAmount)
						if err != nil {
							panic("invalid callback capital amount")
						}
					}
				}
				var matches int
				var parsedStoragePatches []struct {
					address     common.Address
					slot, value common.Hash
				}
				if *interventionAction == "storage_patch" {
					for _, item := range interventionStoragePatch {
						parts := strings.SplitN(item, "=", 2)
						if len(parts) != 2 {
							panic("intervention-storage-patch must be address:slot=value")
						}
						left := strings.SplitN(parts[0], ":", 2)
						if len(left) != 2 {
							panic("intervention-storage-patch must be address:slot=value")
						}
						parsedStoragePatches = append(parsedStoragePatches, struct {
							address     common.Address
							slot, value common.Hash
						}{common.HexToAddress(left[0]), common.HexToHash(left[1]), common.HexToHash(parts[1])})
					}
				}
				evm.CallIntervention = func(op byte, depth int, from, to common.Address, input []byte, budget vm.GasBudget, value *uint256.Int) (bool, []byte, []byte, error) {
					var expectedOp byte = byte(vm.CALL)
					if intervention.CallType == "DELEGATECALL" {
						expectedOp = byte(vm.DELEGATECALL)
					} else if intervention.CallType == "STATICCALL" {
						expectedOp = byte(vm.STATICCALL)
					}
					if op != expectedOp || depth != intervention.Depth || from != common.HexToAddress(intervention.Caller) || to != common.HexToAddress(intervention.Callee) || (len(input) < 4 || hexutil.Encode(input[:4]) != intervention.Selector) {
						return false, nil, nil, nil
					}
					matches++
					intervention.MatchCount = matches
					if !containsInt(selectedOccurrences, matches) {
						return false, nil, nil, nil
					}
					intervention.ApplicationVerified = true
					intervention.AppliedOccurrences = append(intervention.AppliedOccurrences, matches)
					intervention.MatchedInput = hexutil.Encode(input)
					intervention.MatchedDepth = depth
					if value != nil {
						intervention.OriginalValue = value.String()
					}
					if intervention.Action == "observe_only" {
						return false, nil, nil, nil
					}
					if intervention.Action == "storage_patch" {
						for _, patch := range parsedStoragePatches {
							before := st.GetState(patch.address, patch.slot)
							st.SetState(patch.address, patch.slot, patch.value)
							readBack := st.GetState(patch.address, patch.slot)
							intervention.StoragePatches = append(intervention.StoragePatches, storagePatchEvidence{Address: patch.address.Hex(), Slot: patch.slot.Hex(), Before: before.Hex(), After: patch.value.Hex(), ReadBack: readBack.Hex()})
						}
						return false, nil, nil, nil
					}
					if intervention.Action == "substitute_passthrough" {
						// Same seam and descriptor as substitution, but execute the
						// original child call. This is the same-kind sham: it checks
						// instrumentation without changing return data or state.
						return false, nil, nil, nil
					}
					if intervention.Action == "substitute" {
						output, err := hexutil.Decode(*interventionOutput)
						if err != nil {
							return true, nil, nil, err
						}
						intervention.MatchedOutput = hexutil.Encode(output)
						return true, nil, output, nil
					}
					if intervention.Action == "rewrite_input_value" {
						replacement, err := hexutil.Decode(*interventionInput)
						if err != nil {
							return true, nil, nil, err
						}
						newValue, err := uint256.FromHex(*interventionValue)
						if err != nil || value == nil {
							return true, nil, nil, fmt.Errorf("rewrite_input_value requires valid CALL value")
						}
						intervention.OriginalValue = value.String()
						value.Set(newValue)
						intervention.RewrittenValue = value.String()
						return false, replacement, nil, nil
					}
					if intervention.Action == "rewrite_input" {
						replacement, err := hexutil.Decode(*interventionInput)
						if err != nil {
							return true, nil, nil, err
						}
						return false, replacement, nil, nil
					}
					if intervention.Action == "rewrite_value" {
						replacement, err := uint256.FromHex(*interventionValue)
						if err != nil {
							return true, nil, nil, err
						}
						if value == nil {
							return true, nil, nil, fmt.Errorf("rewrite_value requires CALL value")
						}
						value.Set(replacement)
						intervention.RewrittenValue = value.String()
						return false, nil, nil, nil
					}
					if intervention.Action == "callback_trampoline" || intervention.Action == "callback_trampoline_transfer" {
						// Execute the frozen callback as the intercepted provider. The
						// provider's capital transfer is intentionally omitted; callback
						// calldata and destination are supplied by the preregistered
						// descriptor and validated before the run.
						zero := uint256.NewInt(0)
						intervention.CallbackAttempted = true
						intervention.CallbackCaller = to.Hex()
						intervention.CallbackTo = trampolineTo.Hex()
						intervention.CallbackInput = hexutil.Encode(trampolineInput)
						callbackBudget := budget
						if intervention.Action == "callback_trampoline_transfer" {
							transferInput := make([]byte, 68)
							copy(transferInput[:4], common.FromHex("0xa9059cbb"))
							copy(transferInput[4+12:36], trampolineTo.Bytes())
							amountBytes := capitalAmount.Bytes32()
							copy(transferInput[36:], amountBytes[:])
							_, callbackBudget, err = evm.Call(to, capitalToken, transferInput, budget, zero)
							if err != nil {
								intervention.CallbackError = err.Error()
								return true, nil, nil, err
							}
						}
						ret, _, err := evm.Call(to, trampolineTo, trampolineInput, callbackBudget, zero)
						if err != nil {
							intervention.CallbackError = err.Error()
							return true, nil, ret, err
						}
						return true, nil, ret, nil
					}
					return true, nil, nil, vm.ErrExecutionReverted
				}
			}
			logStart := len(st.Logs())
			var receipt *types.Receipt
			var applyErr error
			applyStart := time.Now()
			if messageOverride != nil {
				receipt, _, applyErr = applyMessageGuarded(evm, gasPool, st, &header, &tx, messageOverride, readGuard)
			} else {
				receipt, _, applyErr = applyTransactionGuarded(evm, gasPool, st, &header, &tx, readGuard)
			}
			txEVM = time.Since(applyStart)
			evmReplay += txEVM
			if i == *targetIndex {
				targetEVM = txEVM
			}
			if applyErr != nil {
				runErr = applyErr
			} else {
				r.ActualGas = receipt.GasUsed
				r.ActualOK = receipt.Status == types.ReceiptStatusSuccessful
				actualLogs := append([]*types.Log(nil), st.Logs()[logStart:]...)
				r.Logs = actualLogs
				r.LogsMatch = logsEqual(actualLogs, receipts[i].Receipt.Logs)
				r.PostStateMatch = postStateMatches(st, poststates[i].Prestate, poststates[i].Poststate, readGuard)
			}
			if frames != nil {
				r.CallTrace = *frames
				if intervention != nil {
					for _, frame := range r.CallTrace {
						if frame.Reverted || frame.Error != "" {
							intervention.FirstRevertDepth = frame.Depth
							intervention.FirstRevertData = frame.Output
							break
						}
					}
				}
			}
			if revertData != nil {
				r.RevertData = *revertData
			}
			if balanceChanges != nil {
				r.BalanceChanges = *balanceChanges
			}
			if storageChanges != nil {
				r.StorageChanges = *storageChanges
			}
			if logs != nil {
				r.Logs = *logs
			}
			if i == *targetIndex && receipt != nil && targetPrefixLogCount >= 0 {
				r.Logs = targetLogs(st.Logs(), targetPrefixLogCount)
			}
			if opcodes != nil {
				r.OpcodeTail = *opcodes
				if *emitOpcodeTelemetry {
					r.OpcodeTelemetry = append([]opcodeEvent(nil), (*opcodes)...)
				}
			}
			if intervention != nil && !allOccurrencesMatched(intervention.MatchCount, selectedOccurrences) {
				runErr = fmt.Errorf("call intervention occurrence gate failed: got %d matches, want occurrences %v", intervention.MatchCount, selectedOccurrences)
			}
			r.Intervention = intervention
		}
		if runErr != nil {
			r.Error = runErr.Error()
			r.GasMatch = false
			r.StatusMatch = false
		} else {
			r.GasMatch = r.ActualGas == r.ExpectedGas
			r.StatusMatch = r.ActualOK == r.ExpectedOK
		}
		r.UnauthenticatedRead = readGuard.violated
		resultOutput.Results = append(resultOutput.Results, r)
		resultOutput.TotalGas += r.ActualGas
		resultOutput.TotalExpect += r.ExpectedGas
		resultOutput.AllGasMatch = resultOutput.AllGasMatch && r.GasMatch
		resultOutput.AllStatus = resultOutput.AllStatus && r.StatusMatch
		resultOutput.AllLogsMatch = resultOutput.AllLogsMatch && r.LogsMatch
		resultOutput.RelevantPostStateMatch = resultOutput.RelevantPostStateMatch && r.PostStateMatch
		if ordering != nil {
			ordering.recordExecuted(r, baselineFor(i), txEVM)
			if readGuard.violated {
				// The counterfactual order reached state outside the proof
				// footprint. Values read there are defaults, not history:
				// stop and report instead of guessing. Re-run discovery with
				// -extra-footprint to extend the proof set.
				ordering.failClosed(i, readGuard.reasons)
				break
			}
		}
		if isUnauthenticatedStateError(runErr) {
			// The StateDB may have been partially mutated before the boundary
			// violation. Do not execute later transactions on contaminated state.
			break
		}
	}
	resultOutput.Timing.EVMReplay = durationMS(evmReplay)
	resultOutput.Timing.TargetEVM = durationMS(targetEVM)
	resultOutput.Timing.Note = replayTimingNote
	if ordering != nil {
		ordering.finalize()
	}
	resultOutput.ReadGuardReasons = append([]string(nil), readGuard.reasons...)
	resultOutput.ReadFailures = append([]readFailure(nil), readGuard.Failures...)
	resultOutput.PrefixGasMatch = true
	for i, r := range resultOutput.Results {
		if i < *targetIndex {
			resultOutput.PrefixGasMatch = resultOutput.PrefixGasMatch && r.GasMatch && r.StatusMatch
		}
	}
	resultOutput.IsolatedGate = resultOutput.AllGasMatch && resultOutput.AllStatus && len(resultOutput.Results) == len(txs)
	root := st.IntermediateRoot(false)
	resultOutput.StateRoot = root.Hex()
	resultOutput.ExpectedRoot = header.Root.Hex()
	resultOutput.StateRootMatch = root == header.Root
	if *proofPath != "" {
		proofStart := time.Now()
		accountsOK, storageOK, proofErr := verifyProofFile(*proofPath)
		resultOutput.Timing.ProofVerify = durationMS(time.Since(proofStart))
		resultOutput.ProofAccounts = accountsOK
		resultOutput.ProofStorage = storageOK
		resultOutput.PrestateProofVerified = proofErr == nil
		if proofErr != nil {
			resultOutput.Note += " proof verification failed: " + proofErr.Error()
		}
	}
	// Global state root is out of scope for a transaction-relevant snapshot.
	resultOutput.Acceptance = resultOutput.BlockContextComplete && resultOutput.PreExecutionApplied && !readGuard.violated && resultOutput.AllGasMatch && resultOutput.AllStatus && resultOutput.AllLogsMatch && resultOutput.PrestateProofVerified && resultOutput.PostStateEvidenceAvailable && resultOutput.RelevantPostStateMatch && len(resultOutput.Results) == len(txs)
	if *opcodeTelemetryNDJSON != "" {
		f, err := os.Create(*opcodeTelemetryNDJSON)
		if err != nil {
			panic(err)
		}
		buf := bufio.NewWriterSize(f, 1<<20)
		enc := json.NewEncoder(buf)
		for i := range resultOutput.Results {
			for _, event := range resultOutput.Results[i].OpcodeTelemetry {
				if err := enc.Encode(event); err != nil {
					_ = f.Close()
					panic(err)
				}
			}
			resultOutput.Results[i].OpcodeTelemetry = nil
			resultOutput.Results[i].OpcodeTail = nil
		}
		if err := buf.Flush(); err != nil {
			_ = f.Close()
			panic(err)
		}
		if err := f.Close(); err != nil {
			panic(err)
		}
	}
	b, _ := json.MarshalIndent(resultOutput, "", "  ")
	if err := os.WriteFile(*outputPath, append(b, '\n'), 0644); err != nil {
		panic(err)
	}
	fmt.Println(string(b))
}
func newInstrumentedHooks(
	st *state.StateDB,
	scopingMgr *scopingManager,
	frameRec *frameRecorder,
	revertClf *revertClassifier,
) (*tracing.Hooks, *[]callFrame, *string, *[]balanceChange, *[]*types.Log, *[]opcodeEvent) {
	frames := make([]callFrame, 0)
	revertData := ""
	balanceChanges := make([]balanceChange, 0)
	logs := make([]*types.Log, 0)
	opcodes := make([]opcodeEvent, 0)

	hooks := &tracing.Hooks{
		OnEnter: func(depth int, typ byte, from common.Address, to common.Address, input []byte, gas uint64, value *big.Int) {
			frames = append(frames, callFrame{
				Event: "enter", Depth: depth,
				Type: vm.OpCode(typ).String(), From: from.Hex(), To: to.Hex(),
				Input: hexutil.Encode(input), Gas: gas, Value: value.String(),
			})
			if revertClf != nil {
				revertClf.onEnter(depth, from, to)
			}
			if frameRec != nil {
				frameRec.onEnter(depth, typ, from, to, input, gas, value)
			}
			if scopingMgr != nil {
				fIdx := -1
				if frameRec != nil {
					fIdx = frameRec.currentFrameIndex()
				}
				scopingMgr.onEnter(depth, typ, from, to, input, gas, st, fIdx)
			}
		},
		OnExit: func(depth int, output []byte, gasUsed uint64, err error, reverted bool) {
			frame := callFrame{Event: "exit", Depth: depth, GasUsed: gasUsed, Reverted: reverted}
			if err != nil {
				frame.Error = err.Error()
			}
			if depth == 0 && reverted && len(output) > 0 {
				revertData = hexutil.Encode(output)
			}
			frames = append(frames, frame)

			if scopingMgr != nil {
				scopingMgr.onExit(depth, output, st)
			}
			if frameRec != nil {
				frameRec.onExit(depth, output, gasUsed, err, reverted)
			}
			if revertClf != nil {
				revertClf.onExit(depth, err, reverted)
			}
		},
		OnBalanceChange: func(addr common.Address, previous, current *big.Int, _ tracing.BalanceChangeReason) {
			balanceChanges = append(balanceChanges, balanceChange{Address: addr.Hex(), Previous: previous.String(), Current: current.String()})
			if frameRec != nil {
				frameRec.onBalanceChange(addr, previous, current)
			}
		},
		OnLog: func(log *types.Log) {
			logs = append(logs, log)
			if frameRec != nil {
				frameRec.onLog(log)
			}
		},
	}
	hooks.OnOpcode = func(pc uint64, op byte, gas, cost uint64, _ tracing.OpContext, _ []byte, depth int, err error) {
		e := opcodeEvent{PC: pc, Op: vm.OpCode(op).String(), Gas: gas, Cost: cost, Depth: depth}
		if err != nil {
			e.Error = err.Error()
		}
		if len(opcodes) >= 128 {
			opcodes = opcodes[1:]
		}
		opcodes = append(opcodes, e)
	}
	return hooks, &frames, &revertData, &balanceChanges, &logs, &opcodes
}
