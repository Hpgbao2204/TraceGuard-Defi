# Legacy frame-local port

Not used for RQ3. The current runner is `tools/geth-replay/cmd/framelocal`
(see its `-mode frame-local|isolation|sham` and `eval/rq3/run_fixed20.py`).
This directory is kept only to compare against earlier runs; its
verdicts use the old 50% threshold on summed raw token amounts and a
depth-based CAUSE_BLOCKED rule, so do not cite numbers from it.
