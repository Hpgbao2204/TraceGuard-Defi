# TraFiSec: Experimental Reproduction Guide

This guide details the step-by-step procedure to reproduce the empirical evaluation (E1 through E6) reported in the paper.

---

## 1. Environment Setup

```bash
# 1. Clone repository
git clone <repository-url> traceguard-defi
cd TraFiSec

# 2. Virtual environment setup
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install requirements
pip install -r requirements.txt

# 4. Configure RPC keys in .env
cp .env.example .env
```

---

## 2. Research Questions and CLI Commands

### RQ1: Multi-View Screening on Standard Traffic (E1)
Evaluates the temperature-calibrated logistic screener on the fixed 60/20 incident stratified split:
```bash
python -m eval.e1_cli --mode stratified
```
- **Corrected P7 candidate:** AUPRC = 0.553254; the 1% value is a calibration target, while held-out test FPR is 3.11% (TP=10, FP=21; recall=0.625, precision=0.3226). This supports bounded-cost triage only.

### RQ2: Generalization under Distribution Shifts (E2)
Evaluates chronological holdout and leave-one-family-out cross-validation:
```bash
python -m eval.e1_cli --mode chronological
python -m eval.e1_cli --mode leave_one_family_out
```

### RQ3: Structural Near-Negatives (E3)
Tests screener robustness against complex benign arbitrage and liquidation traffic:
```bash
python -m eval.e1_cli --include-near-negatives
```
- **Corrected P7 near-negative evaluation:** AUPRC = 0.557477 and realized FPR = **11.23%** (21/187 negatives) at the frozen 1% calibration target. Human adjudication of verified hard negatives is pending in P8.

### RQ4: View Ablation Study (E2-Ablation)
Ablates individual behavioral views to measure feature contribution:
```bash
python -m eval.e2_ablation
```

### RQ5: Validity-Aware Replay Mechanics (fixed benchmark)

Replays verified incidents under counterfactual mutations on local Anvil forks:
```bash
# Replay fidelity benchmarking
python -m eval.fidelity_cli --dataset corpus/incidents.jsonl

# Necessity attribution on pilot incidents
python -m eval.necessity_cli --case cream
python -m eval.necessity_cli --case euler

# Pilot cross-platform case runner
python pilot/run_case.py --case cream
python pilot/run_case.py --case euler
python pilot/run_case.py --case wazirx
python pilot/run_case.py --case arbitrage
```

The pilot commands above are legacy historical case studies, not the frozen
20-case RQ5 benchmark and not a causal-accuracy estimate. Their outputs are
diagnostic illustrations only.
