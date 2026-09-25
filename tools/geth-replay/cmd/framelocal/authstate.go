package main

// Authenticated initial state, ancestor headers and pre-execution, ported
// from the main geth-replay runner so frame-local replays start from the same
// proof-bound state (not a union of per-transaction prestate snapshots).

import (
	stdcontext "context"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/consensus"
	"github.com/ethereum/go-ethereum/core"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/core/vm"
	"github.com/ethereum/go-ethereum/params"
)

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

func (c chainContext) Config() *params.ChainConfig { return c.config }

// replayChain is the block context every EVM in this run uses, so BLOCKHASH
// sees the same ancestors in the prefix, the baseline and the counterfactual.
var replayChain *chainContext

func chainFor(header *types.Header, config *params.ChainConfig) chainContext {
	if replayChain != nil {
		return *replayChain
	}
	return chainContext{header: header, config: config}
}

// buildAuthenticatedState seeds the StateDB from the EIP-1186 proofs at the
// block's parent state root for every account/slot the context touches, then
// applies pre-execution system calls (beacon roots, history storage).
func buildAuthenticatedState(contextDir, proofPath string, merged map[string]account, txs []types.Transaction,
	header *types.Header, config *params.ChainConfig) (*state.StateDB, chainContext, error) {
	chainCtx, err := loadChainContext(contextDir+"/ancestors.json", header, config)
	if err != nil {
		return nil, chainCtx, err
	}
	parent := chainCtx.byNumber[header.Number.Uint64()-1]
	if parent == nil {
		return nil, chainCtx, fmt.Errorf("proof-bound replay requires canonical parent header (ancestors.json)")
	}
	discovered := make(map[string]map[string]struct{}, len(merged))
	for address, value := range merged {
		slots := make(map[string]struct{}, len(value.Storage))
		for slot := range value.Storage {
			slots[strings.ToLower(common.HexToHash(slot).Hex())] = struct{}{}
		}
		discovered[strings.ToLower(common.HexToAddress(address).Hex())] = slots
	}
	if _, statErr := os.Stat(contextDir + "/poststates.json"); statErr == nil {
		hashes := make([]string, len(txs))
		for i := range txs {
			hashes[i] = txs[i].Hash().Hex()
		}
		poststates, err := loadPoststates(contextDir+"/poststates.json", hashes)
		if err != nil {
			return nil, chainCtx, err
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
	}
	initial, err := loadAuthenticatedInitialState(proofPath, discovered, header, parent)
	if err != nil {
		return nil, chainCtx, err
	}
	if err := requirePreExecutionAccounts(initial, header, parent, config); err != nil {
		return nil, chainCtx, err
	}
	st, err := makeState(initial.Accounts)
	if err != nil {
		return nil, chainCtx, err
	}
	preEVM := vm.NewEVM(core.NewEVMBlockContext(header, chainCtx, &header.Coinbase), st, config, vm.Config{})
	core.PreExecution(stdcontext.Background(), header.ParentBeaconRoot, parent, config, preEVM, header.Number, header.Time)
	if err := verifyPreExecutionState(st, header, parent, config); err != nil {
		return nil, chainCtx, err
	}
	return st, chainCtx, nil
}
