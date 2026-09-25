package main

import (
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/core/vm"
	"github.com/holiman/uint256"
)

type testOpcodeContext struct {
	memory []byte
	stack  []uint256.Int
	caller common.Address
	addr   common.Address
	value  *uint256.Int
	input  []byte
}

func (c testOpcodeContext) MemoryData() []byte       { return c.memory }
func (c testOpcodeContext) StackData() []uint256.Int { return c.stack }
func (c testOpcodeContext) Caller() common.Address   { return c.caller }
func (c testOpcodeContext) Address() common.Address  { return c.addr }
func (c testOpcodeContext) CallValue() *uint256.Int  { return c.value }
func (c testOpcodeContext) CallInput() []byte        { return c.input }
func (c testOpcodeContext) ContractCode() []byte     { return []byte{byte(vm.PUSH1)} }

func TestNewCallHooksEmitsAuthenticatedOpcodeContext(t *testing.T) {
	hooks, frames, _, _, _, _, opcodes := newCallHooks(false)
	from := common.HexToAddress("0x1000000000000000000000000000000000000001")
	to := common.HexToAddress("0x2000000000000000000000000000000000000002")
	hooks.OnEnter(0, byte(vm.CALL), from, to, []byte{0xaa}, 100000, uint256.NewInt(7).ToBig())

	stack := make([]uint256.Int, 7)
	for i := range stack {
		stack[i].SetUint64(uint64(i + 1))
	}
	ctx := testOpcodeContext{
		memory: make([]byte, 64), stack: stack, caller: from, addr: to,
		value: uint256.NewInt(7), input: []byte{0xbb, 0xcc},
	}
	ctx.memory[32] = 0x42
	hooks.OnOpcode(12, byte(vm.CALL), 90000, 700, ctx, []byte{0xde, 0xad}, 1, nil)

	if len(*frames) != 1 || (*frames)[0].FrameID == "" {
		t.Fatalf("missing stable frame identity: %+v", *frames)
	}
	if len(*opcodes) != 1 {
		t.Fatalf("got %d opcode events", len(*opcodes))
	}
	e := (*opcodes)[0]
	if e.FrameID != (*frames)[0].FrameID || e.Caller != from.Hex() || e.Address != to.Hex() {
		t.Fatalf("frame/address provenance not preserved: %+v", e)
	}
	if len(e.Stack) != 7 || e.ReturnData != "" || e.CallInput != "0xbbcc" {
		t.Fatalf("value provenance incomplete: %+v", e)
	}
	if e.Memory == "" || e.StorageContext != to.Hex() {
		t.Fatalf("memory/storage context missing: %+v", e)
	}
}

func TestNewCallHooksRecordsStorageOperands(t *testing.T) {
	hooks, _, _, _, storageChanges, _, opcodes := newCallHooks(false)
	hooks.OnEnter(0, byte(vm.CALL), common.Address{}, common.Address{}, nil, 1, uint256.NewInt(0).ToBig())
	stack := make([]uint256.Int, 2)
	stack[0].SetUint64(0x99)
	stack[1].SetUint64(0x77)
	ctx := testOpcodeContext{stack: stack, caller: common.Address{}, addr: common.HexToAddress("0x3"), value: uint256.NewInt(0)}
	hooks.OnOpcode(1, byte(vm.SSTORE), 1, 1, ctx, nil, 1, nil)
	hooks.OnStorageChange(common.HexToAddress("0x3"), common.HexToHash("0x77"), common.HexToHash("0x1"), common.HexToHash("0x2"))
	if len(*opcodes) != 1 || (*opcodes)[0].StorageSlot != "119" || (*opcodes)[0].StorageValue != "153" {
		t.Fatalf("unexpected SSTORE operands: %+v", *opcodes)
	}
	if len(*storageChanges) != 1 || (*storageChanges)[0].Previous != common.HexToHash("0x1").Hex() {
		t.Fatalf("storage write telemetry missing: %+v", *storageChanges)
	}
}

func TestNewCallHooksLinksChildReturnToParent(t *testing.T) {
	hooks, _, _, _, _, _, opcodes := newCallHooks(false)
	root := common.HexToAddress("0x10")
	child := common.HexToAddress("0x20")
	zero := uint256.NewInt(0).ToBig()
	hooks.OnEnter(0, byte(vm.CALL), root, root, nil, 100, zero)
	hooks.OnEnter(1, byte(vm.STATICCALL), root, child, []byte{0x01}, 90, zero)
	hooks.OnExit(1, []byte{0xde, 0xad}, 3, nil, false)
	hooks.OnOpcode(1, byte(vm.PUSH1), 80, 3, testOpcodeContext{caller: root, addr: root, value: uint256.NewInt(0)}, nil, 1, nil)
	if len(*opcodes) != 1 || (*opcodes)[0].ReturnData != "0xdead" || (*opcodes)[0].ReturnDataSource == "" {
		t.Fatalf("child return was not linked to parent: %+v", *opcodes)
	}
}

var _ tracing.OpContext = testOpcodeContext{}
