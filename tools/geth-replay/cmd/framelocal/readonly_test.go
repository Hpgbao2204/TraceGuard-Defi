package main

import (
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/params"
)

// A getter is admissible as a read site; a call that writes storage, directly
// or in a nested frame whose failure the caller swallows, is not.
func TestReadOnlyDistinguishesGettersFromWriters(t *testing.T) {
	st, err := state.New(types.EmptyRootHash, state.NewDatabaseForTesting())
	if err != nil {
		t.Fatal(err)
	}
	getter := common.HexToAddress("0x00000000000000000000000000000000000000d1")
	writer := common.HexToAddress("0x00000000000000000000000000000000000000d2")
	swallow := common.HexToAddress("0x00000000000000000000000000000000000000d3")
	// getter: return 32 bytes of SLOAD(0)
	st.SetCode(getter, hexutil.MustDecode("0x60005460005260206000f3"), tracing.CodeChangeUnspecified)
	// writer: SSTORE(0, 1); STOP
	st.SetCode(writer, hexutil.MustDecode("0x600160005500"), tracing.CodeChangeUnspecified)
	// swallow: CALL writer, ignore the result, return 32 zero bytes
	code := "0x" + "6000600060006000600073" + "00000000000000000000000000000000000000d2" + "5af150" + "60206000f3"
	st.SetCode(swallow, hexutil.MustDecode(code), tracing.CodeChangeUnspecified)
	m := &scopingManager{header: testHeader(), chainConfig: params.MainnetChainConfig}
	caller := common.HexToAddress("0x00000000000000000000000000000000000000c1")
	if !m.readOnly(caller, getter, nil, 100_000, st) {
		t.Fatal("getter reported as writing state")
	}
	if m.readOnly(caller, writer, nil, 100_000, st) {
		t.Fatal("storage writer reported as read-only")
	}
	if m.readOnly(caller, swallow, nil, 100_000, st) {
		t.Fatal("nested write whose failure is swallowed reported as read-only")
	}
}
