// LEGACY: not used for RQ3. The frame-local runner is tools/geth-replay/cmd/framelocal,
// which holds attacker input fixed, gates consumption and CAUSE_BLOCKED by event
// time, and applies per-token thresholds. This copy is kept only for comparison.

package main

import (
	"fmt"
	"math/big"
)

type frameLocalExecutionResult struct {
	TargetFrameIndex        int               `json:"target_frame_index"`
	Executed                bool              `json:"executed"`
	Status                  bool              `json:"status"`
	GasUsed                 uint64            `json:"gas_used"`
	Reverted                bool              `json:"reverted"`
	Error                   string            `json:"error,omitempty"`
	BaselineDeltaLoss       map[string]string `json:"baseline_delta_loss"`
	CounterfactualDeltaLoss map[string]string `json:"counterfactual_delta_loss"`
	IsolationMatch          bool              `json:"isolation_match,omitempty"`
	ShamMatch               bool              `json:"sham_match,omitempty"`
	Consumed                bool              `json:"consumed"`
	Verdict                 string            `json:"verdict"`
	VerdictReason           string            `json:"verdict_reason"`
}

// computeFrameLocalVerdict derives the CDE causal verdict from baseline and counterfactual frame results
func computeFrameLocalVerdict(
	baseline *victimEntryFrame,
	cf *victimEntryFrame,
	consumed bool,
	mode string, // "frame-local", "isolation", "sham"
) frameLocalExecutionResult {
	res := frameLocalExecutionResult{
		BaselineDeltaLoss:       make(map[string]string),
		CounterfactualDeltaLoss: make(map[string]string),
		Consumed:                consumed,
	}
	if baseline != nil {
		res.TargetFrameIndex = baseline.FrameIndex
		for k, v := range baseline.AssetDeltas {
			res.BaselineDeltaLoss[k] = v
		}
	}
	if cf == nil {
		res.Executed = false
		res.Verdict = "INCONCLUSIVE"
		res.VerdictReason = "target frame was never reached or execution failed before entry"
		return res
	}

	res.Executed = true
	res.Status = cf.Status
	res.GasUsed = cf.GasUsed
	res.Reverted = cf.Reverted
	res.Error = cf.Error
	for k, v := range cf.AssetDeltas {
		res.CounterfactualDeltaLoss[k] = v
	}

	// 1. Mode: Isolation Control (T9)
	if mode == "isolation" {
		statusMatch := baseline != nil && cf.Status == baseline.Status
		gasMatch := baseline != nil && cf.GasUsed == baseline.GasUsed
		logMatch := baseline != nil && len(cf.Logs) == len(baseline.Logs)
		lossMatch := assetDeltasEqual(res.BaselineDeltaLoss, res.CounterfactualDeltaLoss)
		res.IsolationMatch = statusMatch && gasMatch && logMatch && lossMatch
		if res.IsolationMatch {
			res.Verdict = "PASS"
			res.VerdictReason = "isolation control passed: baseline reproduced exactly"
		} else {
			res.Verdict = "FAIL"
			res.VerdictReason = fmt.Sprintf(
				"isolation discrepancy: status=%v gas=%v (diff %d) logs=%v (diff %d) loss=%v",
				statusMatch, gasMatch, int64(cf.GasUsed)-int64(baseline.GasUsed),
				logMatch, len(cf.Logs)-len(baseline.Logs), lossMatch,
			)
		}
		return res
	}

	// 2. Mode: Sham Control (T10)
	if mode == "sham" {
		lossMatch := assetDeltasEqual(res.BaselineDeltaLoss, res.CounterfactualDeltaLoss)
		res.ShamMatch = lossMatch
		if res.ShamMatch {
			res.Verdict = "PASS"
			res.VerdictReason = "sham control passed: observed value substitution leaves loss unchanged"
		} else {
			res.Verdict = "FAIL"
			res.VerdictReason = "sham control failed: no-op substitution altered victim loss"
		}
		return res
	}

	// 3. Mode: Frame-local counterfactual replay (T8)
	// Gate A: Consumption check
	if !consumed {
		res.Verdict = "INCONCLUSIVE"
		res.VerdictReason = "neutral factor was not consumed inside the victim harm frame"
		return res
	}

	// Gate B: If the victim frame itself reverted upon observing neutral value -> CAUSE_BLOCKED
	if cf.Reverted {
		res.Verdict = "CAUSE_BLOCKED"
		res.VerdictReason = fmt.Sprintf("victim frame rejected execution with neutral value (error: %s)", cf.Error)
		return res
	}

	// Gate C: Compare loss delta
	totalBaselineLoss := sumPositiveDeltas(res.BaselineDeltaLoss)
	totalCFLoss := sumPositiveDeltas(res.CounterfactualDeltaLoss)

	if totalBaselineLoss.Sign() == 0 {
		res.Verdict = "INCONCLUSIVE"
		res.VerdictReason = "baseline harm frame had zero measurable positive asset outflow"
		return res
	}

	// Calculate reduction = (L - L') / L
	diffLoss := new(big.Int).Sub(totalBaselineLoss, totalCFLoss)
	if diffLoss.Sign() <= 0 {
		// Loss did not decrease at all
		res.Verdict = "NO_EFFECT"
		res.VerdictReason = "neutral factor substitution did not reduce victim asset outflow"
		return res
	}

	// Compare with threshold rho = 50%
	// If (L - L') * 2 >= L, reduction >= 50%
	twoDiff := new(big.Int).Mul(diffLoss, big.NewInt(2))
	if totalCFLoss.Sign() <= 0 || twoDiff.Cmp(totalBaselineLoss) >= 0 {
		res.Verdict = "CAUSE"
		res.VerdictReason = fmt.Sprintf(
			"neutral factor eliminated victim outflow (baseline: %s, counterfactual: %s)",
			totalBaselineLoss.String(), totalCFLoss.String(),
		)
		return res
	}

	res.Verdict = "PARTIAL"
	res.VerdictReason = fmt.Sprintf(
		"neutral factor partially reduced victim outflow (baseline: %s, counterfactual: %s)",
		totalBaselineLoss.String(), totalCFLoss.String(),
	)
	return res
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

func sumPositiveDeltas(m map[string]string) *big.Int {
	sum := new(big.Int)
	for _, vStr := range m {
		n, ok := new(big.Int).SetString(vStr, 10)
		if ok && n.Sign() > 0 {
			sum.Add(sum, n)
		}
	}
	return sum
}
