from __future__ import annotations

from typing import Any


PRODUCT_SCOPE_VERSION = "mone-advisory-paper-only-v1"
EXECUTION_MODE = "ADVISORY_PAPER_ONLY"


def product_scope() -> dict[str, Any]:
    """Canonical product authority: recommendations and Paper evidence, never broker orders."""
    return {
        "version": PRODUCT_SCOPE_VERSION,
        "executionMode": EXECUTION_MODE,
        "humanDecisionRequired": True,
        "liveBrokerOrdersSupported": False,
        "liveOrderAllowed": False,
        "brokerCredentialStorageAllowed": False,
        "automaticCapitalScalingAllowed": False,
        "paperLedgerMutationsAllowed": True,
        "recommendationOutputs": [
            "TAKE_WAIT_REJECT",
            "ENTRY_STOP_TARGET",
            "MAX_RECOMMENDED_WEIGHT",
            "RATIONALE_COUNTEREVIDENCE_UNCERTAINTY",
        ],
        "enforcement": [
            "NO_LIVE_BROKER_ORDER_CLIENT",
            "NO_LIVE_ORDER_API_ROUTE",
            "PAPER_LEDGER_ONLY",
            "USER_EXECUTES_OUTSIDE_MONE",
        ],
    }


def live_order_allowed() -> bool:
    """A non-configurable denial used wherever legacy clients expect this field."""
    return False
