package main

import (
	"encoding/hex"
	"fmt"
	"math/big"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/core/vm"
	"github.com/ethereum/go-ethereum/params"
)

// Known DeFi price oracle and AMM getter 4-byte selectors
var knownPriceSelectors = map[string]string{
	"0902f1ac": "getReserves()",               // Uniswap V2 / SushiSwap
	"3850c7bd": "slot0()",                     // Uniswap V3
	"88316456": "observe(uint32[])",           // Uniswap V3 TWAP
	"feaf968c": "latestRoundData()",           // Chainlink AggregatorV3
	"50d25bcd": "latestAnswer()",              // Chainlink legacy
	"98d5fdac": "getPrice()",                  // Common Oracle
	"41976e09": "getPrice()",                  // Common Oracle
	"a48651eb": "getPrice()",                  // Common Oracle
	"415565b0": "getPrice(address)",           // Common Oracle
	"fc57d4fc": "getUnderlyingPrice(address)", // Compound / Cream / Onyx
	"182df0f5": "exchangeRateStored()",        // cToken
	"bd6d894d": "exchangeRateCurrent()",       // cToken
	"07a2d13a": "convertToAssets(uint256)",    // ERC-4626 share-to-asset conversion
}

type scopedReadRecord struct {
	Depth         int    `json:"depth"`
	Caller        string `json:"caller"`
	Target        string `json:"target"`
	Selector      string `json:"selector"`
	Function      string `json:"function,omitempty"`
	ObservedValue string `json:"observed_value,omitempty"`
	V0Value       string `json:"v0_value,omitempty"`
	ReturnedValue string `json:"returned_value,omitempty"`
	IsRevert      bool   `json:"is_revert"`
	FrameIndex    int    `json:"frame_index"`
	Seq           uint64 `json:"seq"`
	Kind          string `json:"kind"` // neutral, observed (isolation), sham
}

// Value modes for scoped reads.
const (
	valueNeutral  = "neutral"  // v0 on S0 (or explicit replacement / identity / dose)
	valueObserved = "observed" // identity stub: the value the real call returns now
	valueSham     = "sham"     // a different value at a read that is not the factor
)

type scopingManager struct {
	enabled      bool
	victims      map[common.Address]bool
	scopeCallers map[common.Address]bool
	priceSources map[common.Address]bool
	s0State      *state.StateDB
	header       *types.Header
	chainConfig  *params.ChainConfig
	records      []scopedReadRecord
	activeStubs  map[int][]stubRecord // depth -> LIFO stack of stub records
	doseLambda   *float64             // optional dose-response lambda in [0, 1]
	valueMode    string               // valueNeutral, valueObserved or valueSham
	shamScale    float64              // sham value = observed word * shamScale
	inScope      func() bool          // nil: every read; otherwise only while it returns true
	clock        *eventClock
	replacement  []byte // optional explicit replacement for scoped reads
	identity     bool   // return the first ABI argument for one-argument reads
}

type stubRecord struct {
	target       common.Address
	originalCode []byte
}

func newScopingManager(
	enabled bool,
	victims []string,
	priceSources []string,
	scopeCallers []string,
	s0State *state.StateDB,
	header *types.Header,
	chainConfig *params.ChainConfig,
	doseLambda *float64,
	valueMode string,
	replacement []byte,
	identity bool,
) *scopingManager {
	victimMap := make(map[common.Address]bool)
	for _, v := range victims {
		cleaned := strings.TrimSpace(strings.ToLower(v))
		if cleaned != "" {
			victimMap[common.HexToAddress(cleaned)] = true
		}
	}
	callerMap := make(map[common.Address]bool)
	for _, v := range scopeCallers {
		cleaned := strings.TrimSpace(strings.ToLower(v))
		if cleaned != "" {
			callerMap[common.HexToAddress(cleaned)] = true
		}
	}
	if len(callerMap) == 0 {
		for v := range victimMap {
			callerMap[v] = true
		}
	}
	priceMap := make(map[common.Address]bool)
	for _, p := range priceSources {
		cleaned := strings.TrimSpace(strings.ToLower(p))
		if cleaned != "" {
			priceMap[common.HexToAddress(cleaned)] = true
		}
	}
	return &scopingManager{
		enabled:      enabled,
		victims:      victimMap,
		scopeCallers: callerMap,
		priceSources: priceMap,
		s0State:      s0State,
		header:       header,
		chainConfig:  chainConfig,
		records:      make([]scopedReadRecord, 0),
		activeStubs:  make(map[int][]stubRecord),
		doseLambda:   doseLambda,
		valueMode:    valueMode,
		shamScale:    0.5,
		clock:        &eventClock{},
		replacement:  replacement,
		identity:     identity,
	}
}

func (m *scopingManager) isVictim(addr common.Address) bool {
	return m.victims[addr]
}

func (m *scopingManager) isPriceTarget(addr common.Address, selector string) bool {
	_, found := knownPriceSelectors[selector]
	if !found {
		return false
	}
	if len(m.priceSources) == 0 {
		return true
	}
	return m.priceSources[addr]
}

// evaluateCallOnS0 executes a static call on a copy of S0 state
func (m *scopingManager) evaluateCallOnS0(from, to common.Address, input []byte, gas uint64) ([]byte, error) {
	if m.s0State == nil {
		return nil, fmt.Errorf("S0 state is nil")
	}
	evalState := m.s0State.Copy()
	blockContext := core.NewEVMBlockContext(m.header, chainContext{header: m.header, config: m.chainConfig}, &m.header.Coinbase)
	evalEVM := vm.NewEVM(blockContext, evalState, m.chainConfig, vm.Config{})
	if gas == 0 || gas > 5_000_000 {
		gas = 5_000_000
	}
	ret, _, err := evalEVM.StaticCall(from, to, input, vm.NewGasBudget(gas, 0))
	return ret, err
}

// evaluateObserved runs the read on a copy of the current state, which is what
// the real call would return at this point.
func (m *scopingManager) evaluateObserved(from, to common.Address, input []byte, gas uint64, st *state.StateDB) ([]byte, error) {
	blockContext := core.NewEVMBlockContext(m.header, chainContext{header: m.header, config: m.chainConfig}, &m.header.Coinbase)
	evalEVM := vm.NewEVM(blockContext, st.Copy(), m.chainConfig, vm.Config{})
	if gas == 0 || gas > 5_000_000 {
		gas = 5_000_000
	}
	ret, _, err := evalEVM.StaticCall(from, to, input, vm.NewGasBudget(gas, 0))
	return ret, err
}

// perturbWords scales every 32-byte word of v by scale, and bumps a word that
// would stay unchanged (0, or 1 at scale 0.5) by one, so the sham value always
// differs from the observed value.
func perturbWords(v []byte, scale float64) []byte {
	out := make([]byte, len(v))
	copy(out, v)
	for off := 0; off+32 <= len(out); off += 32 {
		w := new(big.Int).SetBytes(out[off : off+32])
		f := new(big.Float).Mul(new(big.Float).SetInt(w), big.NewFloat(scale))
		n, _ := f.Int(nil)
		if n.Cmp(w) == 0 {
			n.Add(w, big.NewInt(1))
		}
		b := n.Bytes()
		if len(b) > 32 {
			b = b[len(b)-32:]
		}
		word := make([]byte, 32)
		copy(word[32-len(b):], b)
		copy(out[off:off+32], word)
	}
	if len(out) < 32 {
		out = append(out, 0x01)
	}
	return out
}

// makeReturnBytecode produces runtime EVM bytecode that returns the given data or reverts
func makeReturnBytecode(data []byte, isRevert bool) []byte {
	l := len(data)
	opReturn := byte(0xf3) // RETURN
	if isRevert {
		opReturn = byte(0xfd) // REVERT
	}
	if l == 0 {
		return []byte{0x60, 0x00, 0x60, 0x00, opReturn}
	}
	// Header:
	// PUSH2 <L>       61 <L_hi> <L_lo>   (3 bytes)
	// PUSH1 0x0e      60 0e              (2 bytes)
	// PUSH1 0x00      60 00              (2 bytes)
	// CODECOPY        39                 (1 byte)
	// PUSH2 <L>       61 <L_hi> <L_lo>   (3 bytes)
	// PUSH1 0x00      60 00              (2 bytes)
	// RETURN/REVERT   f3 / fd            (1 byte)
	// Total = 14 bytes (0x0e)
	header := []byte{
		0x61, byte(l >> 8), byte(l & 0xff),
		0x60, 0x0e,
		0x60, 0x00,
		0x39,
		0x61, byte(l >> 8), byte(l & 0xff),
		0x60, 0x00,
		opReturn,
	}
	return append(header, data...)
}

// interpolateDoseResponse applies v(lambda) = v_obs + lambda * (v_0 - v_obs)
// for each 32-byte word independently.
//
// Supported payload sizes:
//   - 32 bytes  — any single uint256 oracle (Chainlink latestAnswer, exchangeRateStored, …)
//   - 96 bytes  — Uniswap V2 / SushiSwap getReserves(): (reserve0, reserve1, blockTimestampLast)
//     reserve0 and reserve1 are interpolated; blockTimestampLast (last 32 bytes) is preserved
//     unchanged because it is a timestamp that must remain consistent with the real block.
//
// For any other size the function returns v0 (full neutral substitution, equivalent to lambda=1).
func interpolateDoseResponse(vObs, v0 []byte, lambda float64) []byte {
	if len(vObs) == 0 || len(vObs) != len(v0) {
		return v0
	}
	interpolate32 := func(obs, neutral []byte) []byte {
		nObs := new(big.Int).SetBytes(obs)
		n0 := new(big.Int).SetBytes(neutral)
		diff := new(big.Int).Sub(n0, nObs)
		diffFloat := new(big.Float).SetInt(diff)
		adj := new(big.Float).Mul(diffFloat, big.NewFloat(lambda))
		adjInt, _ := adj.Int(nil)
		res := new(big.Int).Add(nObs, adjInt)
		if res.Sign() < 0 {
			res.SetInt64(0)
		}
		b := res.Bytes()
		out := make([]byte, 32)
		copy(out[32-len(b):], b)
		return out
	}
	if len(v0) == 32 {
		return interpolate32(vObs, v0)
	}
	if len(v0) == 96 {
		// getReserves() → (reserve0 uint112, reserve1 uint112, blockTimestampLast uint32)
		// Each field is ABI-encoded as a 32-byte word.
		out := make([]byte, 96)
		copy(out[0:32], interpolate32(vObs[0:32], v0[0:32]))    // reserve0
		copy(out[32:64], interpolate32(vObs[32:64], v0[32:64])) // reserve1
		copy(out[64:96], v0[64:96])                             // blockTimestampLast: preserve as-is
		return out
	}
	// Fallback: full neutral substitution for non-standard response sizes.
	return v0
}

// onEnter inspects the call and applies read-site scoping if caller is a victim
func (m *scopingManager) onEnter(
	depth int,
	typ byte,
	from common.Address,
	to common.Address,
	input []byte,
	gas uint64,
	st *state.StateDB,
	currentFrameIndex int,
) {
	if !m.enabled || len(input) < 4 {
		return
	}
	if m.inScope != nil && !m.inScope() {
		return
	}
	selector := hex.EncodeToString(input[:4])
	// Neutral and observed modes act on the factor: a price read by V.
	// Sham acts on a price read by anyone else, which is not the factor.
	if m.valueMode == valueSham {
		if m.scopeCallers[from] || m.victims[from] {
			return
		}
		if _, found := knownPriceSelectors[selector]; !found {
			return
		}
	} else {
		if !m.scopeCallers[from] {
			return
		}
		if !m.isPriceTarget(to, selector) {
			return
		}
	}

	// Read neutral value v0 on S0
	v0, err := m.evaluateCallOnS0(from, to, input, gas)
	isRevert := err != nil

	// The value the real call would return here, recorded for every mode.
	vObs, obsErr := m.evaluateObserved(from, to, input, gas, st)

	var valueToReturn []byte
	switch m.valueMode {
	case valueObserved, valueSham:
		isRevert = obsErr != nil
		valueToReturn = vObs
		if m.valueMode == valueSham && !isRevert {
			valueToReturn = perturbWords(vObs, m.shamScale)
		}
	default:
		valueToReturn = v0
		if len(m.replacement) > 0 {
			valueToReturn = append([]byte(nil), m.replacement...)
		}
		if m.identity && len(input) >= 36 {
			valueToReturn = append([]byte(nil), input[4:36]...)
		}
		if m.doseLambda != nil && !isRevert {
			valueToReturn = interpolateDoseResponse(vObs, v0, *m.doseLambda)
		}
	}

	fnName := knownPriceSelectors[selector]
	record := scopedReadRecord{
		Depth:         depth,
		Caller:        from.Hex(),
		Target:        to.Hex(),
		Selector:      "0x" + selector,
		Function:      fnName,
		V0Value:       "0x" + hex.EncodeToString(v0),
		ObservedValue: "0x" + hex.EncodeToString(vObs),
		IsRevert:      isRevert,
		FrameIndex:    currentFrameIndex,
		Seq:           m.clock.now(),
		Kind:          m.valueMode,
		ReturnedValue: "0x" + hex.EncodeToString(valueToReturn),
	}
	m.records = append(m.records, record)

	// Save original code and install bytecode stub for this call.
	// Use a per-depth LIFO stack so that multiple oracle stubs active at the same
	// call depth (e.g., victim calls two price sources before returning) do not
	// clobber each other's restore record.
	origCode := st.GetCode(to)
	m.activeStubs[depth] = append(m.activeStubs[depth], stubRecord{
		target:       to,
		originalCode: origCode,
	})
	stubCode := makeReturnBytecode(valueToReturn, isRevert)
	st.SetCode(to, stubCode, tracing.CodeChangeUnspecified)
}

// onExit restores the most recently installed stub at this depth (LIFO order).
func (m *scopingManager) onExit(depth int, output []byte, st *state.StateDB) {
	stack, exists := m.activeStubs[depth]
	if !exists || len(stack) == 0 {
		return
	}
	// Pop the top of the stack (LIFO: last stub installed is first restored).
	top := stack[len(stack)-1]
	st.SetCode(top.target, top.originalCode, tracing.CodeChangeUnspecified)
	if len(stack) == 1 {
		delete(m.activeStubs, depth)
	} else {
		m.activeStubs[depth] = stack[:len(stack)-1]
	}
}
