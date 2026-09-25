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
	"70a08231": "balanceOf(address)",          // Pool balance as price
}

type scopedReadRecord struct {
	Depth         int    `json:"depth"`
	Caller        string `json:"caller"`
	Target        string `json:"target"`
	Selector      string `json:"selector"`
	Function      string `json:"function,omitempty"`
	ObservedValue string `json:"observed_value,omitempty"`
	V0Value       string `json:"v0_value,omitempty"`
	IsRevert      bool   `json:"is_revert"`
	FrameIndex    int    `json:"frame_index"`
}

type scopingManager struct {
	enabled      bool
	victims      map[common.Address]bool
	priceSources map[common.Address]bool
	s0State      *state.StateDB
	header       *types.Header
	chainConfig  *params.ChainConfig
	records      []scopedReadRecord
	activeStubs  map[int][]stubRecord // depth -> LIFO stack of stub records
	doseLambda   *float64             // optional dose-response lambda in [0, 1]
	shamMode     bool                 // return observed value instead of v0
}

type stubRecord struct {
	target       common.Address
	originalCode []byte
}

func newScopingManager(
	enabled bool,
	victims []string,
	priceSources []string,
	s0State *state.StateDB,
	header *types.Header,
	chainConfig *params.ChainConfig,
	doseLambda *float64,
	shamMode bool,
) *scopingManager {
	victimMap := make(map[common.Address]bool)
	for _, v := range victims {
		cleaned := strings.TrimSpace(strings.ToLower(v))
		if cleaned != "" {
			victimMap[common.HexToAddress(cleaned)] = true
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
		priceSources: priceMap,
		s0State:      s0State,
		header:       header,
		chainConfig:  chainConfig,
		records:      make([]scopedReadRecord, 0),
		activeStubs:  make(map[int][]stubRecord),
		doseLambda:   doseLambda,
		shamMode:     shamMode,
	}
}

func (m *scopingManager) isVictim(addr common.Address) bool {
	return m.victims[addr]
}

func (m *scopingManager) isPriceTarget(addr common.Address, selector string) bool {
	if m.priceSources[addr] {
		return true
	}
	_, found := knownPriceSelectors[selector]
	return found
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
	// Condition 1: caller must be in victim set V
	if !m.isVictim(from) {
		return
	}
	selector := hex.EncodeToString(input[:4])
	// Condition 2: target or selector must be a price source
	if !m.isPriceTarget(to, selector) {
		return
	}

	// Read neutral value v0 on S0
	v0, err := m.evaluateCallOnS0(from, to, input, gas)
	isRevert := err != nil

	valueToReturn := v0
	if m.doseLambda != nil && !isRevert {
		// Evaluate observed value on current dirty state
		blockContext := core.NewEVMBlockContext(m.header, chainContext{header: m.header, config: m.chainConfig}, &m.header.Coinbase)
		evalEVM := vm.NewEVM(blockContext, st.Copy(), m.chainConfig, vm.Config{})
		vObs, _, _ := evalEVM.StaticCall(from, to, input, vm.NewGasBudget(gas, 0))
		if m.shamMode {
			valueToReturn = vObs
		} else {
			valueToReturn = interpolateDoseResponse(vObs, v0, *m.doseLambda)
		}
	} else if m.shamMode {
		blockContext := core.NewEVMBlockContext(m.header, chainContext{header: m.header, config: m.chainConfig}, &m.header.Coinbase)
		evalEVM := vm.NewEVM(blockContext, st.Copy(), m.chainConfig, vm.Config{})
		vObs, _, _ := evalEVM.StaticCall(from, to, input, vm.NewGasBudget(gas, 0))
		valueToReturn = vObs
	}

	fnName := knownPriceSelectors[selector]
	record := scopedReadRecord{
		Depth:      depth,
		Caller:     from.Hex(),
		Target:     to.Hex(),
		Selector:   "0x" + selector,
		Function:   fnName,
		V0Value:    "0x" + hex.EncodeToString(v0),
		IsRevert:   isRevert,
		FrameIndex: currentFrameIndex,
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

	// Update observed value in the last record at this depth if not yet populated.
	for i := len(m.records) - 1; i >= 0; i-- {
		if m.records[i].Depth == depth && m.records[i].ObservedValue == "" {
			m.records[i].ObservedValue = "0x" + hex.EncodeToString(output)
			break
		}
	}
}
