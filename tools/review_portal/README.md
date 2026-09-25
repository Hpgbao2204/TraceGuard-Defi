# Offline M5 review portal

This portal is a presentation and data-entry layer over the existing blinded
M5 JSONL packets. It does not change the protocol, infer labels, or perform
adjudication.

## Build

From the repository root:

```bash
python3 tools/review_portal/build_review_portal.py
```

The generator reads the authoritative files in
`corpus/annotations/review_packets/` and writes self-contained bundles to
`corpus/annotations/review_bundles/`:

- `reviewer_a.html`
- `reviewer_b.html`
- `bundle_manifest.json`

Open the appropriate HTML file directly in Chrome or Edge with `file://`; no
server, network, npm, or Python service is required. Each bundle contains only
that reviewer's immutable packet and an explicit allowlist of objective packet
facts. Ground-truth fields, system verdicts, and other reviewer votes are not
embedded.

## Reviewer workflow

1. Open the supplied HTML and confirm the displayed reviewer identity.
2. Complete E4 and hard-negative reviews independently.
3. Use **Export Draft** for a backup; drafts are bound to reviewer and packet
   manifest identity.
4. When all rows validate, choose **Finalize & Export JSONL**.
5. Send the two downloaded JSONL files to the researcher without editing
   packet identity fields.

The researcher copies the files to
`corpus/annotations/review_submissions/` and runs:

```bash
python3 corpus/scripts/audit_review_workflow.py
```

Finalization does not adjudicate disagreements. Human adjudication remains a
separate step.
