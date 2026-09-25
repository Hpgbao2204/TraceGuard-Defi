package main

import (
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
	MultipleRevertsAtDepth     bool   `json:"multiple_reverts_at_depth,omitempty"`
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
}

type revertClassifier struct {
	victims      map[common.Address]bool
	attackers    map[common.Address]bool
	scopedReads  []scopedReadRecord
	nodes        []*callTreeNode
	currentStack []*callTreeNode
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
	}
}

func (c *revertClassifier) onEnter(depth int, from, to common.Address) {
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
	}
	c.nodes = append(c.nodes, node)
	if parentNode != nil {
		parentNode.Children = append(parentNode.Children, node)
	}
	c.currentStack = append(c.currentStack, node)
}

func (c *revertClassifier) onExit(depth int, err error, reverted bool) {
	if len(c.currentStack) > 0 {
		top := c.currentStack[len(c.currentStack)-1]
		if top.Depth == depth {
			top.Reverted = reverted
			if err != nil {
				top.Error = err.Error()
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

	// Start from root node.
	// NOTE: This traversal is greedy — it follows the *first* reverted child at each
	// level. In Solidity try/catch patterns, multiple siblings may have reverted;
	// the MultipleRevertsAtDepth field is set to signal such ambiguity.
	curr := c.nodes[0]
	multipleRevertsAtDepth := false
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
	}

	originClass := c.classifyOrigin(curr.To)
	errorMsg := curr.Error
	if errorMsg == "" {
		errorMsg = txRevertReason
	}

	// Check if any scoped read happened before this revert
	readBeforeRevert := false
	for _, sr := range c.scopedReads {
		if sr.Depth <= curr.Depth {
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

	return revertOriginResult{
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

