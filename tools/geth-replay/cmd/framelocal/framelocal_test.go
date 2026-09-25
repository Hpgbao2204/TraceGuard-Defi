package main

import (
	"math/big"
	"os"
	"strings"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/types"
)

var (
	tokA = "0x000000000000000000000000000000000000aaaa"
	tokB = "0x000000000000000000000000000000000000bbbb"
)

func TestPerTokenThresholds(t *testing.T) {
	th := defaultThresholds // L_min = 1% of L, rho = 0.1
	cases := []struct {
		name string
		base map[string]string
		cf   map[string]string
		want string
	}{
		{"eliminated", map[string]string{tokA: "1000"}, map[string]string{}, "CAUSE"},
		{"at L_min", map[string]string{tokA: "1000"}, map[string]string{tokA: "10"}, "CAUSE"},
		{"just above L_min", map[string]string{tokA: "1000"}, map[string]string{tokA: "11"}, "PARTIAL"},
		{"at (1-rho)L", map[string]string{tokA: "1000"}, map[string]string{tokA: "900"}, "PARTIAL"},
		{"just above (1-rho)L", map[string]string{tokA: "1000"}, map[string]string{tokA: "901"}, "NO_EFFECT"},
		{"increased", map[string]string{tokA: "1000"}, map[string]string{tokA: "2000"}, "NO_EFFECT"},
		// Raw sum would be (1e18+5) -> 5, i.e. CAUSE; per token B is unchanged.
		{"tokens not summed", map[string]string{tokA: "1000000000000000000", tokB: "5"}, map[string]string{tokB: "5"}, "PARTIAL"},
		{"harm moved to new token", map[string]string{tokA: "1000"}, map[string]string{tokB: "7"}, "PARTIAL"},
	}
	for _, c := range cases {
		got, rows, code := perTokenVerdict(c.base, c.cf, th)
		if code != "" || got != c.want {
			t.Errorf("%s: got %q (code %q, rows %+v), want %q", c.name, got, code, rows, c.want)
		}
	}
	if _, _, code := perTokenVerdict(map[string]string{tokA: "-5"}, map[string]string{}, th); code != "zero_baseline_loss" {
		t.Errorf("inflow-only baseline must be inconclusive, got code %q", code)
	}
}

func frame(idx, parent int, caller, input string) victimEntryFrame {
	return victimEntryFrame{FrameIndex: idx, ParentFrame: parent, Caller: caller, Target: "0xv", Input: input, Value: "0",
		Status: true, AssetDeltas: map[string]string{tokA: "100"}, LogDigest: "0xd"}
}

func TestCheckAttackerInputs(t *testing.T) {
	base := []victimEntryFrame{frame(0, -1, "0xa", "0x01"), frame(1, 0, "0xa", "0x02"), frame(2, 0, "0xa", "0x03")}
	same := []victimEntryFrame{frame(0, -1, "0xa", "0x01"), frame(1, 0, "0xa", "0x02"), frame(2, 0, "0xa", "0x03")}
	if c := checkAttackerInputs(base, 0, same, 0, nil); !c.Match || c.ComparedEntries != 3 {
		t.Fatalf("identical inputs: %+v", c)
	}
	fewer := []victimEntryFrame{frame(0, -1, "0xa", "0x01"), frame(1, 0, "0xa", "0x02")}
	if c := checkAttackerInputs(base, 0, fewer, 0, nil); !c.Match {
		t.Fatalf("victim stopping early is allowed: %+v", c)
	}
	changed := []victimEntryFrame{frame(0, -1, "0xa", "0x01"), frame(1, 0, "0xa", "0xff")}
	if c := checkAttackerInputs(base, 0, changed, 0, nil); c.Match {
		t.Fatal("changed nested calldata must fail")
	}
	more := append(append([]victimEntryFrame{}, same...), frame(3, 0, "0xa", "0x04"))
	if c := checkAttackerInputs(base, 0, more, 0, nil); c.Match {
		t.Fatal("extra nested entry must fail")
	}
	// A third party's nested entry into V is not attacker input.
	third := []victimEntryFrame{frame(0, -1, "0xa", "0x01"), frame(1, 0, "0xa", "0x02"), frame(2, 0, "0xc", "0xee")}
	baseThird := []victimEntryFrame{frame(0, -1, "0xa", "0x01"), frame(1, 0, "0xa", "0x02"), frame(2, 0, "0xc", "0x03")}
	isA := func(a string) bool { return a == "0xa" }
	if c := checkAttackerInputs(baseThird, 0, third, 0, isA); !c.Match {
		t.Fatalf("third-party entry must not be compared: %+v", c)
	}
	top := []victimEntryFrame{frame(0, -1, "0xa", "0x99")}
	if c := checkAttackerInputs(base, 0, top, 0, nil); c.Match {
		t.Fatal("changed target calldata must fail")
	}
}

func TestVerdictGates(t *testing.T) {
	b := frame(0, -1, "0xa", "0x01")
	cf := b
	cf.AssetDeltas = map[string]string{}
	ok := &attackerInputCheck{Match: true}
	bad := &attackerInputCheck{Match: false, Detail: "x"}
	base := verdictInput{Mode: "frame-local", Baseline: &b, CF: &cf, Consumed: true, Sites: 1, Input: ok, Thresholds: defaultThresholds}

	check := func(name string, in verdictInput, verdict, code string) {
		t.Helper()
		got := computeFrameLocalVerdict(in)
		if got.Verdict != verdict || got.ReasonCode != code {
			t.Errorf("%s: got %s/%s (%s), want %s/%s", name, got.Verdict, got.ReasonCode, got.VerdictReason, verdict, code)
		}
	}
	check("cause", base, "CAUSE", "")

	in := base
	in.Input = bad
	check("attacker input", in, "INCONCLUSIVE", "attacker_input_changed")

	in = base
	in.Consumed = false
	check("not consumed", in, "INCONCLUSIVE", "not_consumed")

	in = base
	in.CF = nil
	check("not reached", in, "INCONCLUSIVE", "target_frame_not_reached")

	rev := cf
	rev.Reverted, rev.Status = true, false
	in = base
	in.CF = &rev
	in.Revert = &revertOriginResult{HasRevert: true, OriginClass: "victim", IntervenedReadBeforeRevert: true}
	check("blocked", in, "CAUSE_BLOCKED", "")
	in.Revert = &revertOriginResult{HasRevert: true, OriginClass: "victim", IntervenedReadBeforeRevert: false}
	check("victim revert before read", in, "INCONCLUSIVE", "victim_revert_before_read")
	in.Revert = &revertOriginResult{HasRevert: true, OriginClass: "attacker", IntervenedReadBeforeRevert: true}
	check("attacker revert", in, "INCONCLUSIVE", "revert_confound_attacker")
	in.Revert = &revertOriginResult{HasRevert: true, OriginClass: "third_party", IntervenedReadBeforeRevert: true}
	check("third-party revert", in, "INCONCLUSIVE", "revert_confound_third_party")

	// Isolation: identity stubs must reproduce status, log digest and loss.
	same := b
	iso := verdictInput{Mode: "isolation", Baseline: &b, CF: &same, Sites: 1, Input: ok, Thresholds: defaultThresholds}
	check("isolation pass", iso, "PASS", "")
	diffLogs := b
	diffLogs.LogDigest = "0xe"
	iso.CF = &diffLogs
	check("isolation log digest", iso, "FAIL", "")
	iso.CF, iso.Sites = &same, 0
	check("isolation without site", iso, "INCONCLUSIVE", "no_read_site")

	sham := verdictInput{Mode: "sham", Baseline: &b, CF: &same, Sites: 1, Input: ok, Thresholds: defaultThresholds}
	check("sham pass", sham, "PASS", "")
	sham.CF = &cf
	check("sham loss changed", sham, "FAIL", "")
	sham.CF, sham.Sites = &same, 0
	check("sham without site", sham, "INCONCLUSIVE", "no_unrelated_read_site")
	sham.Sites, sham.Input = 1, bad
	check("sham moves attacker", sham, "INCONCLUSIVE", "attacker_input_changed")
}

// A read deeper in the call tree than the reverting victim frame still
// happened before the revert. Depth ordering got this wrong.
func TestRevertOriginUsesTimeNotDepth(t *testing.T) {
	victim := common.HexToAddress("0x01")
	attacker := common.HexToAddress("0x02")
	oracle := common.HexToAddress("0x03")
	clf := newRevertClassifier([]string{victim.Hex()}, []string{attacker.Hex()}, nil)
	clock := clf.clock
	enter := func(d int, from, to common.Address) uint64 {
		clock.tick()
		clf.onEnter(d, 0xf1, from, to, nil)
		return clock.now()
	}
	exit := func(d int, reverted bool) { clock.tick(); clf.onExit(d, nil, nil, reverted) }

	enter(0, attacker, attacker)
	targetSeq := enter(1, attacker, victim)
	enter(2, victim, attacker) // callback
	readSeq := enter(3, attacker, victim)
	enter(4, victim, oracle)
	exit(4, false)
	exit(3, false)
	exit(2, false)
	exit(1, true) // victim frame reverts
	exit(0, true)

	clf.scopedReads = []scopedReadRecord{{Depth: 4, Seq: readSeq + 1}}
	got := clf.classifyFrame(targetSeq)
	if got.OriginClass != "victim" || !got.IntervenedReadBeforeRevert || got.CandidateVerdict != "CAUSE_BLOCKED" {
		t.Fatalf("read at depth 4 before a depth-1 revert: %+v", got)
	}
	// A read after the revert (larger seq) does not count.
	clf.scopedReads = []scopedReadRecord{{Depth: 1, Seq: clock.now() + 5}}
	if got := clf.classifyFrame(targetSeq); got.IntervenedReadBeforeRevert {
		t.Fatalf("read after the revert must not count: %+v", got)
	}
}

func TestRecorderCountsEachTransferOnce(t *testing.T) {
	victim := common.HexToAddress("0x0000000000000000000000000000000000000001")
	attacker := common.HexToAddress("0x0000000000000000000000000000000000000002")
	token := common.HexToAddress(tokA)
	st, err := makeState(map[string]account{})
	if err != nil {
		t.Fatal(err)
	}
	st.SetTxContext(common.HexToHash("0x1234"), 0, 0)
	rec := newFrameRecorder(st, []string{victim.Hex()}, []string{attacker.Hex()}, false, -1, nil)
	rec.onEnter(0, 0xf1, attacker, victim, nil, 100000, big.NewInt(0))
	log := &types.Log{Address: token, Topics: []common.Hash{transferEventTopic,
		common.BytesToHash(victim.Bytes()), common.BytesToHash(attacker.Bytes())},
		Data: common.BigToHash(big.NewInt(100)).Bytes()}
	st.AddLog(log)
	rec.onLog(log)
	rec.onExit(0, nil, 21000, nil, false)
	if got := rec.entryFrames[0].AssetDeltas[tokA]; got != "100" {
		t.Fatalf("victim loss = %s, want 100 (each Transfer once)", got)
	}
	if len(rec.entryFrames[0].Logs) != 1 {
		t.Fatalf("frame logs = %d, want 1", len(rec.entryFrames[0].Logs))
	}
}

func TestLogsDigestSeesContent(t *testing.T) {
	a := &types.Log{Address: common.HexToAddress("0x01"), Topics: []common.Hash{{1}}, Data: []byte{1}}
	b := &types.Log{Address: common.HexToAddress("0x01"), Topics: []common.Hash{{1}}, Data: []byte{2}}
	if logsDigest([]*types.Log{a}) == logsDigest([]*types.Log{b}) {
		t.Fatal("same count, different data must give different digests")
	}
	if logsDigest([]*types.Log{a}) != logsDigest([]*types.Log{a}) {
		t.Fatal("digest must be deterministic")
	}
}

func TestPerturbWordsAlwaysDiffers(t *testing.T) {
	for _, v := range [][]byte{
		common.BigToHash(big.NewInt(1000)).Bytes(),
		common.BigToHash(big.NewInt(0)).Bytes(),
		common.BigToHash(big.NewInt(1)).Bytes(),
		{},
	} {
		got := perturbWords(v, 0.5)
		if string(got) == string(v) {
			t.Fatalf("perturbWords(%x) returned the observed value", v)
		}
	}
}

func TestSelectHarmFrameUsesShares(t *testing.T) {
	// Frame 0 loses 1e18 of A (half of all A); frame 1 loses all 5 units of B.
	frames := []victimEntryFrame{
		{FrameIndex: 0, ParentFrame: -1, IsHarmFrame: true, AssetDeltas: map[string]string{tokA: "1000000000000000000"}},
		{FrameIndex: 1, ParentFrame: -1, IsHarmFrame: true, AssetDeltas: map[string]string{tokB: "5"}},
		{FrameIndex: 2, ParentFrame: -1, IsHarmFrame: true, AssetDeltas: map[string]string{tokA: "1000000000000000000"}},
	}
	if got := selectHarmFrame(frames); got != 1 {
		t.Fatalf("selectHarmFrame = %d, want 1 (largest unit-free share)", got)
	}
	if got := selectHarmFrame(nil); got != -1 {
		t.Fatalf("no frames: %d", got)
	}
}

func TestScopingOnlyInsideTargetFrame(t *testing.T) {
	victim := common.HexToAddress("0x0000000000000000000000000000000000000001")
	oracle := common.HexToAddress("0x0000000000000000000000000000000000000003")
	st, err := makeState(map[string]account{})
	if err != nil {
		t.Fatal(err)
	}
	header := testHeader()
	cfg, _ := getChainConfig(mainnetChainID)
	m := newScopingManager(true, []string{victim.Hex()}, nil, nil, st.Copy(), header, cfg, nil, valueNeutral, nil, false)
	active := false
	m.inScope = func() bool { return active }
	input := common.FromHex("0x50d25bcd") // latestAnswer()
	m.onEnter(2, 0xfa, victim, oracle, input, 100000, st, 0)
	m.onExit(2, nil, st)
	if len(m.records) != 0 {
		t.Fatal("read outside the target frame must not be intervened")
	}
	active = true
	m.onEnter(2, 0xfa, victim, oracle, input, 100000, st, 0)
	m.onExit(2, nil, st)
	if len(m.records) != 1 || m.records[0].Kind != valueNeutral {
		t.Fatalf("read inside the target frame: %+v", m.records)
	}
	// Sham ignores the victim's own reads and takes reads by other callers.
	s := newScopingManager(true, []string{victim.Hex()}, nil, nil, st.Copy(), header, cfg, nil, valueSham, nil, false)
	s.onEnter(2, 0xfa, victim, oracle, input, 100000, st, 0)
	s.onExit(2, nil, st)
	other := common.HexToAddress("0x0000000000000000000000000000000000000009")
	s.onEnter(2, 0xfa, other, oracle, input, 100000, st, 0)
	s.onExit(2, nil, st)
	if len(s.records) != 1 || s.records[0].Caller != other.Hex() {
		t.Fatalf("sham sites: %+v", s.records)
	}
}

func TestParseReadSite(t *testing.T) {
	ok := []string{"0x00000000000000000000000000000000000000a1:0x70a08231", "*:70a08231", "0x00000000000000000000000000000000000000a1:*"}
	for _, v := range ok {
		if _, err := parseReadSite(v); err != nil {
			t.Errorf("%s: %v", v, err)
		}
	}
	for _, v := range []string{"*:*", "nope", "0x01:0x1234", "zz:70a08231"} {
		if _, err := parseReadSite(v); err == nil {
			t.Errorf("%s must be rejected", v)
		}
	}
}

// discover flags a read whose value changed since S0 and leaves an unchanged
// read alone.
func TestDiscoverFlagsDivergentReads(t *testing.T) {
	victim := common.HexToAddress("0x0000000000000000000000000000000000000001")
	oracle := common.HexToAddress("0x00000000000000000000000000000000000000a1")
	s0, err := makeState(map[string]account{
		strings.ToLower(oracle.Hex()): {Balance: "0x0", Code: "0x60005460005260206000f3", Storage: map[string]string{
			"0x0000000000000000000000000000000000000000000000000000000000000000": "0x0000000000000000000000000000000000000000000000000000000000000005"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	cfg, _ := getChainConfig(mainnetChainID)
	m := newScopingManager(true, []string{victim.Hex()}, nil, nil, s0.Copy(), testHeader(), cfg, nil, valueDiscover, nil, false)
	input := common.FromHex("0x70a08231")
	m.onEnter(2, 0xfa, victim, oracle, input, 100000, s0.Copy(), 0)
	moved := s0.Copy()
	moved.SetState(oracle, common.Hash{}, common.BigToHash(big.NewInt(7)))
	m.onEnter(2, 0xfa, victim, oracle, input, 100000, moved, 0)
	m.onEnter(2, 0xfa, common.HexToAddress("0x09"), oracle, input, 100000, moved, 0) // not V
	if len(m.records) != 2 {
		t.Fatalf("records = %d, want 2 (reads by V only)", len(m.records))
	}
	if m.records[0].Diverges || !m.records[1].Diverges {
		t.Fatalf("divergence flags: %+v", m.records)
	}
	// Changed before entry vs changed inside the frame by V.
	entry := s0.Copy()
	m.entryState = func() *state.StateDB { return entry }
	m.onEnter(2, 0xfa, victim, oracle, input, 100000, moved, 0)
	if r := m.records[2]; !r.Diverges || r.ChangedBeforeEntry {
		t.Fatalf("change made inside the frame must not count as pre-entry: %+v", r)
	}
	entry = moved
	m.onEnter(2, 0xfa, victim, oracle, input, 100000, moved, 0)
	if r := m.records[3]; !r.ChangedBeforeEntry {
		t.Fatalf("change before entry must count: %+v", r)
	}
	if moved.GetCode(oracle) == nil || len(m.activeStubs) != 0 {
		t.Fatal("discover must not stub")
	}
}

func TestReadSitesReplaceCatalogue(t *testing.T) {
	m := &scopingManager{}
	a := common.HexToAddress("0x00000000000000000000000000000000000000a1")
	if !m.isPriceTarget(a, "50d25bcd", "") || m.isPriceTarget(a, "70a08231", "") {
		t.Fatal("default catalogue: latestAnswer yes, balanceOf no")
	}
	rs, _ := parseReadSite(a.Hex() + ":70a08231")
	m.readSites = []readSite{rs}
	if m.isPriceTarget(a, "50d25bcd", "") || !m.isPriceTarget(a, "70a08231", "") || m.isPriceTarget(common.HexToAddress("0x02"), "70a08231", "") {
		t.Fatal("declared site must replace the catalogue and match target and selector")
	}
}

func TestUnscopedPinsEveryCaller(t *testing.T) {
	victim := common.HexToAddress("0x0000000000000000000000000000000000000001")
	attacker := common.HexToAddress("0x0000000000000000000000000000000000000bad")
	third := common.HexToAddress("0x0000000000000000000000000000000000000009")
	oracle := common.HexToAddress("0x00000000000000000000000000000000000000a1")
	s0, err := makeState(map[string]account{
		strings.ToLower(oracle.Hex()): {Balance: "0x0", Code: "0x60005460005260206000f3"},
	})
	if err != nil {
		t.Fatal(err)
	}
	cfg, _ := getChainConfig(mainnetChainID)
	rs, _ := parseReadSite(oracle.Hex() + ":70a08231")
	input := common.FromHex("0x70a08231")
	for _, unscoped := range []bool{false, true} {
		m := newScopingManager(true, []string{victim.Hex()}, nil, nil, s0.Copy(), testHeader(), cfg, nil, valueNeutral, nil, false)
		m.readSites = []readSite{rs}
		m.unscoped = unscoped
		m.attackers = addressSet([]string{attacker.Hex()})
		st := s0.Copy()
		for _, from := range []common.Address{victim, attacker, third} {
			m.onEnter(2, 0xfa, from, oracle, input, 100000, st, 0)
			m.onExit(2, nil, st)
		}
		var classes []string
		for _, r := range m.records {
			classes = append(classes, r.CallerClass)
		}
		want := "victim"
		if unscoped {
			want = "victim,attacker,third_party"
		}
		if got := strings.Join(classes, ","); got != want {
			t.Errorf("unscoped=%v: pinned callers %q, want %q", unscoped, got, want)
		}
	}
}

func TestDecodeRevert(t *testing.T) {
	errString := common.FromHex("0x08c379a0" +
		"0000000000000000000000000000000000000000000000000000000000000020" +
		"0000000000000000000000000000000000000000000000000000000000000001" +
		"4b00000000000000000000000000000000000000000000000000000000000000")
	panic11 := common.FromHex("0x4e487b71" + "0000000000000000000000000000000000000000000000000000000000000011")
	cases := []struct {
		out       []byte
		err       string
		kind, msg string
	}{
		{errString, "execution reverted", "error_string", "K"},
		{panic11, "execution reverted", "panic", "0x11 arithmetic_overflow"},
		{common.FromHex("0xdeadbeef"), "execution reverted", "custom_error", "0xdeadbeef"},
		{nil, "execution reverted", "empty", ""},
		{nil, "out of gas", "halt", "out of gas"},
	}
	for _, c := range cases {
		if k, m := decodeRevert(c.out, c.err); k != c.kind || m != c.msg {
			t.Errorf("decodeRevert(%x, %q) = %s/%q, want %s/%q", c.out, c.err, k, m, c.kind, c.msg)
		}
	}
}

func TestRevertChainNamesOriginFunction(t *testing.T) {
	clock := &eventClock{}
	clf := newRevertClassifier([]string{"0x0000000000000000000000000000000000000001"}, []string{"0x0000000000000000000000000000000000000bad"}, nil)
	clf.clock = clock
	v := common.HexToAddress("0x01")
	a := common.HexToAddress("0x0bad")
	clock.tick()
	clf.onEnter(0, 0xf1, common.HexToAddress("0xee"), a, common.FromHex("0x12345678"))
	clock.tick()
	clf.onEnter(1, 0xf4, a, v, common.FromHex("0xa9059cbb00"))
	clock.tick()
	clf.onExit(1, common.FromHex("0xdeadbeef"), nil, true)
	clock.tick()
	clf.onExit(0, common.FromHex("0xdeadbeef"), nil, true)
	r := clf.classify(true, "")
	if r.OriginClass != "victim" || r.OriginSelector != "0xa9059cbb" || r.RevertMessage != "0xdeadbeef" || len(r.RevertChain) != 2 || r.RevertChain[0].Class != "attacker" ||
		r.OriginContextClass != "attacker" {
		t.Fatalf("revert detail: %+v", r)
	}
	clf.delegateContext = true
	if r := clf.classify(true, ""); r.OriginClass != "attacker" {
		t.Fatalf("delegate-context must classify by the storage context: %+v", r)
	}
}

func TestReadSiteArgs(t *testing.T) {
	a := common.HexToAddress("0x00000000000000000000000000000000000000a1")
	holder := "000000000000000000000000" + strings.Repeat("11", 20)
	rs, err := parseReadSite(a.Hex() + ":70a08231:" + holder)
	if err != nil || rs.args != holder {
		t.Fatalf("parse args: %+v %v", rs, err)
	}
	m := &scopingManager{readSites: []readSite{rs}}
	other := "000000000000000000000000" + strings.Repeat("22", 20)
	if !m.isPriceTarget(a, "70a08231", holder) || m.isPriceTarget(a, "70a08231", other) {
		t.Fatal("args must restrict the site to one holder")
	}
	if _, err := parseReadSite(a.Hex() + ":70a08231:zz"); err == nil {
		t.Fatal("bad args must be rejected")
	}
	if got := argsHex(common.FromHex("0x70a08231" + holder)); got != holder {
		t.Fatalf("argsHex = %s", got)
	}
}

func TestTargetCodeCopyAndFile(t *testing.T) {
	src := common.HexToAddress("0x00000000000000000000000000000000000000a1")
	dst := common.HexToAddress("0x000000000000000000000000000000000000f1a1")
	st, err := makeState(map[string]account{strings.ToLower(src.Hex()): {Balance: "0x0", Code: "0x6001"}})
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	art := dir + "/a.json"
	if err := os.WriteFile(art, []byte(`{"deployedBytecode":"0x6002"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	applyTargetOverrides(st, []string{src.Hex() + "=@" + art}, nil, dst.Hex()+"="+src.Hex())
	if got := common.Bytes2Hex(st.GetCode(dst)); got != "6001" {
		t.Fatalf("copy must keep the original code, got %s", got)
	}
	if got := common.Bytes2Hex(st.GetCode(src)); got != "6002" {
		t.Fatalf("@file artifact not loaded, got %s", got)
	}
}
