from __future__ import annotations

import os
from typing import Any


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except Exception:
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(value, maximum)
    return value


def heavy_jobs_enabled() -> bool:
    return env_bool("ENABLE_HEAVY_JOBS", False)


def trendline_learning_enabled() -> bool:
    return heavy_jobs_enabled() and env_bool("ENABLE_TRENDLINE_LEARNING", False)


def recommendation_max_symbols() -> int:
    return env_int("RECOMMENDATION_MAX_SYMBOLS", 20, minimum=1, maximum=50)


def validation_max_rows() -> int:
    return env_int("VALIDATION_MAX_ROWS", 500, minimum=1, maximum=5000)


def trendline_learning_max_symbols() -> int:
    return env_int("TRENDLINE_LEARNING_MAX_SYMBOLS", 20, minimum=1, maximum=100)


def trendline_learning_batch_size() -> int:
    return env_int("TRENDLINE_LEARNING_BATCH_SIZE", 10, minimum=1, maximum=50)


def clamp_limit(requested: Any, default: int, max_allowed: int) -> int:
    try:
        value = int(requested)
    except Exception:
        value = default
    return max(1, min(value, max_allowed))


def limit_meta(total_count: int, processed_count: int, limit: int, max_allowed: int, **extra: Any) -> dict[str, Any]:
    skipped = max(0, int(total_count or 0) - int(processed_count or 0))
    return {
        "limited": skipped > 0 or limit >= max_allowed,
        "limit": limit,
        "processedCount": processed_count,
        "skippedCount": skipped,
        "maxAllowed": max_allowed,
        **extra,
    }
