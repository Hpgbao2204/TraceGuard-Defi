import json
from pathlib import Path


def test_property_harm_comparison_is_descriptive_and_three_case():
    path = Path("eval/results/e5_rcfh/property_harm_comparison_v1.json")
    data = json.loads(path.read_text())
    assert data["metrics"]["case_count"] == 3
    assert data["metrics"]["property_verdictable"] == 2
    assert data["metrics"]["harm_property_agreement"] == "descriptive_only"
