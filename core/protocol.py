"""Versioned feature contracts for maintained TraFiSec protocols."""

from __future__ import annotations

SCREENING_PROTOCOL_VERSION = "screening-grouped-v2"
SCREENING_FEATURE_CONTRACT_VERSION = "screening-grouped-v2-4view"
SCREENING_VIEWS = (
    "call_structure",
    "token_flow",
    "state_delta",
    "economic",
)


def screening_contract() -> dict[str, object]:
    """Return the canonical, serializable Stage 1 feature contract."""
    return {
        "protocol_version": SCREENING_PROTOCOL_VERSION,
        "feature_contract_version": SCREENING_FEATURE_CONTRACT_VERSION,
        "views": list(SCREENING_VIEWS),
    }


def require_screening_views(view_names: object) -> None:
    """Reject models or evaluators that silently use another view contract."""
    if tuple(view_names) != SCREENING_VIEWS:
        raise ValueError(
            "screening-grouped-v2 requires views "
            f"{list(SCREENING_VIEWS)}, got {list(view_names)}"
        )
