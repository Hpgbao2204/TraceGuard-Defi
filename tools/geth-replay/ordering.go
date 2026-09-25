package main

// Ordering intervention (-drop-tx): remove selected prefix transactions and
// replay the remaining prefix and the target unchanged on the same
// proof-bound state. The baseline for every comparison is the context's own
// receipts, i.e. the observed on-chain order; a fidelity run without
// -drop-tx is what establishes that the engine reproduces that baseline.

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/ethereum/go-ethereum/core/types"
)

// Confound kinds for an intermediate transaction whose outcome changed
// because the dropped transactions were removed from in front of it.
const (
	confoundNowReverts  = "now_reverts"
	confoundNowSucceeds = "now_succeeds"
	confoundInvalid     = "invalid"
	confoundGasChanged  = "gas_changed"
	confoundLogsChanged = "logs_changed"
)

// parseDropIndices validates repeatable -drop-tx values. Only strict prefix
// transactions may be dropped: dropping the target is not an ordering
// intervention on the target.
func parseDropIndices(values []string, targetIndex int) ([]int, error) {
	seen := make(map[int]struct{})
	var out []int
	for _, raw := range values {
		for _, part := range strings.Split(raw, ",") {
			part = strings.TrimSpace(part)
			index, err := strconv.Atoi(part)
			if err != nil {
				return nil, fmt.Errorf("--drop-tx %q is not an integer index", part)
			}
			if index < 0 || index >= targetIndex {
				return nil, fmt.Errorf("--drop-tx %d must be a prefix index in [0, %d)", index, targetIndex)
			}
			if _, dup := seen[index]; dup {
				return nil, fmt.Errorf("--drop-tx %d given more than once", index)
			}
			seen[index] = struct{}{}
			out = append(out, index)
		}
	}
	sort.Ints(out)
	return out, nil
}

// baselineOutcome is what the context receipts say a transaction did in the
// observed order.
type baselineOutcome struct {
	Status bool
	Gas    uint64
	Logs   []*types.Log
}

type orderingTxOutcome struct {
	Index               int     `json:"index"`
	Hash                string  `json:"tx_hash"`
	Role                string  `json:"role"` // dropped, prefix, target
	Executed            bool    `json:"executed"`
	BaselineStatus      bool    `json:"baseline_status"`
	BaselineGas         uint64  `json:"baseline_gas"`
	Status              bool    `json:"status"`
	Gas                 uint64  `json:"gas"`
	Error               string  `json:"error,omitempty"`
	StatusDiffers       bool    `json:"status_differs"`
	GasDiffers          bool    `json:"gas_differs"`
	LogsDiffer          bool    `json:"logs_differ"`
	DiffersFromBaseline bool    `json:"differs_from_baseline"`
	EVMms               float64 `json:"evm_ms"`
}

type orderingConfound struct {
	Index int      `json:"index"`
	Hash  string   `json:"tx_hash"`
	Kinds []string `json:"kinds"`
}

type orderingReport struct {
	DroppedIndices []int               `json:"dropped_indices"`
	TargetIndex    int                 `json:"target_index"`
	Baseline       string              `json:"baseline"`
	Prefix         []orderingTxOutcome `json:"per_tx"`
	Confounds      []orderingConfound  `json:"ordering_confounds"`
	Confounded     bool                `json:"ordering_confounded"`
	// FailClosed: the counterfactual order touched state outside the proof
	// footprint (or the target could not be compared). Nothing after
	// FailClosedTxIndex was executed and no verdict may be drawn.
	FailClosed        bool     `json:"fail_closed"`
	FailClosedTxIndex *int     `json:"fail_closed_tx_index,omitempty"`
	FailClosedReasons []string `json:"fail_closed_reasons,omitempty"`
	Comparable        bool     `json:"comparable"`
	IncomparableCause string   `json:"incomparable_reason,omitempty"`

	dropped map[int]struct{}
}

func newOrderingReport(dropped []int, targetIndex int) *orderingReport {
	set := make(map[int]struct{}, len(dropped))
	for _, index := range dropped {
		set[index] = struct{}{}
	}
	return &orderingReport{
		DroppedIndices: append([]int(nil), dropped...),
		TargetIndex:    targetIndex,
		Baseline:       "context receipts (observed on-chain order)",
		Confounds:      []orderingConfound{},
		dropped:        set,
	}
}

func (o *orderingReport) isDropped(index int) bool {
	_, ok := o.dropped[index]
	return ok
}

func (o *orderingReport) firstDropped() int {
	return o.DroppedIndices[0]
}

func (o *orderingReport) recordDropped(index int, hash string, baseline baselineOutcome) {
	o.Prefix = append(o.Prefix, orderingTxOutcome{Index: index, Hash: hash, Role: "dropped",
		BaselineStatus: baseline.Status, BaselineGas: baseline.Gas})
}

// recordExecuted compares one replayed transaction with its baseline. A
// changed intermediate transaction (after the first dropped index, before the
// target) is an ordering confound. A change before the first drop cannot be
// caused by the intervention and makes the run incomparable.
func (o *orderingReport) recordExecuted(r result, baseline baselineOutcome, evm time.Duration) {
	role := "prefix"
	if r.Index == o.TargetIndex {
		role = "target"
	}
	outcome := orderingTxOutcome{Index: r.Index, Hash: r.Hash, Role: role, Executed: r.Error == "",
		BaselineStatus: baseline.Status, BaselineGas: baseline.Gas,
		Status: r.ActualOK, Gas: r.ActualGas, Error: r.Error, EVMms: durationMS(evm)}
	var kinds []string
	if r.Error != "" {
		outcome.StatusDiffers, outcome.GasDiffers, outcome.LogsDiffer = true, true, true
		kinds = append(kinds, confoundInvalid)
	} else {
		outcome.StatusDiffers = r.ActualOK != baseline.Status
		outcome.GasDiffers = r.ActualGas != baseline.Gas
		outcome.LogsDiffer = !logsEqual(r.Logs, baseline.Logs)
		if outcome.StatusDiffers {
			if r.ActualOK {
				kinds = append(kinds, confoundNowSucceeds)
			} else {
				kinds = append(kinds, confoundNowReverts)
			}
		}
		if outcome.GasDiffers {
			kinds = append(kinds, confoundGasChanged)
		}
		if outcome.LogsDiffer {
			kinds = append(kinds, confoundLogsChanged)
		}
	}
	outcome.DiffersFromBaseline = len(kinds) > 0
	o.Prefix = append(o.Prefix, outcome)
	switch {
	case role == "target":
		if r.Error != "" {
			o.markIncomparable("target_invalid_after_drop: " + r.Error)
		}
	case r.Index < o.firstDropped():
		if outcome.DiffersFromBaseline {
			o.markIncomparable(fmt.Sprintf("baseline_mismatch_before_drop: tx %d", r.Index))
		}
	case len(kinds) > 0:
		o.Confounds = append(o.Confounds, orderingConfound{Index: r.Index, Hash: r.Hash, Kinds: kinds})
		o.Confounded = true
	}
}

func (o *orderingReport) failClosed(txIndex int, reasons []string) {
	o.FailClosed = true
	index := txIndex
	o.FailClosedTxIndex = &index
	o.FailClosedReasons = append([]string(nil), reasons...)
	o.markIncomparable("unauthenticated_state_read_after_drop")
}

func (o *orderingReport) markIncomparable(reason string) {
	if o.IncomparableCause == "" {
		o.IncomparableCause = reason
	}
}

// finalize decides comparability once the prefix loop is over.
func (o *orderingReport) finalize() {
	targetSeen := false
	for _, outcome := range o.Prefix {
		if outcome.Role == "target" {
			targetSeen = true
		}
	}
	if !targetSeen {
		o.markIncomparable("target_not_executed")
	}
	o.Comparable = o.IncomparableCause == ""
}

// replayTiming separates in-memory EVM execution from context loading.
// EVMReplay is the latency figure for a builder that already holds state.
type replayTiming struct {
	EVMReplay   float64 `json:"evm_replay"`
	TargetEVM   float64 `json:"target_evm"`
	ContextLoad float64 `json:"context_load"`
	ProofVerify float64 `json:"proof_verify"`
	Note        string  `json:"note"`
}

const replayTimingNote = "evm_replay sums only core.ApplyTransaction over executed prefix and target transactions on the in-memory StateDB (tracer hooks included). context_load covers JSON parsing, proof-bound state construction and pre-execution system calls; proof_verify is the post-run EIP-1186 check."

func durationMS(d time.Duration) float64 {
	return float64(d.Nanoseconds()) / 1e6
}
