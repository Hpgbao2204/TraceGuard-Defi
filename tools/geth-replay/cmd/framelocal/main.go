package main

// B2 baseline probe: execute each transaction with go-ethereum's real EVM
// using that transaction's own prestateTracer snapshot.  This first milestone
// is intentionally labelled "prestate-isolated": it validates chain rules,
// header fields, and per-transaction gas/status before we add a sequential
// state builder.  It must not be mistaken for the final prefix replayer.

import (
	"encoding/json"
	"flag"
	"fmt"
	"math/big"
	"os"
	"sort"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core"
	"github.com/ethereum/go-ethereum/core/rawdb"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/core/types"
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
			// An authenticated absence is authoritative.
			if value.Exists != nil && !*value.Exists {
				merged[address] = account{Exists: value.Exists}
				continue
			}
			current := merged[address]
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
	Index          int             `json:"index"`
	Hash           string          `json:"tx_hash"`
	ExpectedGas    uint64          `json:"expected_gas"`
	ActualGas      uint64          `json:"actual_gas"`
	GasMatch       bool            `json:"gas_match"`
	ExpectedOK     bool            `json:"expected_status"`
	ActualOK       bool            `json:"actual_status"`
	StatusMatch    bool            `json:"status_match"`
	Error          string          `json:"error,omitempty"`
	RevertData     string          `json:"revert_data,omitempty"`
	CallTrace      []callFrame     `json:"call_trace,omitempty"`
	Logs           []*types.Log    `json:"logs,omitempty"`
	BalanceChanges []balanceChange `json:"balance_changes,omitempty"`
	OpcodeTail     []opcodeEvent   `json:"opcode_tail,omitempty"`
}

type balanceChange struct {
	Address  string `json:"address"`
	Previous string `json:"previous"`
	Current  string `json:"current"`
}

type callFrame struct {
	Event    string `json:"event"`
	Depth    int    `json:"depth"`
	Type     string `json:"type,omitempty"`
	From     string `json:"from,omitempty"`
	To       string `json:"to,omitempty"`
	Input    string `json:"input,omitempty"`
	Gas      uint64 `json:"gas,omitempty"`
	Value    string `json:"value,omitempty"`
	GasUsed  uint64 `json:"gas_used,omitempty"`
	Error    string `json:"error,omitempty"`
	Reverted bool   `json:"reverted,omitempty"`
}

type opcodeEvent struct {
	PC    uint64 `json:"pc"`
	Op    string `json:"op"`
	Gas   uint64 `json:"gas"`
	Cost  uint64 `json:"cost"`
	Depth int    `json:"depth"`
	Error string `json:"error,omitempty"`
}

func targetLogs(all []*types.Log, prefixCount int) []*types.Log {
	if prefixCount < 0 || prefixCount > len(all) {
		return nil
	}
	return append([]*types.Log(nil), all[prefixCount:]...)
}

func newCallHooks() (*tracing.Hooks, *[]callFrame, *string, *[]balanceChange, *[]*types.Log, *[]opcodeEvent) {
	frames := make([]callFrame, 0)
	revertData := ""
	balanceChanges := make([]balanceChange, 0)
	logs := make([]*types.Log, 0)
	opcodes := make([]opcodeEvent, 0)
	hooks := &tracing.Hooks{
		OnEnter: func(depth int, typ byte, from common.Address, to common.Address, input []byte, gas uint64, value *big.Int) {
			frames = append(frames, callFrame{Event: "enter", Depth: depth,
				Type: vm.OpCode(typ).String(), From: from.Hex(), To: to.Hex(),
				Input: hexutil.Encode(input), Gas: gas, Value: value.String()})
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
		},
		OnBalanceChange: func(addr common.Address, previous, current *big.Int, _ tracing.BalanceChangeReason) {
			balanceChanges = append(balanceChanges, balanceChange{Address: addr.Hex(), Previous: previous.String(), Current: current.String()})
		},
		OnLog: func(log *types.Log) { logs = append(logs, log) },
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

	// One clock shared by all components, ticked once per enter and exit.
	clock := &eventClock{}
	if scopingMgr != nil {
		scopingMgr.clock = clock
	}
	if frameRec != nil {
		frameRec.clock = clock
	}
	if revertClf != nil {
		revertClf.clock = clock
	}

	hooks := &tracing.Hooks{
		OnEnter: func(depth int, typ byte, from common.Address, to common.Address, input []byte, gas uint64, value *big.Int) {
			clock.tick()
			frames = append(frames, callFrame{
				Event: "enter", Depth: depth,
				Type: vm.OpCode(typ).String(), From: from.Hex(), To: to.Hex(),
				Input: hexutil.Encode(input), Gas: gas, Value: value.String(),
			})
			if revertClf != nil {
				revertClf.onEnter(depth, from, to, input)
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
			clock.tick()
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
				revertClf.onExit(depth, output, err, reverted)
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

// targetRun is one traced execution of the target transaction.
type targetRun struct {
	recorder       *frameRecorder
	receipt        *types.Receipt
	err            error
	frames         *[]callFrame
	revertData     *string
	balanceChanges *[]balanceChange
	logs           *[]*types.Log
	opcodes        *[]opcodeEvent
}

func applyTarget(
	st *state.StateDB,
	header *types.Header,
	chainConfig *params.ChainConfig,
	gasPool *core.GasPool,
	tx *types.Transaction,
	scopingMgr *scopingManager,
	rec *frameRecorder,
	revertClf *revertClassifier,
	onEVM func(*vm.EVM),
) *targetRun {
	hooks, frames, revertData, balanceChanges, logs, opcodes := newInstrumentedHooks(st, scopingMgr, rec, revertClf)
	blockContext := core.NewEVMBlockContext(header, chainFor(header, chainConfig), &header.Coinbase)
	evm := vm.NewEVM(blockContext, st, chainConfig, vm.Config{Tracer: hooks})
	if onEVM != nil {
		onEVM(evm)
	}
	receipt, _, err := core.ApplyTransaction(evm, gasPool, st, header, tx)
	return &targetRun{recorder: rec, receipt: receipt, err: err, frames: frames, revertData: revertData,
		balanceChanges: balanceChanges, logs: logs, opcodes: opcodes}
}

func applyTargetOverrides(st *state.StateDB, targetCode, targetStorage []string) {
	for _, item := range targetCode {
		address, code, parseErr := parseOverride(item)
		if parseErr != nil {
			panic(parseErr)
		}
		decoded, decodeErr := hexutil.Decode(code)
		if decodeErr != nil {
			panic(decodeErr)
		}
		st.SetCode(address, decoded, tracing.CodeChangeUnspecified)
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
		st.SetState(common.HexToAddress(left[0]), common.HexToHash(left[1]), common.HexToHash(parts[1]))
	}
}

// makeLean drops the per-call trace, logs, balance changes and opcode tail,
// which dominate output size; verdicts, entry-frame losses and scoped reads stay.
func makeLean(out *output) {
	for i := range out.Results {
		out.Results[i].CallTrace = nil
		out.Results[i].Logs = nil
		out.Results[i].BalanceChanges = nil
		out.Results[i].OpcodeTail = nil
	}
	for i := range out.EntryFrames {
		out.EntryFrames[i].Logs = nil
		out.EntryFrames[i].BalanceChanges = nil
		out.EntryFrames[i].AttackerCallbacks = nil
	}
}

type stringListFlag []string

func (f *stringListFlag) String() string { return strings.Join(*f, ",") }
func (f *stringListFlag) Set(value string) error {
	*f = append(*f, value)
	return nil
}

type output struct {
	Mode                  string                     `json:"mode"`
	ChainRules            map[string]any             `json:"chain_rules"`
	BlockNumber           string                     `json:"block_number"`
	Results               []result                   `json:"per_tx"`
	TotalGas              uint64                     `json:"total_actual_gas"`
	TotalExpect           uint64                     `json:"total_expected_gas"`
	AllGasMatch           bool                       `json:"all_gas_match"`
	AllStatus             bool                       `json:"all_status_match"`
	IsolatedGate          bool                       `json:"isolated_baseline_gate"`
	StateRoot             string                     `json:"state_root_actual"`
	ExpectedRoot          string                     `json:"state_root_expected"`
	StateRootMatch        bool                       `json:"state_root_match"`
	PrestateProofVerified bool                       `json:"prestate_proof_verified"`
	ProofAccounts         int                        `json:"proof_accounts_verified"`
	ProofStorage          int                        `json:"proof_storage_cells_verified"`
	TargetIndex           int                        `json:"target_index"`
	PrefixGasMatch        bool                       `json:"prefix_gas_match"`
	Mutation              bool                       `json:"mutation"`
	MutationNote          string                     `json:"mutation_note,omitempty"`
	Acceptance            bool                       `json:"acceptance_gate"`
	Note                  string                     `json:"note"`
	EntryFrames           []victimEntryFrame         `json:"entry_frames,omitempty"`
	RevertOrigin          *revertOriginResult        `json:"revert_origin,omitempty"`
	ScopedReads           []scopedReadRecord         `json:"scoped_reads,omitempty"`
	FrameLocalResult      *frameLocalExecutionResult `json:"frame_local_result,omitempty"`
	WholeTxResult         *frameLocalExecutionResult `json:"whole_tx_result,omitempty"`
	// BaselineTargetMatch: the unmodified target replay (pass 1) matched the
	// receipt's gas and status. In frame-local modes the counterfactual pass
	// is cancelled at the harm-frame exit, so its receipt cannot be compared.
	BaselineTargetMatch *bool `json:"baseline_target_match,omitempty"`
	// ReplayGate: authenticated prestate, exact prefix, and exact baseline
	// target. Verdicts are only admissible when it holds.
	ReplayGate bool `json:"replay_gate"`
	// AuthenticatedInitialState: the StateDB was seeded from EIP-1186 proofs
	// (not from the union of per-transaction prestate snapshots).
	AuthenticatedInitialState bool `json:"authenticated_initial_state"`
	Lean                      bool `json:"lean,omitempty"`
}

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

func makeState(accounts map[string]account) (*state.StateDB, error) {
	disk := rawdb.NewMemoryDatabase()
	trie := triedb.NewDatabase(disk, nil)
	db := state.NewDatabase(trie, nil)
	st, err := state.New(types.EmptyRootHash, db)
	if err != nil {
		return nil, err
	}
	for address, a := range accounts {
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

func parseOverride(value string) (common.Address, string, error) {
	parts := strings.SplitN(value, "=", 2)
	if len(parts) != 2 {
		return common.Address{}, "", fmt.Errorf("override must be address=value: %s", value)
	}
	return common.HexToAddress(strings.TrimSpace(parts[0])), strings.TrimSpace(parts[1]), nil
}

func replaceLegacyData(tx types.Transaction, data string) (types.Transaction, error) {
	if tx.Type() != types.LegacyTxType {
		return types.Transaction{}, fmt.Errorf("target-data only supports legacy transactions")
	}
	v, r, s := tx.RawSignatureValues()
	decoded, err := hexutil.Decode(data)
	if err != nil {
		return types.Transaction{}, err
	}
	return *types.NewTx(&types.LegacyTx{
		Nonce: tx.Nonce(), GasPrice: tx.GasPrice(), Gas: tx.Gas(),
		To: tx.To(), Value: tx.Value(), Data: decoded, V: v, R: r, S: s,
	}), nil
}

func main() {
	context := flag.String("context", "", "B2 context directory")
	outputPath := flag.String("output", "", "output JSON")
	listAuthorities := flag.Bool("list-authorities", false, "print recovered EIP-7702 authorities and exit")
	chainID := flag.Uint64("chain-id", mainnetChainID, "chain ID (1=Ethereum Mainnet, 43114=experimental Avalanche C-Chain)")
	proofPath := flag.String("proofs", "", "prestate_proofs.json (optional)")
	targetIndex := flag.Int("target-index", -1, "target transaction index; defaults to last")
	targetData := flag.String("target-data", "", "replacement calldata for target legacy tx")
	mode := flag.String("mode", "whole-tx", "execution mode: whole-tx, record, frame-local, isolation, sham, discover")
	scopedPrice := flag.Bool("scoped-price", false, "enable read-site scoping for price sources (f_price)")
	frameIndex := flag.Int("frame-index", -1, "target entry frame index for frame-local modes; -1 picks the harm frame with the largest per-token loss share")
	doseLambda := flag.Float64("dose-lambda", -1.0, "dose-response lambda parameter in [0.0, 1.0]")
	priceValue := flag.String("price-value", "", "explicit replacement return value for scoped reads (hex)")
	priceIdentity := flag.Bool("price-identity", false, "return the first ABI argument for one-argument conversion reads")
	lean := flag.Bool("lean", false, "omit call trace, logs, balance changes and opcode tail from the output; do not echo JSON to stdout")
	lossMinFrac := flag.Float64("loss-min-frac", defaultThresholds.LossMinFrac, "L_min as a fraction of the baseline loss of the same token (CAUSE when L' <= L_min)")
	rho := flag.Float64("rho", defaultThresholds.Rho, "PARTIAL when L_min < L' <= (1-rho)L")
	shamScale := flag.Float64("sham-scale", 0.5, "sham mode: multiply each 32-byte word of the unrelated read by this factor")
	unscoped := flag.Bool("unscoped", false, "whole-tx ablation: pin the declared -read-site values for every caller (attacker and third parties too), not only for the victim")
	var victims stringListFlag
	var scopeCallers stringListFlag
	var attackers stringListFlag
	var priceSources stringListFlag
	flag.Var(&victims, "victim", "victim contract address (repeatable)")
	flag.Var(&scopeCallers, "scope-caller", "caller address allowed to receive scoped read intervention (repeatable)")
	flag.Var(&attackers, "attacker", "attacker address (repeatable)")
	flag.Var(&priceSources, "price-source", "price source contract address (repeatable)")
	var readSiteFlags stringListFlag
	flag.Var(&readSiteFlags, "read-site", "declared factor read site target:selector, '*' allowed on one side (repeatable); replaces the price-selector catalogue")
	var targetCode stringListFlag
	var targetStorage stringListFlag
	flag.Var(&targetCode, "target-code", "address=runtime-bytecode override (repeatable)")
	flag.Var(&targetStorage, "target-storage", "address:slot=value override (repeatable)")
	flag.Parse()
	thresholds := verdictThresholds{LossMinFrac: *lossMinFrac, Rho: *rho}
	var sites []readSite
	for _, v := range readSiteFlags {
		rs, err := parseReadSite(v)
		if err != nil {
			panic(err)
		}
		sites = append(sites, rs)
	}
	if *unscoped && (*mode != "whole-tx" || !*scopedPrice || len(sites) == 0) {
		panic("-unscoped needs -mode whole-tx -scoped-price and at least one -read-site")
	}
	if *lossMinFrac < 0 || *lossMinFrac >= 1-*rho || *rho <= 0 || *rho >= 1 {
		panic("thresholds need 0 <= loss-min-frac < 1-rho and 0 < rho < 1")
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
			Status  string `json:"status"`
			GasUsed string `json:"gasUsed"`
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
	if *targetIndex < 0 {
		*targetIndex = len(txs) - 1
	}
	if *targetIndex < 0 || *targetIndex >= len(txs) {
		panic("target-index outside context")
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
		authAddresses, err := authorizationAddresses(txs)
		if err != nil {
			panic(err)
		}
		existence, err := proofAccountExistence(*proofPath, authAddresses["required"])
		if err != nil {
			panic(err)
		}
		for address, exists := range existence {
			a := merged[address]
			if !exists {
				// The proof's non-existence is authoritative.
				a = account{}
			}
			a.Exists = &exists
			merged[address] = a
		}
	}
	var st *state.StateDB
	authenticatedState := false
	if *proofPath != "" {
		var chainCtx chainContext
		st, chainCtx, err = buildAuthenticatedState(*context, *proofPath, merged, txs, &header, chainConfig)
		if err != nil {
			panic("authenticated initial state: " + err.Error())
		}
		replayChain = &chainCtx
		authenticatedState = true
	} else {
		st, err = makeState(merged)
		if err != nil {
			panic(err)
		}
	}
	gasPool := core.NewGasPool(header.GasLimit)

	rules := chainConfig.Rules(header.Number, false, header.Time)
	resultOutput := output{Mode: "sequential-relevant-substate", BlockNumber: header.Number.String(), ChainRules: map[string]any{
		"chain_id": chainProfile.ID, "chain_name": chainProfile.Name,
		"go_ethereum_version": goEthereumVersion,
		"experimental":        chainProfile.Experimental,
		"istanbul":            rules.IsIstanbul, "berlin": rules.IsBerlin, "london": rules.IsLondon,
		"header_time": header.Time, "header_gas_limit": header.GasLimit,
		"difficulty": header.Difficulty.String(), "base_fee_nil": header.BaseFee == nil,
	}, AllGasMatch: true, AllStatus: true, TargetIndex: *targetIndex,
		Note: "One shared StateDB; initial values are the union of transaction-relevant prestate snapshots. Global state root is out of scope; local prestate Merkle proofs are the authenticity gate."}
	resultOutput.AuthenticatedInitialState = authenticatedState
	if authenticatedState {
		resultOutput.Note = "One shared StateDB seeded from the proof-bound initial state at the parent state root, with ancestor headers and pre-execution applied (as in the main runner)."
	}
	resultOutput.Mutation = *targetData != "" || len(targetCode) > 0 || len(targetStorage) > 0
	if resultOutput.Mutation {
		resultOutput.MutationNote = "target override applied after prefix transactions"
	}
	targetPrefixLogCount := -1
	for i, tx := range txs[:*targetIndex+1] {
		if i == *targetIndex && *targetData != "" {
			tx, err = replaceLegacyData(tx, *targetData)
			if err != nil {
				resultOutput.Results = append(resultOutput.Results, result{Index: i, Hash: tx.Hash().Hex(), Error: err.Error()})
				resultOutput.AllGasMatch = false
				resultOutput.AllStatus = false
				continue
			}
		}
		var expectedGas *big.Int
		var expectedOK bool
		expectedGas = quantity(receipts[i].Receipt.GasUsed)
		expectedOK = receipts[i].Receipt.Status == "0x1"
		r := result{Index: i, Hash: tx.Hash().Hex(), ExpectedGas: expectedGas.Uint64(), ExpectedOK: expectedOK}
		var runErr error
		if i == *targetIndex {
			s0Snapshot := st.Copy()

			// Recover tx sender if attackers list is empty
			if len(attackers) == 0 {
				signer := types.MakeSigner(chainConfig, header.Number, header.Time)
				if sender, sErr := types.Sender(signer, &tx); sErr == nil {
					attackers = append(attackers, sender.Hex())
				}
			}

			var lambdaPtr *float64
			if *doseLambda >= 0.0 && *doseLambda <= 1.0 {
				lambdaPtr = doseLambda
			}
			var replacement []byte
			if *priceValue != "" {
				decoded, decodeErr := hexutil.Decode(*priceValue)
				if decodeErr != nil {
					panic(decodeErr)
				}
				replacement = decoded
			}

			frameMode := *mode == "frame-local" || *mode == "isolation" || *mode == "sham" || *mode == "discover"
			wholeTxVerdict := *mode == "whole-tx" && *scopedPrice

			// Pass 1: unmodified baseline on a copy of S0, for every mode that
			// compares against it.
			var base *targetRun
			if frameMode || wholeTxVerdict {
				baseState := s0Snapshot.Copy()
				baseRec := newFrameRecorder(baseState, victims, attackers, false, -1, nil)
				base = applyTarget(baseState, &header, chainConfig, core.NewGasPool(header.GasLimit), &tx, nil, baseRec, nil, nil)
				match := base.err == nil && base.receipt != nil && base.receipt.GasUsed == r.ExpectedGas &&
					(base.receipt.Status == types.ReceiptStatusSuccessful) == r.ExpectedOK
				resultOutput.BaselineTargetMatch = &match
			}

			// Pass 2: counterfactual on the shared state.
			targetPrefixLogCount = len(st.Logs())
			applyTargetOverrides(st, targetCode, targetStorage)

			var run *targetRun
			if frameMode {
				resultOutput.EntryFrames = base.recorder.entryFrames
				targetIdx := *frameIndex
				if targetIdx < 0 {
					targetIdx = selectHarmFrame(base.recorder.entryFrames)
				}
				valueMode := map[string]string{"frame-local": valueNeutral, "isolation": valueObserved, "sham": valueSham, "discover": valueDiscover}[*mode]
				scopingMgr := newScopingManager(true, victims, priceSources, scopeCallers, s0Snapshot, &header, chainConfig, lambdaPtr, valueMode, replacement, *priceIdentity)
				scopingMgr.shamScale = *shamScale
				scopingMgr.attackers = addressSet(attackers)
				scopingMgr.readSites = sites
				scopingMgr.maxDiscover = 2000

				var cfEVM *vm.EVM
				cfCancel := func() {
					if cfEVM != nil {
						cfEVM.Cancel()
					}
				}
				cfRecorder := newFrameRecorder(st, victims, attackers, true, targetIdx, cfCancel)
				// Frame-local: intervene only while the harm frame runs, so the
				// prefix of the transaction replays exactly as in the baseline.
				scopingMgr.inScope = cfRecorder.targetActive
				if *mode == "discover" {
					scopingMgr.entryState = func() *state.StateDB { return cfRecorder.targetEntryState }
				}
				cfRevertClf := newRevertClassifier(victims, attackers, nil)
				run = applyTarget(st, &header, chainConfig, gasPool, &tx, scopingMgr, cfRecorder, cfRevertClf, func(e *vm.EVM) { cfEVM = e })

				consumed := len(scopingMgr.records) > 0
				// A runtime-code intervention is consumed when the overridden
				// address is actually entered in the replayed call tree.
				if !consumed && len(targetCode) > 0 {
					for _, item := range targetCode {
						address, _, parseErr := parseOverride(item)
						if parseErr != nil {
							continue
						}
						for _, frame := range *run.frames {
							if frame.Event == "enter" && strings.EqualFold(frame.To, address.Hex()) {
								consumed = true
							}
						}
					}
				}
				var verdict frameLocalExecutionResult
				if *mode == "discover" {
					verdict = frameLocalExecutionResult{Mode: *mode, TargetFrameIndex: targetIdx, Thresholds: thresholds,
						Verdict: "DISCOVERY", InterventionSites: len(scopingMgr.records),
						VerdictReason: "reads by V inside the harm frame recorded with S0 and observed values; no intervention"}
					if targetIdx < 0 {
						verdict.ReasonCode = "no_harm_frame"
					}
				} else if targetIdx < 0 || targetIdx >= len(base.recorder.entryFrames) {
					verdict = inconclusive(frameLocalExecutionResult{Mode: *mode, TargetFrameIndex: targetIdx, Thresholds: thresholds},
						"no_harm_frame", "baseline has no victim harm frame to target")
				} else {
					in := verdictInput{
						Mode:       *mode,
						Baseline:   &base.recorder.entryFrames[targetIdx],
						CF:         cfRecorder.frameLocalResult,
						Consumed:   consumed,
						Sites:      len(scopingMgr.records),
						Thresholds: thresholds,
					}
					if in.CF != nil {
						check := checkAttackerInputs(base.recorder.entryFrames, targetIdx, cfRecorder.entryFrames, targetIdx, func(addr string) bool { return cfRecorder.isAttacker(common.HexToAddress(addr)) })
						in.Input = &check
						cfRevertClf.scopedReads = scopingMgr.records
						ro := cfRevertClf.classifyFrame(in.CF.EnterSeq)
						in.Revert = &ro
						resultOutput.RevertOrigin = &ro
					}
					verdict = computeFrameLocalVerdict(in)
				}
				resultOutput.FrameLocalResult = &verdict
				resultOutput.ScopedReads = scopingMgr.records
			} else {
				// Mode "whole-tx" or "record"
				scopingMgr := newScopingManager(*scopedPrice, victims, priceSources, scopeCallers, s0Snapshot, &header, chainConfig, lambdaPtr, valueNeutral, replacement, *priceIdentity)
				scopingMgr.readSites = sites
				scopingMgr.unscoped = *unscoped
				scopingMgr.attackers = addressSet(attackers)
				frameRec := newFrameRecorder(st, victims, attackers, false, -1, nil)
				revertClf := newRevertClassifier(victims, attackers, nil)
				run = applyTarget(st, &header, chainConfig, gasPool, &tx, scopingMgr, frameRec, revertClf, nil)

				resultOutput.EntryFrames = frameRec.entryFrames
				resultOutput.ScopedReads = scopingMgr.records
				revertClf.scopedReads = scopingMgr.records
				cfFailed := run.err != nil || run.receipt == nil || run.receipt.Status != types.ReceiptStatusSuccessful
				errText := ""
				if run.err != nil {
					errText = run.err.Error()
				}
				revertRes := revertClf.classify(cfFailed, errText)
				resultOutput.RevertOrigin = &revertRes
				if wholeTxVerdict {
					baseOK := base.err == nil && base.receipt != nil && base.receipt.Status == types.ReceiptStatusSuccessful
					var baseGas, cfGas uint64
					if base.receipt != nil {
						baseGas = base.receipt.GasUsed
					}
					if run.receipt != nil {
						cfGas = run.receipt.GasUsed
					}
					verdict := computeFrameLocalVerdict(verdictInput{
						Mode:       "whole-tx",
						Baseline:   &victimEntryFrame{FrameIndex: -1, Status: baseOK, Reverted: !baseOK, GasUsed: baseGas},
						CF:         &victimEntryFrame{FrameIndex: -1, Status: !cfFailed, Reverted: cfFailed, GasUsed: cfGas, Error: errText},
						BaseLoss:   sumLossTopLevel(base.recorder.entryFrames),
						CFLoss:     sumLossTopLevel(frameRec.entryFrames),
						Consumed:   len(scopingMgr.records) > 0,
						Sites:      len(scopingMgr.records),
						Revert:     &revertRes,
						Thresholds: thresholds,
					})
					if *unscoped {
						verdict.Mode = "whole-tx-unscoped"
					}
					resultOutput.WholeTxResult = &verdict
				}
			}

			if run.err != nil {
				runErr = run.err
			} else if run.receipt != nil {
				r.ActualGas = run.receipt.GasUsed
				r.ActualOK = run.receipt.Status == types.ReceiptStatusSuccessful
			}
			r.CallTrace = *run.frames
			r.RevertData = *run.revertData
			r.BalanceChanges = *run.balanceChanges
			r.Logs = *run.logs
			if !frameMode && run.receipt != nil && targetPrefixLogCount >= 0 {
				r.Logs = targetLogs(st.Logs(), targetPrefixLogCount)
			}
			r.OpcodeTail = *run.opcodes
		} else {
			// Prefix transactions execute without tracer
			blockContext := core.NewEVMBlockContext(&header, chainFor(&header, chainConfig), &header.Coinbase)
			evm := vm.NewEVM(blockContext, st, chainConfig, vm.Config{})
			receipt, _, applyErr := core.ApplyTransaction(evm, gasPool, st, &header, &tx)
			if applyErr != nil {
				runErr = applyErr
			} else {
				r.ActualGas = receipt.GasUsed
				r.ActualOK = receipt.Status == types.ReceiptStatusSuccessful
			}
		}
		if runErr != nil {
			r.Error = runErr.Error()
			r.GasMatch = false
			r.StatusMatch = false
		} else {
			r.GasMatch = r.ActualGas == r.ExpectedGas
			r.StatusMatch = r.ActualOK == r.ExpectedOK
		}
		resultOutput.Results = append(resultOutput.Results, r)
		resultOutput.TotalGas += r.ActualGas
		resultOutput.TotalExpect += r.ExpectedGas
		resultOutput.AllGasMatch = resultOutput.AllGasMatch && r.GasMatch
		resultOutput.AllStatus = resultOutput.AllStatus && r.StatusMatch
	}
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
		accountsOK, storageOK, proofErr := verifyProofFile(*proofPath)
		resultOutput.ProofAccounts = accountsOK
		resultOutput.ProofStorage = storageOK
		resultOutput.PrestateProofVerified = proofErr == nil
		if proofErr != nil {
			resultOutput.Note += " proof verification failed: " + proofErr.Error()
		}
	}
	// Global state root is out of scope for a transaction-relevant snapshot.
	resultOutput.Acceptance = resultOutput.AllGasMatch && resultOutput.AllStatus && resultOutput.PrestateProofVerified && len(resultOutput.Results) == len(txs)
	resultOutput.ReplayGate = resultOutput.Acceptance && resultOutput.AuthenticatedInitialState
	if resultOutput.BaselineTargetMatch != nil {
		resultOutput.ReplayGate = resultOutput.PrestateProofVerified && resultOutput.AuthenticatedInitialState && resultOutput.PrefixGasMatch &&
			*resultOutput.BaselineTargetMatch && len(resultOutput.Results) == len(txs)
	}
	resultOutput.Lean = *lean
	if *lean {
		makeLean(&resultOutput)
	}
	b, _ := json.MarshalIndent(resultOutput, "", "  ")
	if err := os.WriteFile(*outputPath, append(b, '\n'), 0644); err != nil {
		panic(err)
	}
	if !*lean {
		fmt.Println(string(b))
	}
}

func addressSet(list []string) map[common.Address]bool {
	out := make(map[common.Address]bool)
	for _, v := range list {
		if v = strings.TrimSpace(v); v != "" {
			out[common.HexToAddress(v)] = true
		}
	}
	return out
}
