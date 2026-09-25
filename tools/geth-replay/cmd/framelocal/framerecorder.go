package main

import (
	"encoding/hex"
	"math/big"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/types"
)

var transferEventTopic = common.HexToHash("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef")

type attackerCallback struct {
	Depth    int    `json:"depth"`
	From     string `json:"from"`
	To       string `json:"to"`
	Input    string `json:"input"`
	Output   string `json:"output,omitempty"`
	GasUsed  uint64 `json:"gas_used"`
	Error    string `json:"error,omitempty"`
	Reverted bool   `json:"reverted"`
}

type victimEntryFrame struct {
	FrameIndex        int                `json:"frame_index"`
	Depth             int                `json:"depth"`
	Caller            string             `json:"caller"`
	Target            string             `json:"target"`
	Input             string             `json:"input"`
	Gas               uint64             `json:"gas"`
	Value             string             `json:"value"`
	GasUsed           uint64             `json:"gas_used"`
	Status            bool               `json:"status"`
	Reverted          bool               `json:"reverted"`
	Error             string             `json:"error,omitempty"`
	Logs              []*types.Log       `json:"logs,omitempty"`
	BalanceChanges    []balanceChange    `json:"balance_changes,omitempty"`
	AssetDeltas       map[string]string  `json:"asset_deltas"` // token/native address -> net outflow string
	IsHarmFrame       bool               `json:"is_harm_frame"`
	AttackerCallbacks []attackerCallback `json:"attacker_callbacks,omitempty"`
	// ParentFrame is the entry frame that was active when this one was entered
	// (-1 for a top-level entry). EnterSeq/ExitSeq are positions on the shared
	// event clock, so reads, reverts and frames can be ordered in time.
	ParentFrame int    `json:"parent_frame"`
	EnterSeq    uint64 `json:"enter_seq"`
	ExitSeq     uint64 `json:"exit_seq"`
	LogDigest   string `json:"log_digest,omitempty"`

	startLogCount int
	entryBalances map[common.Address]*big.Int
}

type frameRecorder struct {
	st               *state.StateDB
	victims          map[common.Address]bool
	attackers        map[common.Address]bool
	entryFrames      []victimEntryFrame
	activeEntryStack []int // indices into entryFrames

	// Nested callbacks tracking
	activeCallbackDepth int
	inCallback          bool

	// Frame-local abort hook
	isFrameLocal     bool
	targetFrameIndex int
	cancelFunc       func()
	frameLocalResult *victimEntryFrame
	clock            *eventClock
}

func newFrameRecorder(
	st *state.StateDB,
	victims []string,
	attackers []string,
	isFrameLocal bool,
	targetFrameIndex int,
	cancelFunc func(),
) *frameRecorder {
	victimMap := make(map[common.Address]bool)
	for _, v := range victims {
		cleaned := strings.TrimSpace(strings.ToLower(v))
		if cleaned != "" {
			victimMap[common.HexToAddress(cleaned)] = true
		}
	}
	attackerMap := make(map[common.Address]bool)
	for _, a := range attackers {
		cleaned := strings.TrimSpace(strings.ToLower(a))
		if cleaned != "" {
			attackerMap[common.HexToAddress(cleaned)] = true
		}
	}
	return &frameRecorder{
		st:                  st,
		victims:             victimMap,
		attackers:           attackerMap,
		entryFrames:         make([]victimEntryFrame, 0),
		activeEntryStack:    make([]int, 0),
		activeCallbackDepth: -1,
		inCallback:          false,
		isFrameLocal:        isFrameLocal,
		targetFrameIndex:    targetFrameIndex,
		cancelFunc:          cancelFunc,
		clock:               &eventClock{},
	}
}

// targetActive reports whether the target entry frame is currently executing
// (it is on the active entry stack, possibly with nested entries above it).
func (r *frameRecorder) targetActive() bool {
	for _, idx := range r.activeEntryStack {
		if idx == r.targetFrameIndex {
			return true
		}
	}
	return false
}

func (r *frameRecorder) isVictim(addr common.Address) bool {
	return r.victims[addr]
}

func (r *frameRecorder) isAttacker(addr common.Address) bool {
	return r.attackers[addr]
}

func (r *frameRecorder) currentFrameIndex() int {
	if len(r.activeEntryStack) > 0 {
		return r.activeEntryStack[len(r.activeEntryStack)-1]
	}
	return -1
}

func (r *frameRecorder) onEnter(
	depth int,
	typ byte,
	from common.Address,
	to common.Address,
	input []byte,
	gas uint64,
	value *big.Int,
) {
	// Detect entry frame into victim V from outside V
	if r.isVictim(to) && !r.isVictim(from) {
		fIdx := len(r.entryFrames)
		entryBals := make(map[common.Address]*big.Int)
		startLogCount := 0
		if r.st != nil {
			startLogCount = len(r.st.Logs())
			for v := range r.victims {
				bal := r.st.GetBalance(v)
				if bal != nil {
					entryBals[v] = bal.ToBig()
				}
			}
			for a := range r.attackers {
				bal := r.st.GetBalance(a)
				if bal != nil {
					entryBals[a] = bal.ToBig()
				}
			}
		}
		frame := victimEntryFrame{
			FrameIndex:        fIdx,
			ParentFrame:       r.currentFrameIndex(),
			EnterSeq:          r.clock.now(),
			Depth:             depth,
			Caller:            from.Hex(),
			Target:            to.Hex(),
			Input:             "0x" + hex.EncodeToString(input),
			Gas:               gas,
			Value:             value.String(),
			Status:            true,
			Logs:              make([]*types.Log, 0),
			BalanceChanges:    make([]balanceChange, 0),
			AssetDeltas:       make(map[string]string),
			AttackerCallbacks: make([]attackerCallback, 0),
			startLogCount:     startLogCount,
			entryBalances:     entryBals,
		}
		r.entryFrames = append(r.entryFrames, frame)
		r.activeEntryStack = append(r.activeEntryStack, fIdx)
		return
	}

	// Detect callback from V into Attacker A inside an active entry frame
	if len(r.activeEntryStack) > 0 && r.isVictim(from) && r.isAttacker(to) {
		r.inCallback = true
		r.activeCallbackDepth = depth
		currIdx := r.currentFrameIndex()
		r.entryFrames[currIdx].AttackerCallbacks = append(
			r.entryFrames[currIdx].AttackerCallbacks,
			attackerCallback{
				Depth: depth,
				From:  from.Hex(),
				To:    to.Hex(),
				Input: "0x" + hex.EncodeToString(input),
			},
		)
	}
}

// onLog is only used without a StateDB. With a StateDB the frame's logs are
// taken from st.Logs() at frame exit, which already excludes logs of reverted
// sub-calls; collecting both would count every Transfer twice.
func (r *frameRecorder) onLog(log *types.Log) {
	if r.st == nil && len(r.activeEntryStack) > 0 {
		currIdx := r.currentFrameIndex()
		r.entryFrames[currIdx].Logs = append(r.entryFrames[currIdx].Logs, log)
	}
}

func (r *frameRecorder) onBalanceChange(addr common.Address, prev, curr *big.Int) {
	if len(r.activeEntryStack) > 0 {
		currIdx := r.currentFrameIndex()
		r.entryFrames[currIdx].BalanceChanges = append(
			r.entryFrames[currIdx].BalanceChanges,
			balanceChange{
				Address:  addr.Hex(),
				Previous: prev.String(),
				Current:  curr.String(),
			},
		)
	}
}

func (r *frameRecorder) onExit(
	depth int,
	output []byte,
	gasUsed uint64,
	err error,
	reverted bool,
) {
	// Handle exiting attacker callback
	if r.inCallback && depth == r.activeCallbackDepth {
		r.inCallback = false
		r.activeCallbackDepth = -1
		if len(r.activeEntryStack) > 0 {
			currIdx := r.currentFrameIndex()
			cbs := r.entryFrames[currIdx].AttackerCallbacks
			if len(cbs) > 0 {
				last := len(cbs) - 1
				cbs[last].Output = "0x" + hex.EncodeToString(output)
				cbs[last].GasUsed = gasUsed
				cbs[last].Reverted = reverted
				if err != nil {
					cbs[last].Error = err.Error()
				}
				r.entryFrames[currIdx].AttackerCallbacks = cbs
			}
		}
	}

	// Handle exiting victim entry frame
	if len(r.activeEntryStack) > 0 {
		currIdx := r.currentFrameIndex()
		if r.entryFrames[currIdx].Depth == depth {
			r.entryFrames[currIdx].ExitSeq = r.clock.now()
			r.entryFrames[currIdx].GasUsed = gasUsed
			r.entryFrames[currIdx].Reverted = reverted
			r.entryFrames[currIdx].Status = !reverted && err == nil
			if err != nil {
				r.entryFrames[currIdx].Error = err.Error()
			}
			// Compute victim asset outflow deltas inside this frame
			r.computeAssetDeltas(currIdx)

			// Pop from active entry stack
			r.activeEntryStack = r.activeEntryStack[:len(r.activeEntryStack)-1]

			// If running in frame-local mode and this was our target frame, capture and abort!
			if r.isFrameLocal && currIdx == r.targetFrameIndex {
				res := r.entryFrames[currIdx]
				r.frameLocalResult = &res
				if r.cancelFunc != nil {
					r.cancelFunc()
				}
			}
		}
	}
}

// computeAssetDeltas computes net asset outflows from V in frame currIdx
func (r *frameRecorder) computeAssetDeltas(frameIdx int) {
	frame := &r.entryFrames[frameIdx]
	deltas := make(map[string]*big.Int) // asset -> net outflow (positive = loss for V)

	// Collect logs emitted inside this frame directly from StateDB if available
	if r.st != nil && frame.startLogCount <= len(r.st.Logs()) {
		frame.Logs = append([]*types.Log(nil), r.st.Logs()[frame.startLogCount:]...)
	}
	frame.LogDigest = logsDigest(frame.Logs)

	// 1. Native ETH balance changes for victims and attacker gains
	if r.st != nil && frame.entryBalances != nil {
		for v := range r.victims {
			prevBal := frame.entryBalances[v]
			if prevBal == nil {
				continue
			}
			currBalObj := r.st.GetBalance(v)
			var currBal *big.Int
			if currBalObj != nil {
				currBal = currBalObj.ToBig()
			} else {
				currBal = big.NewInt(0)
			}
			outflow := new(big.Int).Sub(prevBal, currBal)
			if outflow.Sign() != 0 {
				if deltas["native"] == nil {
					deltas["native"] = new(big.Int)
				}
				deltas["native"].Add(deltas["native"], outflow)
			}
		}
		// Also check ETH flow directly into attackers
		for a := range r.attackers {
			prevBal := frame.entryBalances[a]
			if prevBal == nil {
				continue
			}
			currBalObj := r.st.GetBalance(a)
			var currBal *big.Int
			if currBalObj != nil {
				currBal = currBalObj.ToBig()
			} else {
				currBal = big.NewInt(0)
			}
			attackerGain := new(big.Int).Sub(currBal, prevBal)
			if attackerGain.Sign() > 0 && deltas["native"] == nil {
				deltas["native"] = attackerGain
			}
		}
	} else {
		for _, bc := range frame.BalanceChanges {
			addr := common.HexToAddress(bc.Address)
			if r.isVictim(addr) {
				prev := quantity(bc.Previous)
				curr := quantity(bc.Current)
				outflow := new(big.Int).Sub(prev, curr)
				if deltas["native"] == nil {
					deltas["native"] = new(big.Int)
				}
				deltas["native"].Add(deltas["native"], outflow)
			}
		}
	}

	// 2. ERC-20 Transfer logs
	for _, log := range frame.Logs {
		if len(log.Topics) >= 3 && log.Topics[0] == transferEventTopic {
			tokenAddr := strings.ToLower(log.Address.Hex())
			fromAddr := common.BytesToAddress(log.Topics[1].Bytes())
			toAddr := common.BytesToAddress(log.Topics[2].Bytes())
			val := new(big.Int).SetBytes(log.Data)

			isOutflow := (r.isVictim(fromAddr) || r.isAttacker(toAddr)) && !r.isVictim(toAddr) && !r.isAttacker(fromAddr)
			isInflow := (r.isVictim(toAddr) || r.isAttacker(fromAddr)) && !r.isVictim(fromAddr) && !r.isAttacker(toAddr)

			if isOutflow {
				// Outflow from victim protocol to outside or attacker
				if deltas[tokenAddr] == nil {
					deltas[tokenAddr] = new(big.Int)
				}
				deltas[tokenAddr].Add(deltas[tokenAddr], val)
			} else if isInflow {
				// Inflow into victim protocol from outside
				if deltas[tokenAddr] == nil {
					deltas[tokenAddr] = new(big.Int)
				}
				deltas[tokenAddr].Sub(deltas[tokenAddr], val)
			}
		}
	}

	// Serialize deltas and determine if this is a harm frame
	hasHarm := false
	for asset, delta := range deltas {
		if delta.Sign() != 0 {
			frame.AssetDeltas[asset] = delta.String()
			if delta.Sign() > 0 {
				hasHarm = true
			}
		}
	}
	frame.IsHarmFrame = hasHarm
}
