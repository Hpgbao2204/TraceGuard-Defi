package main

import (
	"testing"

	"github.com/ethereum/go-ethereum/common"
)

// A victim that catches a reverting sub-call (a staticcall into attacker code) and then reverts with its
// own message is the origin; the caught child is not on the chain of uncaught reverts.
func TestClassifyStopsAtCaughtRevert(t *testing.T) {
	victim := common.HexToAddress("0x1")
	attacker := common.HexToAddress("0x2")
	own := []byte("guard message")
	caught := &callTreeNode{To: attacker, Reverted: true, Output: nil, Context: attacker}
	origin := &callTreeNode{To: victim, Reverted: true, Output: own, Children: []*callTreeNode{caught}, Context: victim}
	root := &callTreeNode{To: attacker, Reverted: true, Output: own, Children: []*callTreeNode{origin}, Context: attacker}
	c := newRevertClassifier([]string{victim.Hex()}, []string{attacker.Hex()}, nil)
	got := c.classifyFrom(root, "")
	if got.OriginClass != "victim" || len(got.RevertChain) != 2 {
		t.Fatalf("origin class %q chain %d, want victim at depth 2", got.OriginClass, len(got.RevertChain))
	}
}

// Revert data re-raised unchanged by every ancestor still leads to the deepest frame.
func TestClassifyFollowsBubbledRevert(t *testing.T) {
	victim := common.HexToAddress("0x1")
	attacker := common.HexToAddress("0x2")
	data := []byte("deep")
	deep := &callTreeNode{To: victim, Reverted: true, Output: data, Context: victim}
	mid := &callTreeNode{To: attacker, Reverted: true, Output: data, Children: []*callTreeNode{deep}, Context: attacker}
	root := &callTreeNode{To: attacker, Reverted: true, Output: data, Children: []*callTreeNode{mid}, Context: attacker}
	c := newRevertClassifier([]string{victim.Hex()}, []string{attacker.Hex()}, nil)
	if got := c.classifyFrom(root, ""); got.OriginClass != "victim" || len(got.RevertChain) != 3 {
		t.Fatalf("origin class %q chain %d, want victim at depth 3", got.OriginClass, len(got.RevertChain))
	}
}
