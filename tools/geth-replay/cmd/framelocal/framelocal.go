package main

import (
	"fmt"
	"math/big"
	"sort"
	"strings"

	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

// eventClock orders call enters/exits across the frame recorder, the scoping
// manager and the revert classifier. The hooks tick it once per enter/exit, so
// "read before revert" is decided by time, not by call depth.
type eventClock struct{ n uint64 }

func (c *eventClock) tick() uint64 {
	c.n++
	return c.n
}

func (c *eventClock) now() uint64 { return c.n }

// Verdict thresholds (paper): CAUSE when L' <= L_min; PARTIAL when
// L_min < L' <= (1-rho)L; NO_EFFECT otherwise. Applied per token, never on a
// sum of raw amounts of different tokens. L_min is a fraction of the baseline
// loss of the same token.
type verdictThresholds struct {
	LossMinFrac float64 `json:"loss_min_frac"`
	Rho         float64 `json:"rho"`
}

var defaultThresholds = verdictThresholds{LossMinFrac: 0.01, Rho: 0.1}

type tokenLoss struct {
	Asset          string `json:"asset"`
	Baseline       string `json:"baseline"`
	Counterfactual string `json:"counterfactual"`
	Outcome        string `json:"outcome"` // CAUSE, PARTIAL, NO_EFFECT, NEW_HARM
}

type attackerInputCheck struct {
	Match           bool   `json:"match"`
	Detail          string `json:"detail,omitempty"`
	ComparedEntries int    `json:"compared_entries"`
}

type frameLocalExecutionResult struct {
	Mode                    string              `json:"mode"`
	TargetFrameIndex        int                 `json:"target_frame_index"`
	Executed                bool                `json:"executed"`
	Status                  bool                `json:"status"`
	GasUsed                 uint64              `json:"gas_used"`
	GasDelta                int64               `json:"gas_delta"`
	Reverted                bool                `json:"reverted"`
	Error                   string              `json:"error,omitempty"`
	BaselineDeltaLoss       map[string]string   `json:"baseline_delta_loss"`
	CounterfactualDeltaLoss map[string]string   `json:"counterfactual_delta_loss"`
	TokenLosses             []tokenLoss         `json:"token_losses,omitempty"`
	Thresholds              verdictThresholds   `json:"thresholds"`
	AttackerInput           *attackerInputCheck `json:"attacker_input,omitempty"`
	LogDigestMatch          bool                `json:"log_digest_match"`
	InterventionSites       int                 `json:"intervention_sites"`
	Consumed                bool                `json:"consumed"`
	RevertOrigin            *revertOriginResult `json:"revert_origin,omitempty"`
	IsolationMatch          bool                `json:"isolation_match,omitempty"`
	ShamMatch               bool                `json:"sham_match,omitempty"`
	Verdict                 string              `json:"verdict"`
	ReasonCode              string              `json:"reason_code,omitempty"`
	VerdictReason           string              `json:"verdict_reason"`
}

type verdictInput struct {
	Mode       string // "frame-local", "isolation", "sham", "whole-tx"
	Baseline   *victimEntryFrame
	CF         *victimEntryFrame
	BaseLoss   map[string]string // defaults to Baseline.AssetDeltas
	CFLoss     map[string]string // defaults to CF.AssetDeltas
	Consumed   bool
	Sites      int
	Input      *attackerInputCheck
	Revert     *revertOriginResult // origin of the counterfactual revert, if any
	Thresholds verdictThresholds
}

func inconclusive(res frameLocalExecutionResult, code, reason string) frameLocalExecutionResult {
	res.Verdict = "INCONCLUSIVE"
	res.ReasonCode = code
	res.VerdictReason = reason
	return res
}

// computeFrameLocalVerdict derives the verdict for one intervention run.
// Order of gates for frame-local and whole-tx: reached, attacker input held
// fixed, intervention consumed inside the harm frame, revert origin, then the
// per-token loss comparison.
func computeFrameLocalVerdict(in verdictInput) frameLocalExecutionResult {
	res := frameLocalExecutionResult{
		Mode:                    in.Mode,
		TargetFrameIndex:        -1,
		BaselineDeltaLoss:       map[string]string{},
		CounterfactualDeltaLoss: map[string]string{},
		Thresholds:              in.Thresholds,
		AttackerInput:           in.Input,
		Consumed:                in.Consumed,
		InterventionSites:       in.Sites,
		RevertOrigin:            in.Revert,
	}
	baseLoss, cfLoss := in.BaseLoss, in.CFLoss
	if in.Baseline != nil {
		res.TargetFrameIndex = in.Baseline.FrameIndex
		if baseLoss == nil {
			baseLoss = in.Baseline.AssetDeltas
		}
	}
	for k, v := range baseLoss {
		res.BaselineDeltaLoss[k] = v
	}
	if in.Baseline == nil {
		return inconclusive(res, "no_baseline_frame", "baseline target frame not found")
	}
	if in.CF == nil {
		return inconclusive(res, "target_frame_not_reached", "target frame was never reached or execution failed before entry")
	}
	if cfLoss == nil {
		cfLoss = in.CF.AssetDeltas
	}
	res.Executed = true
	res.Status = in.CF.Status
	res.GasUsed = in.CF.GasUsed
	res.GasDelta = int64(in.CF.GasUsed) - int64(in.Baseline.GasUsed)
	res.Reverted = in.CF.Reverted
	res.Error = in.CF.Error
	res.LogDigestMatch = in.CF.LogDigest == in.Baseline.LogDigest
	for k, v := range cfLoss {
		res.CounterfactualDeltaLoss[k] = v
	}
	lossEqual := assetDeltasEqual(baseLoss, cfLoss)
	inputOK := in.Input == nil || in.Input.Match

	switch in.Mode {
	case "isolation":
		// Identity stubs at the same read sites the intervention uses: the
		// machinery runs, the values do not change. Gas is reported but not
		// gated, because a stub necessarily costs different gas than the
		// real getter.
		if in.Sites == 0 {
			return inconclusive(res, "no_read_site", "no scoped read site inside the target frame; isolation would be trivial")
		}
		statusMatch := in.CF.Status == in.Baseline.Status
		res.IsolationMatch = statusMatch && res.LogDigestMatch && lossEqual && inputOK
		if res.IsolationMatch {
			res.Verdict = "PASS"
			res.VerdictReason = "identity stubs reproduce baseline status, log digest, per-token loss and attacker inputs"
		} else {
			res.Verdict = "FAIL"
			res.VerdictReason = fmt.Sprintf("isolation discrepancy: status=%v logs=%v loss=%v attacker_input=%v gas_delta=%d",
				statusMatch, res.LogDigestMatch, lossEqual, inputOK, res.GasDelta)
		}
		return res
	case "sham":
		if in.Sites == 0 {
			return inconclusive(res, "no_unrelated_read_site", "no unrelated read site inside the target frame to perturb")
		}
		if !inputOK {
			return inconclusive(res, "attacker_input_changed", "sham site is not unrelated: attacker input to the victim changed ("+in.Input.Detail+")")
		}
		statusMatch := in.CF.Status == in.Baseline.Status
		res.ShamMatch = statusMatch && lossEqual
		if res.ShamMatch {
			res.Verdict = "PASS"
			res.VerdictReason = "perturbing an unrelated read left victim status and per-token loss unchanged"
		} else {
			res.Verdict = "FAIL"
			res.VerdictReason = fmt.Sprintf("sham perturbation changed victim outcome: status=%v loss=%v", statusMatch, lossEqual)
		}
		return res
	}

	if !inputOK {
		return inconclusive(res, "attacker_input_changed", "attacker input to the victim differs from baseline ("+in.Input.Detail+")")
	}
	if !in.Consumed {
		return inconclusive(res, "not_consumed", "intervened read did not occur inside the victim harm frame")
	}
	if in.CF.Reverted {
		ro := in.Revert
		switch {
		case ro == nil || !ro.HasRevert:
			return inconclusive(res, "revert_origin_unknown", "counterfactual reverted but no revert origin was found")
		case ro.OriginClass == "victim" && ro.IntervenedReadBeforeRevert:
			res.Verdict = "CAUSE_BLOCKED"
			res.VerdictReason = fmt.Sprintf("victim frame %s reverted after the intervened read (error: %s)", ro.OriginAddress, ro.ErrorReason)
			return res
		case ro.OriginClass == "victim":
			return inconclusive(res, "victim_revert_before_read", "victim reverted before any intervened read")
		case ro.OriginClass == "attacker":
			return inconclusive(res, "revert_confound_attacker", "revert originated in attacker code")
		default:
			return inconclusive(res, "revert_confound_third_party", "revert originated in third-party code ("+ro.OriginAddress+")")
		}
	}
	verdict, rows, err := perTokenVerdict(baseLoss, cfLoss, in.Thresholds)
	res.TokenLosses = rows
	if err != "" {
		return inconclusive(res, err, "baseline harm frame had zero measurable positive asset outflow")
	}
	res.Verdict = verdict
	res.VerdictReason = describeTokens(verdict, rows)
	return res
}

// perTokenVerdict classifies each baseline-harmed token, then aggregates:
// CAUSE if every harmed token is CAUSE and no new token is harmed; NO_EFFECT if
// every harmed token is NO_EFFECT; PARTIAL otherwise.
func perTokenVerdict(base, cf map[string]string, th verdictThresholds) (string, []tokenLoss, string) {
	lmin := new(big.Rat).SetFloat64(th.LossMinFrac)
	keep := new(big.Rat).SetFloat64(1 - th.Rho)
	if lmin == nil || keep == nil {
		return "", nil, "bad_thresholds"
	}
	assets := make([]string, 0, len(base)+len(cf))
	seen := map[string]bool{}
	for k := range base {
		assets = append(assets, k)
		seen[k] = true
	}
	for k := range cf {
		if !seen[k] {
			assets = append(assets, k)
		}
	}
	sort.Strings(assets)
	rows := make([]tokenLoss, 0, len(assets))
	counts := map[string]int{}
	harmed := 0
	for _, a := range assets {
		l := parseSigned(base[a])
		lp := parseSigned(cf[a])
		row := tokenLoss{Asset: a, Baseline: l.String(), Counterfactual: lp.String()}
		if l.Sign() <= 0 {
			if lp.Sign() > 0 {
				row.Outcome = "NEW_HARM"
				counts["NEW_HARM"]++
				rows = append(rows, row)
			}
			continue
		}
		harmed++
		lr := new(big.Rat).SetInt(l)
		lpr := new(big.Rat).SetInt(lp)
		switch {
		case lpr.Cmp(new(big.Rat).Mul(lr, lmin)) <= 0:
			row.Outcome = "CAUSE"
		case lpr.Cmp(new(big.Rat).Mul(lr, keep)) <= 0:
			row.Outcome = "PARTIAL"
		default:
			row.Outcome = "NO_EFFECT"
		}
		counts[row.Outcome]++
		rows = append(rows, row)
	}
	if harmed == 0 {
		return "", rows, "zero_baseline_loss"
	}
	switch {
	case counts["CAUSE"] == harmed && counts["NEW_HARM"] == 0:
		return "CAUSE", rows, ""
	case counts["NO_EFFECT"] == harmed:
		return "NO_EFFECT", rows, ""
	default:
		return "PARTIAL", rows, ""
	}
}

func describeTokens(verdict string, rows []tokenLoss) string {
	parts := make([]string, 0, len(rows))
	for _, r := range rows {
		parts = append(parts, fmt.Sprintf("%s:%s->%s(%s)", r.Asset, r.Baseline, r.Counterfactual, r.Outcome))
	}
	return verdict + " per token: " + strings.Join(parts, ", ")
}

func parseSigned(s string) *big.Int {
	n, ok := new(big.Int).SetString(strings.TrimSpace(s), 10)
	if !ok {
		return new(big.Int)
	}
	return n
}

// nestedEntries returns the entry frames entered while frame t was active, in
// entry order.
func nestedEntries(frames []victimEntryFrame, t int) []victimEntryFrame {
	out := []victimEntryFrame{}
	for _, f := range frames {
		for p := f.ParentFrame; p >= 0 && p < len(frames); p = frames[p].ParentFrame {
			if p == t {
				out = append(out, f)
				break
			}
		}
	}
	return out
}

// checkAttackerInputs holds the attacker's input to the victim fixed: the
// target entry and every nested entry into V made by an attacker address
// inside it must have the same caller, calldata and value as in the baseline.
// Entries by third parties are not attacker input and are not compared. The
// counterfactual may have fewer attacker entries (the victim stopped
// earlier), never more or different.
func checkAttackerInputs(base []victimEntryFrame, baseT int, cf []victimEntryFrame, cfT int, isAttacker func(string) bool) attackerInputCheck {
	if baseT < 0 || baseT >= len(base) || cfT < 0 || cfT >= len(cf) {
		return attackerInputCheck{Match: false, Detail: "target frame missing"}
	}
	same := func(a, b victimEntryFrame) bool {
		return strings.EqualFold(a.Caller, b.Caller) && strings.EqualFold(a.Target, b.Target) &&
			strings.EqualFold(a.Input, b.Input) && a.Value == b.Value
	}
	if !same(base[baseT], cf[cfT]) {
		return attackerInputCheck{Match: false, Detail: "target entry caller/calldata/value differ", ComparedEntries: 1}
	}
	byAttacker := func(frames []victimEntryFrame) []victimEntryFrame {
		out := []victimEntryFrame{}
		for _, f := range frames {
			if isAttacker == nil || isAttacker(f.Caller) {
				out = append(out, f)
			}
		}
		return out
	}
	bn, cn := byAttacker(nestedEntries(base, baseT)), byAttacker(nestedEntries(cf, cfT))
	if len(cn) > len(bn) {
		return attackerInputCheck{Match: false, Detail: fmt.Sprintf("counterfactual has %d nested victim entries, baseline %d", len(cn), len(bn)), ComparedEntries: 1}
	}
	for i := range cn {
		if !same(bn[i], cn[i]) {
			return attackerInputCheck{Match: false, Detail: fmt.Sprintf("nested victim entry %d differs", i), ComparedEntries: i + 2}
		}
	}
	return attackerInputCheck{Match: true, ComparedEntries: 1 + len(cn)}
}

// logsDigest hashes the ordered (address, topics, data) of each log.
func logsDigest(logs []*types.Log) string {
	buf := make([]byte, 0, 64*len(logs))
	for _, l := range logs {
		h := crypto.Keccak256Hash(l.Address.Bytes(), topicsBytes(l), l.Data)
		buf = append(buf, h.Bytes()...)
	}
	return crypto.Keccak256Hash(buf).Hex()
}

func topicsBytes(l *types.Log) []byte {
	out := make([]byte, 0, 32*len(l.Topics))
	for _, t := range l.Topics {
		out = append(out, t.Bytes()...)
	}
	return out
}

// sumLossTopLevel sums per-token losses of top-level entry frames only, so a
// nested entry is not counted twice. Amounts of the same token are summed;
// different tokens stay separate.
func sumLossTopLevel(frames []victimEntryFrame) map[string]string {
	acc := map[string]*big.Int{}
	for _, f := range frames {
		if f.ParentFrame >= 0 {
			continue
		}
		for k, v := range f.AssetDeltas {
			if acc[k] == nil {
				acc[k] = new(big.Int)
			}
			acc[k].Add(acc[k], parseSigned(v))
		}
	}
	out := map[string]string{}
	for k, v := range acc {
		if v.Sign() != 0 {
			out[k] = v.String()
		}
	}
	return out
}

// selectHarmFrame picks the harm frame carrying the largest share of the
// transaction's per-token victim loss (shares are unit-free, so tokens are
// never summed raw). Ties go to the earliest frame. Returns -1 if none.
func selectHarmFrame(frames []victimEntryFrame) int {
	total := map[string]*big.Int{}
	for _, f := range frames {
		if f.ParentFrame >= 0 {
			continue
		}
		for k, v := range f.AssetDeltas {
			n := parseSigned(v)
			if n.Sign() > 0 {
				if total[k] == nil {
					total[k] = new(big.Int)
				}
				total[k].Add(total[k], n)
			}
		}
	}
	best, bestScore := -1, new(big.Rat)
	for i, f := range frames {
		if !f.IsHarmFrame {
			continue
		}
		score := new(big.Rat)
		for k, v := range f.AssetDeltas {
			n := parseSigned(v)
			if n.Sign() > 0 && total[k] != nil && total[k].Sign() > 0 {
				score.Add(score, new(big.Rat).SetFrac(n, total[k]))
			}
		}
		if best < 0 || score.Cmp(bestScore) > 0 {
			best, bestScore = i, score
		}
	}
	return best
}

func assetDeltasEqual(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if b[k] != v {
			return false
		}
	}
	return true
}
