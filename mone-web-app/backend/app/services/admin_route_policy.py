from __future__ import annotations


ADMIN_PREFIX = "/api/admin/"
PROTECTED_MUTATION_PREFIXES = (
    "/api/journal/virtual-trades/capture",
    "/api/journal/virtual-trades/evaluate",
    "/api/journal/virtual-trades/",  # per-trade review actions
    "/api/journal/self-learning/performance-gate",
    "/api/journal/self-learning/auto-calibrate",
    "/api/journal/self-learning/rollback",
    "/api/journal/calibration-suggestions/",
    "/api/journal/historical-replay",
)
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def requires_admin_auth(method: str, path: str) -> bool:
    normalized_method = str(method or "").upper()
    normalized_path = str(path or "")
    if normalized_path.startswith(ADMIN_PREFIX):
        return True
    return normalized_method in MUTATING_METHODS and any(
        normalized_path.startswith(prefix) for prefix in PROTECTED_MUTATION_PREFIXES
    )
