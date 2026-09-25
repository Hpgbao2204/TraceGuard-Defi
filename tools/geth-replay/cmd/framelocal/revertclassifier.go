package main

import (
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"math/big"
	"strings"

	"github.com/ethereum/go-ethereum/common"
)

type revertOriginResult struct {
	HasRevert                  bool   `json:"has_revert"`
	DeepestFrameIndex          int    `json:"deepest_frame_index"`
	OriginAddress              string `json:"origin_address,omitempty"`
	OriginClass                string `json:"origin_class,omitempty"` // "victim", "attacker", "third_party"
	ErrorReason                string `json:"error_reason,omitempty"`
	IntervenedReadBeforeRevert bool   `json:"intervened_read_before_revert"`
	CandidateVerdict           string `json:"candidate_verdict,omitempty"`
	// MultipleRevertsAtDepth is true when the greedy traversal encountered >1 reverted
	// sibling children at some level. This can occur with Solidity try/catch patterns.
	// When true, the assigned origin_class may not be unique; treat with caution.
	MultipleRevertsAtDepth bool `json:"multiple_reverts_at_depth,omitempty"`

	// Where and why the origin frame reverted, for guard-type classification.
	OriginCaller   string      `json:"origin_caller,omitempty"`
	OriginSelector string      `json:"origin_selector,omitempty"` // function of the reverting frame
	RevertKind     string      `json:"revert_kind,omitempty"`     // error_string, panic, custom_error, empty, halt
	RevertMessage  string      `json:"revert_message,omitempty"`  // decoded Error(string), panic code, or error selector
	RevertData     string      `json:"revert_data,omitempty"`     // raw revert output of the origin frame (capped)
	RevertChain    []revertHop `json:"revert_chain,omitempty"`    // reverted frames from the start frame down to the origin
}

// revertHop is one reverted frame on the path to the revert origin.
type revertHop struct {
	Address  string `json:"address"`
	Selector string `json:"selector,omitempty"`
	Class    string `json:"class"`
	Message  string `json:"message,omitempty"`
}

const maxRevertDataBytes = 1024

// decodeRevert classifies revert output: Error(string), Panic(uint256), a
// custom error selector, or empty. A frame that halted without REVERT (out of
// gas, invalid opcode) reports kind "halt" with the EVM error.
func decodeRevert(output []byte, evmErr string) (kind, msg string) {
	if len(output) == 0 {
		if evmErr != "" && !strings.Contains(evmErr, "execution reverted") {
			return "halt", evmErr
		}
		return "empty", ""
	}
	if len(output) < 4 {
		return "custom_error", "0x" + hex.EncodeToString(output)
	}
	sel := hex.EncodeToString(output[:4])
	body := output[4:]
	switch sel {
	case "08c379a0": // Error(string)
		if len(body) >= 64 {
			off := new(big.Int).SetBytes(body[:32])
			if off.IsUint64() && off.Uint64()+32 <= uint64(len(body)) {
				o := off.Uint64()
				n := new(big.Int).SetBytes(body[o : o+32])
				if n.IsUint64() && o+32+n.Uint64() <= uint64(len(body)) {
					return "error_string", string(body[o+32 : o+32+n.Uint64()])
				}
			}
		}
		return "error_string", "<undecodable>"
	case "4e487b71": // Panic(uint256)
		if len(body) >= 32 {
			return "panic", fmt.Sprintf("0x%02x %s", binary.BigEndian.Uint64(body[24:32]), panicName(binary.BigEndian.Uint64(body[24:32])))
		}
		return "panic", "<undecodable>"
	}
	return "custom_error", "0x" + sel
}

func panicName(code uint64) string {
	switch code {
	case 0x01:
		return "assert"
	case 0x11:
		return "arithmetic_overflow"
	case 0x12:
		return "division_by_zero"
	case 0x21:
		return "enum_conversion"
	case 0x22:
		return "storage_encoding"
	case 0x31:
		return "pop_empty_array"
	case 0x32:
		return "array_out_of_bounds"
	case 0x41:
		return "out_of_memory"
	case 0x51:
		return "zero_function_pointer"
	}
	return "unknown"
}

type callTreeNode struct {
	Index       int
	Depth       int
	From        common.Address
	To          common.Address
	Reverted    bool
	Error       string
	ParentIndex int
	Children    []*callTreeNode
	EnterSeq    uint64
	ExitSeq     uint64
	Selector    string
	Output      []byte
}

type revertClassifier struct {
	victims      map[common.Address]bool
	attackers    map[common.Address]bool
	scopedReads  []scopedReadRecord
	nodes        []*callTreeNode
	currentStack []*callTreeNode
	clock        *eventClock
}

func newRevertClassifier(
	victims []string,
	attackers []string,
	scopedReads []scopedReadRecord,
) *revertClassifier {
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
	return &revertClassifier{
		victims:      victimMap,
		attackers:    attackerMap,
		scopedReads:  scopedReads,
		nodes:        make([]*callTreeNode, 0),
		currentStack: make([]*callTreeNode, 0),
		clock:        &eventClock{},
	}
}

func (c *revertClassifier) onEnter(depth int, from, to common.Address, input []byte) {
	nodeIdx := len(c.nodes)
	parentIdx := -1
	var parentNode *callTreeNode
	if len(c.currentStack) > 0 {
		parentNode = c.currentStack[len(c.currentStack)-1]
		parentIdx = parentNode.Index
	}
	node := &callTreeNode{
		Index:       nodeIdx,
		Depth:       depth,
		From:        from,
		To:          to,
		ParentIndex: parentIdx,
		Children:    make([]*callTreeNode, 0),
		EnterSeq:    c.clock.now(),
	}
	if len(input) >= 4 {
		node.Selector = "0x" + hex.EncodeToString(input[:4])
	}
	c.nodes = append(c.nodes, node)
	if parentNode != nil {
		parentNode.Children = append(parentNode.Children, node)
	}
	c.currentStack = append(c.currentStack, node)
}

func (c *revertClassifier) onExit(depth int, output []byte, err error, reverted bool) {
	if len(c.currentStack) > 0 {
		top := c.currentStack[len(c.currentStack)-1]
		if top.Depth == depth {
			top.Reverted = reverted
			top.ExitSeq = c.clock.now()
			if err != nil {
				top.Error = err.Error()
			}
			if reverted && len(output) > 0 {
				n := len(output)
				if n > maxRevertDataBytes {
					n = maxRevertDataBytes
				}
				top.Output = append([]byte(nil), output[:n]...)
			}
			c.currentStack = c.currentStack[:len(c.currentStack)-1]
		}
	}
}

func (c *revertClassifier) classifyOrigin(addr common.Address) string {
	if c.victims[addr] {
		return "victim"
	}
	if c.attackers[addr] {
		return "attacker"
	}
	return "third_party"
}

// classify traverses down the unhandled revert chain to find the deepest frame that raised REVERT
func (c *revertClassifier) classify(txFailed bool, txRevertReason string) revertOriginResult {
	if !txFailed && len(c.nodes) > 0 && !c.nodes[0].Reverted {
		return revertOriginResult{
			HasRevert: false,
		}
	}
	if len(c.nodes) == 0 {
		return revertOriginResult{
			HasRevert:   txFailed,
			ErrorReason: txRevertReason,
			OriginClass: "unknown",
		}
	}

	return c.classifyFrom(c.nodes[0], txRevertReason)
}

// classifyFrame attributes the revert of the call that started at enterSeq
// (the target entry frame in frame-local mode). Only scoped reads inside that
// frame and before the revert count.
func (c *revertClassifier) classifyFrame(enterSeq uint64) revertOriginResult {
	for _, n := range c.nodes {
		if n.EnterSeq == enterSeq {
			if !n.Reverted {
				return revertOriginResult{HasRevert: false}
			}
			return c.classifyFrom(n, "")
		}
	}
	return revertOriginResult{HasRevert: false, OriginClass: "unknown"}
}

func (c *revertClassifier) classifyFrom(start *callTreeNode, txRevertReason string) revertOriginResult {
	// NOTE: This traversal is greedy — it follows the *first* reverted child at each
	// level. In Solidity try/catch patterns, multiple siblings may have reverted;
	// the MultipleRevertsAtDepth field is set to signal such ambiguity.
	curr := start
	multipleRevertsAtDepth := false
	hop := func(n *callTreeNode) revertHop {
		_, m := decodeRevert(n.Output, n.Error)
		return revertHop{Address: n.To.Hex(), Selector: n.Selector, Class: c.classifyOrigin(n.To), Message: m}
	}
	chain := []revertHop{hop(start)}
	for {
		var revertedChild *callTreeNode
		revertedCount := 0
		for _, child := range curr.Children {
			if child.Reverted {
				revertedCount++
				if revertedChild == nil {
					revertedChild = child
				}
			}
		}
		if revertedCount > 1 {
			multipleRevertsAtDepth = true
		}
		if revertedChild == nil {
			break
		}
		curr = revertedChild
		chain = append(chain, hop(curr))
	}

	originClass := c.classifyOrigin(curr.To)
	errorMsg := curr.Error
	if errorMsg == "" {
		errorMsg = txRevertReason
	}

	// A scoped read counts only if it happened inside the start frame and
	// before the origin frame reverted (event-clock order, not call depth).
	// A frame that never exited (ExitSeq 0) is treated as still open.
	readBeforeRevert := false
	revertAt := curr.ExitSeq
	if revertAt == 0 {
		revertAt = ^uint64(0)
	}
	for _, sr := range c.scopedReads {
		if sr.Seq > start.EnterSeq && sr.Seq < revertAt {
			readBeforeRevert = true
			break
		}
	}

	candidateVerdict := ""
	if originClass == "victim" {
		if readBeforeRevert {
			candidateVerdict = "CAUSE_BLOCKED"
		} else {
			candidateVerdict = "VICTIM_INTERNAL_REVERT"
		}
	} else if originClass == "attacker" {
		candidateVerdict = "REVERT_CONFOUND_ATTACKER"
	} else {
		candidateVerdict = "REVERT_CONFOUND_THIRD_PARTY"
	}

	kind, msg := decodeRevert(curr.Output, curr.Error)
	data := ""
	if len(curr.Output) > 0 {
		data = "0x" + hex.EncodeToString(curr.Output)
	}
	return revertOriginResult{
		OriginCaller:               curr.From.Hex(),
		OriginSelector:             curr.Selector,
		RevertKind:                 kind,
		RevertMessage:              msg,
		RevertData:                 data,
		RevertChain:                chain,
		HasRevert:                  true,
		DeepestFrameIndex:          curr.Index,
		OriginAddress:              curr.To.Hex(),
		OriginClass:                originClass,
		ErrorReason:                errorMsg,
		IntervenedReadBeforeRevert: readBeforeRevert,
		CandidateVerdict:           candidateVerdict,
		MultipleRevertsAtDepth:     multipleRevertsAtDepth,
	}
}
