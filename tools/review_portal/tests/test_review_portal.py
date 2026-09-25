import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "review_portal"))
from build_review_portal import FORBIDDEN, build  # noqa: E402


def test_builds_both_blinded_bundles(tmp_path):
    result = build(tmp_path)
    assert {"reviewer_a.html", "reviewer_b.html"} <= set(result["bundles"])
    for reviewer in ("reviewer_a", "reviewer_b"):
        html = (tmp_path / f"{reviewer}.html").read_text(encoding="utf-8")
        assert len(html) > 1000
        assert html.count('"case_id"') == 40
        assert html.count('"candidate_tx_hash"') == 320
        assert f'"reviewer":"{reviewer}"' in html
        assert hashlib.sha256(html.encode()).hexdigest() == result["bundles"][f"{reviewer}.html"]["sha256"]
        assert not any(key in html for key in FORBIDDEN)


def test_generation_is_deterministic_for_same_source(tmp_path):
    first = build(tmp_path)
    first_bytes = {name: (tmp_path / name).read_bytes() for name in first["bundles"]}
    second = build(tmp_path)
    second_bytes = {name: (tmp_path / name).read_bytes() for name in second["bundles"]}
    assert first_bytes == second_bytes
    assert first["bundles"] == second["bundles"]


def test_bundle_manifest_binds_packet_manifest_and_packet_hashes(tmp_path):
    build(tmp_path)
    manifest = json.loads((tmp_path / "bundle_manifest.json").read_text())
    packet_manifest = ROOT / "corpus/annotations/review_packets/packet_manifest.json"
    assert manifest["source_packet_manifest_sha256"] == hashlib.sha256(packet_manifest.read_bytes()).hexdigest()
    for name, metadata in manifest["bundles"].items():
        assert metadata["reviewer"] in ("reviewer_a", "reviewer_b")
        assert len(metadata["sha256"]) == 64
        assert len(metadata["e4_packet_sha256"]) == 64
        assert len(metadata["hard_packet_sha256"]) == 64


def test_bundles_embed_materialized_e4_dossier_without_forbidden_labels(tmp_path):
    build(tmp_path)
    for reviewer in ("reviewer_a", "reviewer_b"):
        html = (tmp_path / f"{reviewer}.html").read_text(encoding="utf-8")
        assert '"transaction_summary":{"gas_used"' in html
        assert '"availability"' in html
        assert not any(token in html for token in (
            "root_cause_gt", "blind_candidate_factors", "supported_from_cache",
            "system_verdict", "reviewer_votes"))


def test_hard_bundle_embeds_objective_candidate_trace_display(tmp_path):
    build(tmp_path, ROOT / "corpus/annotations/review_packets_v2")
    html = (tmp_path / "reviewer_a.html").read_text(encoding="utf-8")
    assert '"observed_call_tree"' in html
    assert '"observed_contracts"' in html
    assert '"evidence_source"' in html
    assert "gt_factors" not in html
    assert "system_verdict" not in html


def test_draft_manifest_binding_uses_canonical_digest_field(tmp_path):
    build(tmp_path)
    html = (tmp_path / "reviewer_b.html").read_text(encoding="utf-8")
    assert "packet_manifest_sha256:DATA.provenance.packet_manifest_sha256" in html
    assert "packet_manifest_sha256_sha256" not in html
