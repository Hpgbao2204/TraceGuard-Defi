import json
from pathlib import Path


def test_only_validated_candidate_is_promoted():
    data = json.loads(Path("eval/results/e5_rcfh/mure_candidate_intervention_audit_v1.json").read_text())
    promoted = [x["candidate"] for x in data["candidates"] if x["status"] == "SUPPORTED_NECESSITY_BLOCKING"]
    assert promoted == ["erc1271_magic_return"]
    assert data["minimality"]["exhaustive_subset_search"] is False
