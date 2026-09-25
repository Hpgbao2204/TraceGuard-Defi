"""Single vocabulary bridge between E4 replay outcomes and E5 claim results."""
from __future__ import annotations
from enum import Enum


class FalsificationOutcome(str, Enum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_BLOCKING = "SUPPORTED_BLOCKING"
    REFUTED = "REFUTED"
    PARTIAL_EFFECT = "PARTIAL_EFFECT"
    NOT_TESTABLE = "NOT_TESTABLE"
    CLAIM_NOT_LOCALIZABLE = "CLAIM_NOT_LOCALIZABLE"


def from_e4(label: str) -> FalsificationOutcome:
    mapping = {
        "NECESSITY_SUPPORTED": FalsificationOutcome.SUPPORTED,
        "NECESSITY_SUPPORTED_BLOCKING": FalsificationOutcome.SUPPORTED_BLOCKING,
        "NECESSITY_REFUTED": FalsificationOutcome.REFUTED,
        "PARTIAL_EFFECT": FalsificationOutcome.PARTIAL_EFFECT,
        "NOT_TESTABLE": FalsificationOutcome.NOT_TESTABLE,
        "CAUSE": FalsificationOutcome.SUPPORTED,
        "CAUSE-NECESSARY-blocking": FalsificationOutcome.SUPPORTED_BLOCKING,
        "NOT_NECESSARY": FalsificationOutcome.REFUTED,
    }
    return mapping.get(label, FalsificationOutcome.NOT_TESTABLE)


def to_e4(label: FalsificationOutcome) -> str:
    return {
        FalsificationOutcome.SUPPORTED: "NECESSITY_SUPPORTED",
        FalsificationOutcome.SUPPORTED_BLOCKING: "NECESSITY_SUPPORTED_BLOCKING",
        FalsificationOutcome.REFUTED: "NECESSITY_REFUTED",
        FalsificationOutcome.PARTIAL_EFFECT: "PARTIAL_EFFECT",
        FalsificationOutcome.NOT_TESTABLE: "NOT_TESTABLE",
        FalsificationOutcome.CLAIM_NOT_LOCALIZABLE: "NOT_TESTABLE",
    }[label]
