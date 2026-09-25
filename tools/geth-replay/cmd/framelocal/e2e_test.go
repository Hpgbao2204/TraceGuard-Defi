package main

import (
	"encoding/json"
	"flag"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

// End-to-end runs of the real CLI on a synthetic one-transaction block.
//
// oracle: latestAnswer() returns 100.
// victim: reads oracle.latestAnswer(); reverts if the answer is <= 50,
// otherwise emits Transfer(victim -> attacker, answer) of its own token.
// The attacker EOA calls the victim directly, so entry frame 0 is the harm frame.

var (
	e2eOracle = common.HexToAddress("0x00000000000000000000000000000000000000a1")
	e2eVictim = common.HexToAddress("0x00000000000000000000000000000000000000b2")
)

func e2eOracleCode() string { return "0x606460005260206000f3" }

func e2eVictimCode(attacker common.Address) string {
	code := "63" + "50d25bcd" + "60e01b" + "600052" + // mstore selector
		"6020" + "6000" + "6004" + "6000" + "73" + strings.TrimPrefix(strings.ToLower(e2eOracle.Hex()), "0x") + "5afa" + "50" + // staticcall
		"600051" + "80" + "6032" + "10" + "6039" + "57" + // if 50 < answer goto ok
		"600080fd" + // revert
		"5b" + "600052" + // ok: mstore answer
		"73" + strings.TrimPrefix(strings.ToLower(attacker.Hex()), "0x") + "30" +
		"7f" + strings.TrimPrefix(transferEventTopic.Hex(), "0x") + "6020" + "6000" + "a3" + "00"
	return "0x" + code
}

func testHeader() *types.Header {
	return &types.Header{
		ParentHash:       common.Hash{1},
		UncleHash:        types.EmptyUncleHash,
		Coinbase:         common.HexToAddress("0x00000000000000000000000000000000000000c0"),
		Root:             common.Hash{2},
		TxHash:           types.EmptyTxsHash,
		ReceiptHash:      types.EmptyReceiptsHash,
		Difficulty:       big.NewInt(0),
		Number:           big.NewInt(20_000_000),
		GasLimit:         30_000_000,
		Time:             1_720_000_000,
		MixDigest:        common.Hash{3},
		BaseFee:          big.NewInt(1_000_000_000),
		WithdrawalsHash:  &types.EmptyWithdrawalsHash,
		BlobGasUsed:      new(uint64),
		ExcessBlobGas:    new(uint64),
		ParentBeaconRoot: &common.Hash{4},
	}
}

func writeJSON(t *testing.T, path string, v any) {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, b, 0o644); err != nil {
		t.Fatal(err)
	}
}

func buildE2EContext(t *testing.T, gasUsed uint64) (string, common.Address) {
	t.Helper()
	dir := t.TempDir()
	key, _ := crypto.HexToECDSA("4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318")
	attacker := crypto.PubkeyToAddress(key.PublicKey)
	header := testHeader()
	cfg, _ := getChainConfig(mainnetChainID)
	signer := types.MakeSigner(cfg, header.Number, header.Time)
	tx, err := types.SignTx(types.NewTx(&types.LegacyTx{Nonce: 0, GasPrice: big.NewInt(2_000_000_000), Gas: 200_000,
		To: &e2eVictim, Value: big.NewInt(0)}), signer, key)
	if err != nil {
		t.Fatal(err)
	}
	writeJSON(t, filepath.Join(dir, "block.json"), header)
	writeJSON(t, filepath.Join(dir, "transactions.json"), []*types.Transaction{tx})
	writeJSON(t, filepath.Join(dir, "receipts.json"), []map[string]any{{"index": 0, "tx_hash": tx.Hash().Hex(),
		"receipt": map[string]string{"status": "0x1", "gasUsed": hexutil.EncodeUint64(gasUsed)}}})
	trace := map[string]account{
		strings.ToLower(attacker.Hex()):  {Balance: "0x8ac7230489e80000"},
		strings.ToLower(e2eVictim.Hex()): {Balance: "0x0", Code: e2eVictimCode(attacker)},
		strings.ToLower(e2eOracle.Hex()): {Balance: "0x0", Code: e2eOracleCode()},
	}
	traceJSON, _ := json.Marshal(trace)
	writeJSON(t, filepath.Join(dir, "prestates.json"), []map[string]any{{"index": 0, "tx_hash": tx.Hash().Hex(), "trace": json.RawMessage(traceJSON)}})
	return dir, attacker
}

// TestHelperMain is the CLI entry point for the re-executed test binary.
func TestHelperMain(t *testing.T) {
	if os.Getenv("FRAMELOCAL_HELPER") != "1" {
		t.Skip("helper process only")
	}
	os.Args = append([]string{"framelocal"}, strings.Split(os.Getenv("FRAMELOCAL_ARGS"), "\x1f")...)
	flag.CommandLine = flag.NewFlagSet("framelocal", flag.ExitOnError)
	main()
	os.Exit(0)
}

func runCLI(t *testing.T, args ...string) output {
	t.Helper()
	out := filepath.Join(t.TempDir(), "out.json")
	args = append(args, "-output", out, "-lean")
	cmd := exec.Command(os.Args[0], "-test.run=^TestHelperMain$")
	cmd.Env = append(os.Environ(), "FRAMELOCAL_HELPER=1", "FRAMELOCAL_ARGS="+strings.Join(args, "\x1f"))
	if b, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("framelocal %v: %v\n%s", args, err, b)
	}
	var o output
	b, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(b, &o); err != nil {
		t.Fatal(err)
	}
	return o
}

func TestE2EFrameLocalModes(t *testing.T) {
	// First pass: learn the real gas so the replay gate can hold.
	dir, attacker := buildE2EContext(t, 0)
	rec := runCLI(t, "-context", dir, "-mode", "record", "-victim", e2eVictim.Hex(), "-attacker", attacker.Hex())
	gas := rec.Results[0].ActualGas
	if !rec.Results[0].ActualOK || gas == 0 {
		t.Fatalf("baseline did not succeed: %+v", rec.Results[0])
	}
	dir, attacker = buildE2EContext(t, gas)
	common := []string{"-context", dir, "-victim", e2eVictim.Hex(), "-attacker", attacker.Hex()}
	word := func(v int64) string { return hexutil.Encode(common2word(v)) }

	cases := []struct {
		name, mode string
		extra      []string
		verdict    string
		code       string
	}{
		{"blocked", "frame-local", []string{"-price-value", word(0)}, "CAUSE_BLOCKED", ""},
		{"partial", "frame-local", []string{"-price-value", word(60)}, "PARTIAL", ""},
		{"no effect", "frame-local", []string{"-price-value", word(95)}, "NO_EFFECT", ""},
		{"isolation", "isolation", nil, "PASS", ""},
		{"sham without unrelated read", "sham", nil, "INCONCLUSIVE", "no_unrelated_read_site"},
	}
	for _, c := range cases {
		o := runCLI(t, append(append(append([]string{}, common...), "-mode", c.mode), c.extra...)...)
		fl := o.FrameLocalResult
		if fl == nil {
			t.Fatalf("%s: no frame_local_result", c.name)
		}
		if fl.Verdict != c.verdict || fl.ReasonCode != c.code {
			t.Errorf("%s: got %s/%s (%s), want %s/%s", c.name, fl.Verdict, fl.ReasonCode, fl.VerdictReason, c.verdict, c.code)
		}
		if o.BaselineTargetMatch == nil || !*o.BaselineTargetMatch || !o.PrefixGasMatch {
			t.Errorf("%s: baseline target replay must match the receipt", c.name)
		}
		if fl.AttackerInput == nil || !fl.AttackerInput.Match {
			t.Errorf("%s: attacker input must be unchanged: %+v", c.name, fl.AttackerInput)
		}
		if len(o.Results[0].CallTrace) != 0 {
			t.Errorf("%s: lean output kept the call trace", c.name)
		}
	}

	site := e2eOracle.Hex() + ":50d25bcd"
	declared := runCLI(t, append(append([]string{}, common...), "-mode", "frame-local", "-read-site", site, "-price-value", word(0))...)
	if declared.FrameLocalResult.Verdict != "CAUSE_BLOCKED" {
		t.Errorf("declared site: %+v", declared.FrameLocalResult)
	}
	other := runCLI(t, append(append([]string{}, common...), "-mode", "frame-local", "-read-site", e2eOracle.Hex()+":70a08231", "-price-value", word(0))...)
	if other.FrameLocalResult.ReasonCode != "not_consumed" {
		t.Errorf("undeclared selector must not be intervened: %+v", other.FrameLocalResult)
	}
	disc := runCLI(t, append(append([]string{}, common...), "-mode", "discover")...)
	if disc.FrameLocalResult.Verdict != "DISCOVERY" || len(disc.ScopedReads) != 1 || disc.ScopedReads[0].Diverges || disc.ScopedReads[0].ChangedBeforeEntry {
		t.Errorf("discover: %+v %+v", disc.FrameLocalResult, disc.ScopedReads)
	}

	whole := runCLI(t, append(append([]string{}, common...), "-mode", "whole-tx", "-scoped-price", "-price-value", word(0))...)
	if whole.WholeTxResult == nil || whole.WholeTxResult.Verdict != "CAUSE_BLOCKED" {
		t.Fatalf("whole-tx blocked: %+v", whole.WholeTxResult)
	}
	wholePartial := runCLI(t, append(append([]string{}, common...), "-mode", "whole-tx", "-scoped-price", "-price-value", word(60))...)
	if wholePartial.WholeTxResult == nil || wholePartial.WholeTxResult.Verdict != "PARTIAL" {
		t.Fatalf("whole-tx partial: %+v", wholePartial.WholeTxResult)
	}
	un := runCLI(t, append(append([]string{}, common...), "-mode", "whole-tx", "-scoped-price", "-unscoped", "-read-site", site, "-price-value", word(0))...)
	if un.WholeTxResult == nil || un.WholeTxResult.Verdict != "CAUSE_BLOCKED" || un.WholeTxResult.Mode != "whole-tx-unscoped" {
		t.Fatalf("unscoped whole-tx: %+v", un.WholeTxResult)
	}
	if ro := un.RevertOrigin; ro == nil || ro.OriginClass != "victim" || ro.RevertKind != "empty" || len(un.ScopedReads) != 1 || un.ScopedReads[0].CallerClass != "victim" {
		t.Fatalf("unscoped revert detail: %+v %+v", un.RevertOrigin, un.ScopedReads)
	}
	// Code intervention: the oracle replaced by code returning 0; no -scoped-price.
	code := runCLI(t, append(append([]string{}, common...), "-mode", "whole-tx", "-target-code", e2eOracle.Hex()+"=0x600060005260206000f3")...)
	if code.WholeTxResult == nil || code.WholeTxResult.Verdict != "CAUSE_BLOCKED" {
		t.Fatalf("code override whole-tx: %+v", code.WholeTxResult)
	}
	pr := runCLI(t, append(append([]string{}, common...), "-mode", "probe", "-probe", e2eOracle.Hex()+":0x0dfe1681", "-probe", "zz")...)
	if len(pr.Probes) != 2 || pr.Probes[0].Output != hexutil.Encode(common2word(100)) || pr.Probes[1].Error == "" {
		t.Fatalf("probe: %+v", pr.Probes)
	}
	if !wholePartial.ReplayGate {
		t.Logf("replay gate false without a proof file, as expected")
	}
}

func common2word(v int64) []byte { return common.BigToHash(big.NewInt(v)).Bytes() }
