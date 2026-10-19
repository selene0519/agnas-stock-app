from __future__ import annotations


ADMIN_PREFIX = "/api/admin/"
PROTECTED_MUTATION_PATHS = {
    "/api/holdings",
    "/api/holdings/import-csv",
    "/api/kis/holdings/sync",
    "/api/journal/auto-capture/run",
    "/api/journal/market-analogs/run",
}

PROTECTED_MUTATION_PREFIXES = (
    "/api/paper/",  # global paper ledgers and AI cycles are operational state
    "/api/journal/virtual-trades/capture",
    "/api/holdings/",  # legacy shared-ledger PATCH/DELETE routes
    "/api/journal/virtual-trades/evaluate",
    "/api/journal/virtual-trades/",  # per-trade review actions
    "/api/journal/self-learning/performance-gate",
    "/api/journal/self-learning/auto-calibrate",
    "/api/journal/self-learning/rollback",
    "/api/journal/calibration-suggestions/",
    "/api/journal/historical-replay",
)
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
AUTOMATION_SECRET_ROUTES = {
    ("POST", "/api/journal/auto-capture/run"),
    ("POST", "/api/admin/sync-now"),
}


def requires_admin_auth(method: str, path: str) -> bool:
    normalized_method = str(method or "").upper()
    normalized_path = str(path or "")
    if normalized_path.startswith(ADMIN_PREFIX):
        return True
    if normalized_method in MUTATING_METHODS and normalized_path in PROTECTED_MUTATION_PATHS:
        return True
    return normalized_method in MUTATING_METHODS and any(
        normalized_path.startswith(prefix) for prefix in PROTECTED_MUTATION_PREFIXES
    )


def allows_automation_secret(method: str, path: str) -> bool:
    """Limit the machine credential to the two scheduled-operation routes."""

    return (str(method or "").upper(), str(path or "")) in AUTOMATION_SECRET_ROUTES
