# Stage 1 vNext Statistical Protocol

Version: `vnext-gates-v1`.

Comparisons use identical frozen test IDs, calibration IDs, grouping, seeds, metric definitions, and threshold-selection rules. Thresholds are selected only on calibration data and evaluated once on the frozen test set.

Primary metrics are AUPRC and recall at calibration-targeted 1% FPR. Secondary metrics are precision, realized test FPR, feature coverage, and extraction/runtime cost. Accuracy is descriptive only.

Uncertainty uses 2,000 paired bootstrap replicates, 95% confidence, and a frozen seed. Positives are resampled by incident ID; negatives by a declared dependency cluster. Every comparison reports paired deltas and confidence intervals for AUPRC, recall, and realized FPR.

Experiment order is B0 (`Call + Token + Economic`), Gate-C-enabled robustness, then optional S1 (`+ Operation Semantic`) only after B0/robustness freeze, and optional H1 hard-negative-aware training only when Gate B authorizes it.
