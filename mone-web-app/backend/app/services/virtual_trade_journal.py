from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.services import data_loader as data
from app.services import final_engine
from app.services import runtime_limits

DATA_DIR = data.REPO_ROOT / "data"
REPORTS_DIR = data.REPO_ROOT / "reports"
JOURNAL_CSV = DATA_DIR / "virtual_trade_journal.csv"
EVALUATION_CSV = DATA_DIR / "virtual_trade_evaluations.csv"
AUTO_CAPTURE_STATUS_JSON = REPORTS_DIR / "virtual_trade_journal_status.json"
CALIBRATION_APPROVALS_CSV = DATA_DIR / "virtual_trade_calibration_approvals.csv"
CALIBRATION_APPLICATIONS_CSV = DATA_DIR / "virtual_trade_calibration_applications.csv"
SELF_LEARNING_STATUS_JSON = REPORTS_DIR / "virtual_trade_self_learning_status.json"
HISTORY_OPERATION_CSV = DATA_DIR / "history" / "virtual_operation_history.csv"
HISTORY_EVALUATION_CSV = DATA_DIR / "history" / "virtual_operation_evaluation.csv"
VIRTUAL_VALIDATION_RESULTS_CSV = REPORTS_DIR / "virtual_validation_results.csv"
HISTORICAL_CALIBRATION_REPORT_JSON = REPORTS_DIR / "historical_strategy_calibration.json"
CALIBRATION_PROMOTION_JSON = REPORTS_DIR / "self_correction_promotion.json"

MARKETS = {"kr", "us"}
MODES = {"conservative", "balanced", "aggressive"}
HORIZONS = {"short", "swing", "mid"}
SOURCE_TYPES = {
    "FORWARD_PAPER_TRADE",
    "MANUAL_REVIEWED",
    "HISTORICAL_REPLAY",
    "BACKTEST_EXPERIMENT",
}
JOURNAL_SESSIONS = {
    "PREMARKET_PLAN",
    "INTRADAY_CHECK",
    "AFTER_CLOSE_TRADE",
    "FOLLOWUP_EVALUATION",
}
PLAN_ONLY_SESSIONS = {"PREMARKET_PLAN", "INTRADAY_CHECK"}
DEFAULT_JOURNAL_SESSION = "AFTER_CLOSE_TRADE"
INACTIVE_V1_FAILURE_TAGS = {"REGIME_MISMATCH", "SECTOR_WEAKNESS"}
HISTORICAL_REPLAY_METHOD = "synthetic_cutoff_ohlcv_v1"
SOURCE_CALIBRATION_WEIGHTS = {
    "FORWARD_PAPER_TRADE": 1.0,
    "MANUAL_REVIEWED": 1.2,
    # Historical replay is hypothesis-generation evidence only.  It cannot
    # auto-adjust live recommendation parameters.
    "HISTORICAL_REPLAY": 0.0,
    "BACKTEST_EXPERIMENT": 0.15,
}
AUTO_CALIBRATION_POLICY = {
    # Suggestions automatically enter a zero-capital Forward incubation. Live
    # recommendation parameters may change only after the exact immutable
    # candidate earns a promotion certificate on an unseen date-blocked cohort.
    # Broker orders remain impossible; this changes advisory parameters only.
    "enabled": True,
    "mode": "PROMOTION_GATED_AUTO_APPLY",
    "version": "vtj-self-calibration-v2.3.0",
    "minEffectiveSamples": 40,
    "maxApplicationsPerRun": 1,
    "maxActiveShadowCandidates": 1,
    "maxFailureShareForAutoApply": 0.45,
    "minHoldoutSamples": 10,
    "holdoutFraction": 0.25,
    "holdoutShareFloor": 0.65,
    "minDistinctSignalDates": 30,
    "minHoldoutSignalDates": 8,
    "strictHoldoutRequired": True,
    # Historical holdout remains mandatory for unattended approval.  A human-
    # approved, zero-capital Shadow experiment may start earlier because the
    # immutable 60-date Forward comparison is its primary holdout.
    "shadowIncubationSourceTypes": ["FORWARD_PAPER_TRADE"],
    "shadowIncubationMinDistinctSignalDates": 10,
    "strictHistoricalHoldoutRequiredForShadow": False,
    "forwardPromotionIsPrimaryHoldout": True,
    "currentEvidenceRevalidationRequired": True,
    "sealedApprovalRequired": True,
    "promotionCertificateRequired": True,
    "liveCorrectionDefaultEnabled": True,
    "promotedLineageRequiredForLive": True,
    "minPrePostSamples": 30,
    "rollbackAvgPnlDropPct": 1.5,
    "rollbackWinRateDrop": 0.10,
    "reviewer": "auto_self_learning",
    "sourceMinSamples": {
        "FORWARD_PAPER_TRADE": 50,
        "MANUAL_REVIEWED": 35,
        "HISTORICAL_REPLAY": 999999,
        "BACKTEST_EXPERIMENT": 999999,
    },
    "sourceConfidenceCaps": {
        "FORWARD_PAPER_TRADE": 0.78,
        "MANUAL_REVIEWED": 0.86,
        "HISTORICAL_REPLAY": 0.0,
        "BACKTEST_EXPERIMENT": 0.35,
    },
}
CALIBRATION_PERFORMANCE_POLICY = {
    "version": "vtj-post-promotion-monitor-v1.1.0",
    "minPrePostSamples": 30,
    "minPrePostDistinctSignalDates": 30,
    "rollbackAvgPnlDropPct": 1.5,
    "rollbackWinRateDrop": 0.10,
    "rollbackIfAfterCostExpectancyNonPositive": True,
    "rollbackMinProfitFactor": 1.0,
    "rollbackMinPayoffRatio": 1.0,
    "rollbackConfidenceZ": 1.96,
    "rollbackEmergencyMinDistinctSignalDates": 10,
    "rollbackEmergencyDrawdownPct": 8.0,
    "requireCurrentApplicationLineage": True,
    "rollbackFailureAction": "QUARANTINE_ACTIVE_CORRECTION",
}
CALIBRATION_PROMOTION_VERSION = "vtj-calibration-promotion-v3"
CALIBRATION_PROMOTION_DECISION = "READY_FOR_AUTO_PROMOTION"
CALIBRATION_PROMOTION_MIN_SIGNAL_DATES = 60
CALIBRATION_PROMOTION_MIN_TRADES = 120
CALIBRATION_SHADOW_POLICY = {
    "version": "self-correction-shadow-v1.5.0",
    "inputContractVersion": "correction-shadow-input-v1",
    "maxPositions": 3,
    "maxActiveCandidates": 1,
    "positionWeight": 0.10,
    "minScore": 55.0,
    "baseMinRiskReward": {"short": 1.5, "swing": 1.8, "mid": 2.0},
    "baseMaxDistanceToEntryPct": 3.0,
    "removedExposureStaysCash": True,
    "sameSignalDatePairedComparison": True,
    "minCompleteSignalDates": CALIBRATION_PROMOTION_MIN_SIGNAL_DATES,
    "minEvaluatedChallengerTrades": CALIBRATION_PROMOTION_MIN_TRADES,
    "requiresExactApprovalAndCandidateLineage": True,
    "requiresForwardSealedRawInputs": True,
    "maxRecordingDelayHours": 36.0,
    "requiresSealAfterCanonicalClose": True,
    "requiresSealBeforeNextSessionOpen": True,
    "requiresExactEvaluationPolicyLineage": True,
    "initialRecordingGraceCalendarDays": 5,
    "maxPredictionSilenceCalendarDays": 5,
    "requiresCandidateRecordingFreshness": True,
    "terminalFailureAtPrecommittedMinimum": True,
    "requiresAfterCostPositiveReturn": True,
    "requiresAfterCostExpectancyLowerCiAboveZero": True,
    "requiresProfitFactorAboveOne": True,
    "minPayoffRatio": 1.0,
    "maxPayoffRelativeDegradationVsChampion": 0.05,
    "requiresPairedUpliftLowerCiAboveZero": True,
    "requiresDrawdownNoWorseThanChampion": True,
    "requiresValidatedResidualAlphaModel": True,
    "requiresResidualAlphaLowerCiAboveZero": True,
    "autoPromotionAllowed": True,
    "humanApprovalRequired": False,
}

# Bump this value whenever the recommendation decision contract changes.  The
# fingerprint also includes the correction/model/code versions carried by the
# recommendation, so results from materially different strategies cannot be
# mixed merely because they share the same calendar clean-window date.
STRATEGY_CONTRACT_VERSION = "mone-recommendation-v1"
CORRECTION_LIMITS = {
    "weightAdjustments": {
        "riskScore": (-0.35, 0.25),
        "qualityScore": (-0.35, 0.25),
        "momentumScore": (-0.30, 0.25),
    },
    "priceAdjustments": {
        "entryAggressiveness": (-0.15, 0.15),
        "targetMultiplier": (-0.25, 0.15),
        "stopAtrMultiplier": (-0.10, 0.40),
    },
    "filterAdjustments": {
        "maxDistanceToEntryPct": (-0.80, 1.00),
        "minRiskRewardRatio": (0.00, 0.40),
    },
}
US_MARKET_HOLIDAYS_2026 = {
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-04-03",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
}

TODAY_ENTRY = "\uc624\ub298 \uc9c4\uc785"
CONDITIONAL_ENTRY = "\uc870\uac74\ubd80 \uc9c4\uc785"
WATCH_ENTRY = "\ub300\uae30 \uad00\ucc30"

DECISION_PRIORITY = {
    TODAY_ENTRY: 0,
    CONDITIONAL_ENTRY: 1,
    WATCH_ENTRY: 2,
}
ALLOWED_DECISIONS = set(DECISION_PRIORITY)
BAD_DATA_STATUS = {"STALE", "ERROR", "NO_DATA"}
BAD_TRADE_BLOCKS = {"BLOCK", "CAUTION", "EV_NEGATIVE", "ENSEMBLE_LOW"}

ENTRY_WINDOWS = {"short": 3, "swing": 5, "mid": 10}
EVALUATION_WINDOWS = {"short": 5, "swing": 20, "mid": 60}
MARKET_COSTS = {
    "kr": {"buy_slippage": 0.001, "sell_slippage": 0.001, "tax_commission": 0.0021},
    "us": {"buy_slippage": 0.001, "sell_slippage": 0.001, "tax_commission": 0.0010},
}
EVALUATION_POLICY = {
    "version": "vtj-evaluation-v2.0.0",
    "futureBarsStrictlyAfterSignalDate": True,
    "limitFillBarTargetEmbargo": True,
    "sameBarTargetAndStop": "STOP_FIRST",
    "stopGapFill": "WORSE_OF_STOP_OR_OPEN",
    "entryWindows": ENTRY_WINDOWS,
    "evaluationWindows": EVALUATION_WINDOWS,
    "marketCosts": MARKET_COSTS,
}
# 일평균 거래금액(최근 20거래일) 기준 슬리피지 배수 — 거래량이 적은 종목은 같은 호가 슬리피지
# 가정으로는 실제 체결가 충격을 과소평가하게 됨. 시장별 절대 단위(원/달러)가 달라 임계값을 분리.
LIQUIDITY_SLIPPAGE_TIERS = {
    "kr": [(10_000_000_000, 1.0), (1_000_000_000, 1.5), (0, 2.5)],
    "us": [(50_000_000, 1.0), (5_000_000, 1.5), (0, 2.5)],
}
BENCHMARK_SYMBOLS = {
    "kr": ["KOSPI", "KOSDAQ"],
    "us": ["SPY", "QQQ", "SP500"],
}
ANALOG_FEATURES = {
    "ret_1d_pct": 2.0,
    "ret_5d_pct": 5.0,
    "ret_20d_pct": 10.0,
    "ret_60d_pct": 15.0,
    "vol_20d_pct": 2.0,
    "ma20_gap_pct": 6.0,
    "ma60_gap_pct": 10.0,
    "drawdown_20d_pct": 8.0,
    "range_20d_pct": 10.0,
    "volume_20d_ratio": 1.0,
}
MIN_ANALOG_SEPARATION_BARS = 20
MAX_ANALOG_LIMIT = 40

_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STARTED = False

JOURNAL_COLS = [
    "journal_id",
    "source_type",
    "journal_session",
    "session_note",
    "as_of_date",
    "generated_at",
    "captured_at",
    "market",
    "mode",
    "horizon",
    "symbol",
    "name",
    "decision_unit_id",
    "strategy_fingerprint",
    "strategy_contract_version",
    "strategy_identity_status",
    "correction_version_at_signal",
    "model_version_at_signal",
    "code_version_at_signal",
    "data_cutoff_at_signal",
    "decision_bucket",
    "entry_type",
    "entry_price",
    "stop_price",
    "target_price",
    "current_price_at_signal",
    "final_rank_score",
    "expected_value",
    "risk_reward_ratio",
    "probability",
    "risk_score",
    "event_risk_score",
    # Immutable event context at recommendation time.  The later postmortem
    # may use it as a hypothesis, never as proof that an event caused a loss.
    "news_event_tag",
    "disclosure_event_tag",
    "earnings_event_tag",
    "macro_event_tag",
    "sector_event_tag",
    "event_summary",
    "event_data_source_type",
    "event_reliability_score",
    "data_status",
    "data_confidence",
    "price_source",
    "market_regime_at_signal",
    "sector",
    "reject_reason",
    # 팩터 귀속분석용 기술지표 — 신호 생성 시점 snapshot
    "rsi_at_entry",
    "volume_ratio_at_entry",
    "distance_to_ma20_at_entry",
    "atr14_pct_at_entry",
    "ma_full_align_at_entry",
    "mdd20_at_entry",
    "momentum5_at_entry",
    "raw_recommendation_json",
]

EVALUATION_COLS = [
    "journal_id",
    "evaluation_policy_version",
    "evaluation_policy_fingerprint",
    "status",
    "outcome",
    "filled",
    "fill_date",
    "fill_price",
    "exit_date",
    "exit_price",
    "gross_pnl_pct",
    "net_pnl_pct",
    "mfe_pct",
    "mae_pct",
    "bars_held",
    "entry_window_days",
    "evaluation_window_days",
    "target_progress",
    "stop_progress",
    "failure_reason",
    "entryTouched",
    "targetTouched",
    "stopTouched",
    "targetBeforeStop",
    "entryTouchDate",
    "targetTouchDate",
    "stopTouchDate",
    "maxFavorableExcursion",
    "maxAdverseExcursion",
    "holdingDays",
    "failureReason",
    "diagnosticReason",
    "unknownDetail",
    "secondary_tags",
    "regime_at_entry",
    "regime_at_exit",
    "signal_confidence",
    "data_confidence",
    "review_text",
    "evaluated_at",
]

PENDING_FAILURE_REASONS = {"NO_FUTURE_BARS_YET", "PENDING_EVALUATION", "INSUFFICIENT_HOLDING_PERIOD"}
DATA_QUALITY_FAILURE_REASONS = {
    "DATA_MISSING",
    "PRICE_INVALID",
    "MISSING_ENTRY_PRICE",
    "MISSING_TARGET_OR_STOP",
    "INVALID_PRICE_PATH",
    "SYMBOL_OR_DATE_MISMATCH",
}

CALIBRATION_APPROVAL_COLS = [
    "approval_id",
    "suggestion_id",
    "decision",
    "reviewed_by",
    "reviewed_at",
    "source_summary_id",
    "market",
    "mode",
    "horizon",
    "source_type",
    "journal_session",
    "reason",
    "suggestion_status",
    "sample_count",
    "distinct_signal_dates",
    "count",
    "share",
    "threshold",
    "message",
    "before_params_json",
    "after_params_json",
    "reviewer_note",
    "policy_version",
    "policy_fingerprint",
    "evidence_fingerprint",
    "record_hash",
]

CALIBRATION_APPLICATION_COLS = [
    "application_id",
    "approval_id",
    "suggestion_id",
    "applied_by",
    "applied_at",
    "market",
    "mode",
    "horizon",
    "source_type",
    "journal_session",
    "source_weight",
    "raw_sample_count",
    "distinct_signal_dates",
    "effective_sample_count",
    "reason",
    "before_params_json",
    "after_params_json",
    "correction_version",
    "status",
    "policy_version",
    "policy_fingerprint",
    "evidence_fingerprint",
    "approval_record_hash",
    "current_suggestion_id",
    "current_evidence_fingerprint",
    "candidate_fingerprint",
    "promotion_certificate_hash",
    "record_hash",
]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not JOURNAL_CSV.exists():
        _write_rows(JOURNAL_CSV, [], JOURNAL_COLS)
    if not EVALUATION_CSV.exists():
        _write_rows(EVALUATION_CSV, [], EVALUATION_COLS)
    if not CALIBRATION_APPROVALS_CSV.exists():
        _write_rows(CALIBRATION_APPROVALS_CSV, [], CALIBRATION_APPROVAL_COLS)
    if not CALIBRATION_APPLICATIONS_CSV.exists():
        _write_rows(CALIBRATION_APPLICATIONS_CSV, [], CALIBRATION_APPLICATION_COLS)


def _read_rows(path: Path, columns: list[str]) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size <= 0:
        return []
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return [{str(k): v for k, v in row.items() if k is not None} for row in csv.DictReader(f)]
        except UnicodeDecodeError:
            continue
        except Exception:
            return []
    return []


def _write_path(path: Path) -> Path:
    if not (os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("MONE_FORCE_TEST_WRITE_REDIRECT")):
        return path
    try:
        resolved = path.resolve()
        protected = {
            (data.REPO_ROOT / "data" / "virtual_trade_journal.csv").resolve(),
            (data.REPO_ROOT / "data" / "virtual_trade_evaluations.csv").resolve(),
            (data.REPO_ROOT / "data" / "virtual_trade_calibration_approvals.csv").resolve(),
            (data.REPO_ROOT / "data" / "virtual_trade_calibration_applications.csv").resolve(),
            (data.REPO_ROOT / "reports" / "virtual_trade_journal_status.json").resolve(),
            (data.REPO_ROOT / "reports" / "virtual_trade_self_learning_status.json").resolve(),
            (data.REPO_ROOT / "reports" / "self_correction_promotion.json").resolve(),
        }
        if resolved in protected:
            root = Path(os.environ.get("MONE_PYTEST_WRITE_ROOT") or tempfile.gettempdir()) / "mone-vtj-pytest"
            return root / path.name
    except Exception:
        pass
    return path


def _write_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path = _write_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or not math.isfinite(value)):
            return None
        return float(value)
    raw = str(value).strip()
    if not raw or raw.lower() in {"nan", "none", "null", "-"}:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", raw)
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        out = float(cleaned)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _pct(value: Any) -> float | None:
    out = _safe_float(value)
    return out


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _has_consistent_realized_outcome(row: dict[str, Any]) -> bool:
    """Accept realized PnL only when its terminal label agrees with its sign."""
    pnl = _safe_float(row.get("net_pnl_pct"))
    if pnl is None:
        return False
    outcome = _upper(row.get("outcome"))
    if outcome in {"TARGET_HIT", "TARGET"}:
        return pnl > 0
    if outcome in {"STOP_HIT", "STOP_FIRST", "STOP"}:
        return pnl < 0
    return True


def _journal_session(value: Any, default: str = DEFAULT_JOURNAL_SESSION) -> str:
    session = _upper(value)
    if session in JOURNAL_SESSIONS:
        return session
    return default


def _session_filter(value: Any) -> str:
    session = _upper(value)
    if session in JOURNAL_SESSIONS:
        return session
    return "ALL"


def _read_journal_rows() -> list[dict[str, Any]]:
    rows = _read_rows(JOURNAL_CSV, JOURNAL_COLS)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        work = dict(row)
        work["journal_session"] = _journal_session(work.get("journal_session"))
        work.setdefault("session_note", "")
        normalized.append(_ensure_row_identity(work))
    return normalized


def _is_trade_evaluation_session(row: dict[str, Any]) -> bool:
    return _journal_session(row.get("journal_session")) not in PLAN_ONLY_SESSIONS


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return "{}"


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _calibration_policy_fingerprint() -> str:
    return _hash_payload(AUTO_CALIBRATION_POLICY)[:20]


def _calibration_shadow_policy_fingerprint() -> str:
    return _hash_payload(CALIBRATION_SHADOW_POLICY)[:20]


def _evaluation_policy_fingerprint() -> str:
    return _hash_payload(EVALUATION_POLICY)[:20]


def _sealed_row_hash(row: dict[str, Any], columns: list[str]) -> str:
    payload = {
        column: str(row.get(column)).strip() if row.get(column) is not None else ""
        for column in columns
        if column != "record_hash"
    }
    return _hash_payload(payload)


def _from_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or "{}"))
    except Exception:
        return {}


def _journal_id(row: dict[str, Any]) -> str:
    raw = "|".join(
        _text(row.get(key))
        for key in (
            "source_type",
            "journal_session",
            "as_of_date",
            "generated_at",
            "market",
            "mode",
            "horizon",
            "symbol",
            "entry_price",
            "stop_price",
            "target_price",
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _decision_unit_id(row: dict[str, Any]) -> str:
    """Identify one economic decision, independent of UI/session duplicates."""
    raw = "|".join(
        _text(row.get(key)).lower()
        for key in ("as_of_date", "market", "symbol")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _strategy_identity(item: dict[str, Any], row: dict[str, Any]) -> dict[str, str]:
    """Build an immutable strategy identity from point-in-time provenance.

    Observation values such as score, price, and regime are deliberately not
    included: they vary by signal and are outcomes of a strategy, not its
    identity.  A caller-supplied fingerprint wins so upstream generators can
    provide a stronger configuration hash without the journal rewriting it.
    """
    explicit = _text(item.get("strategyFingerprint") or item.get("strategy_fingerprint"))
    correction_version = _text(
        item.get("appliedCorrectionVersion")
        or item.get("correctionVersion")
        or item.get("calibrationVersion")
        or "0"
    )
    model_version = _text(
        item.get("modelVersion")
        or item.get("strategyVersion")
        or item.get("scoringVersion")
        or "unknown"
    )
    code_version = _text(
        item.get("codeVersion")
        or item.get("gitSha")
        or item.get("commitSha")
        or os.environ.get("GITHUB_SHA")
        or os.environ.get("RENDER_GIT_COMMIT")
        or "unknown"
    )
    data_cutoff = _text(
        item.get("dataCutoff")
        or item.get("dataCutoffAt")
        or item.get("asOfDate")
        or row.get("as_of_date")
    )[:19]
    payload = {
        "contract": STRATEGY_CONTRACT_VERSION,
        "market": _text(row.get("market")).lower(),
        "mode": _text(row.get("mode")).lower(),
        "horizon": _text(row.get("horizon")).lower(),
        "correctionVersion": correction_version,
        "modelVersion": model_version,
        "codeVersion": code_version,
    }
    fingerprint = explicit or hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    identity_status = "FULL" if model_version != "unknown" and code_version != "unknown" else "PARTIAL"
    return {
        "strategy_fingerprint": fingerprint,
        "strategy_contract_version": STRATEGY_CONTRACT_VERSION,
        "strategy_identity_status": identity_status,
        "correction_version_at_signal": correction_version,
        "model_version_at_signal": model_version,
        "code_version_at_signal": code_version,
        "data_cutoff_at_signal": data_cutoff,
    }


def _ensure_row_identity(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize new identity fields without pretending legacy rows are clean."""
    work = dict(row)
    work["decision_unit_id"] = _text(work.get("decision_unit_id")) or _decision_unit_id(work)
    if not _text(work.get("strategy_fingerprint")):
        work["strategy_fingerprint"] = "LEGACY_UNFINGERPRINTED"
        work["strategy_identity_status"] = "LEGACY"
    return work


def _dedupe_decision_units(
    rows: list[dict[str, Any]],
    within_strategy: bool = False,
) -> list[dict[str, Any]]:
    """Keep one highest-score record per independent economic decision.

    Strategy diagnostics retain one observation per strategy cell before
    grouping; account-level quality metrics collapse cross-strategy duplicates.
    """
    selected: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in rows:
        row = _ensure_row_identity(raw)
        key = _text(row.get("decision_unit_id"))
        if within_strategy:
            key += "|" + "|".join(
                _text(row.get(field)).lower()
                for field in ("mode", "horizon", "source_type", "journal_session")
            )
        if key not in selected:
            selected[key] = row
            order.append(key)
            continue
        previous = selected[key]
        prev_score = _safe_float(previous.get("final_rank_score"))
        next_score = _safe_float(row.get("final_rank_score"))
        if (next_score if next_score is not None else float("-inf")) > (
            prev_score if prev_score is not None else float("-inf")
        ):
            selected[key] = row
    return [selected[key] for key in order]


def _decision_bucket(item: dict[str, Any]) -> str:
    bucket = _text(item.get("decisionBucket") or item.get("decision_bucket"))
    if bucket in ALLOWED_DECISIONS:
        return bucket
    new_entry = _text(item.get("newEntryDecision"))
    if new_entry == CONDITIONAL_ENTRY:
        return CONDITIONAL_ENTRY
    execution = _text(item.get("executionStatus"))
    if execution == "\uccb4\uacb0":
        return TODAY_ENTRY
    return bucket


def _entry_type(decision_bucket: str) -> str:
    return "NEXT_OPEN" if decision_bucket == TODAY_ENTRY else "LIMIT_TOUCH"


def _confidence_from_data_status(status: str) -> str:
    up = status.upper()
    if up == "NORMAL":
        return "HIGH"
    if up == "PARTIAL":
        return "MED"
    return "LOW"


def _fmt_plan_num(value: Any, suffix: str = "") -> str:
    num = _safe_float(value)
    if num is None:
        return "-"
    if abs(num) >= 1000:
        return f"{num:,.0f}{suffix}"
    return f"{num:.2f}".rstrip("0").rstrip(".") + suffix


def _source_weight(source_type: Any) -> float:
    return float(SOURCE_CALIBRATION_WEIGHTS.get(_upper(source_type), 0.0))


def _is_calibration_admissible(row: dict[str, Any]) -> bool:
    """보정 근거로 쓸 수 있는 표본인지. SOURCE_CALIBRATION_WEIGHTS 정책을 따른다.

    가중치 0인 소스(HISTORICAL_REPLAY 등)는 가설 생성용이지 라이브 파라미터를
    움직일 근거가 아니다 — 정책 자체는 이미 위에 명시돼 있었는데 귀속분석
    경로만 그걸 안 보고 전부 풀링하고 있었다.

    2026-07-28 실측이 그 대가를 보여준다:
        HISTORICAL_REPLAY    n=1298  승률 39.8%  평균 -0.40%
        FORWARD_PAPER_TRADE  n= 569  승률 19.9%  평균 -5.58%
        풀링(기존 attribution_feedback 근거)  승률 33.7%

    즉 화면과 자가보정이 근거로 삼던 32%대 승률은 **70%가 과거 리플레이**였다.
    같은 기간 forward 실측은 19.9%/-5.58%로 훨씬 나쁘다.
    """
    return _source_weight(row.get("source_type")) > 0.0


def _source_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """소스별 표본수/승률/평균손익. 제외분을 조용히 지우지 않고 드러낸다."""
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _upper(row.get("source_type")) or "UNKNOWN"
        pnl = _safe_float(row.get("net_pnl_pct"))
        if pnl is None:
            continue
        b = buckets.setdefault(key, {"n": 0, "wins": 0, "pnl": 0.0})
        b["n"] += 1
        b["pnl"] += pnl
        if pnl > 0:
            b["wins"] += 1
    out = []
    for key, b in sorted(buckets.items(), key=lambda kv: -kv[1]["n"]):
        out.append({
            "sourceType": key,
            "calibrationWeight": _source_weight(key),
            "admissible": _source_weight(key) > 0.0,
            "n": b["n"],
            "winRate": round(b["wins"] / b["n"], 4) if b["n"] else None,
            "avgPnlPct": round(b["pnl"] / b["n"], 3) if b["n"] else None,
        })
    return out


def _candidate_numbers(item: dict[str, Any]) -> dict[str, float | None]:
    return {
        "score": _safe_float(item.get("finalRankScore") or item.get("finalScore") or item.get("recommendationScore")),
        "ev": _safe_float(item.get("expectedValue") or item.get("ev")),
        "rr": _safe_float(item.get("rrActual") or item.get("riskRewardRatio") or item.get("rr")),
        "probability": _pct(item.get("probability")),
        "risk_score": _safe_float(item.get("riskScore")),
        "event_risk": _safe_float(item.get("eventRiskScore")),
        "entry": _safe_float(item.get("entry") or item.get("entryPrice")),
        "stop": _safe_float(item.get("stop") or item.get("stopPrice")),
        "target": _safe_float(item.get("target") or item.get("targetPrice")),
        "current": _safe_float(item.get("currentPrice") or item.get("price") or item.get("lastPrice")),
    }


def _reject_reason(item: dict[str, Any]) -> str:
    market = _text(item.get("market")).lower()
    mode = _text(item.get("mode")).lower()
    horizon = _text(item.get("horizon")).lower()
    nums = _candidate_numbers(item)
    decision = _decision_bucket(item)
    data_status = _upper(item.get("dataStatus"))
    trade_block = _upper(item.get("tradeBlockStatus"))

    if market not in MARKETS:
        return "INVALID_MARKET"
    if mode not in MODES:
        return "INVALID_MODE"
    if horizon not in HORIZONS:
        return "INVALID_HORIZON"
    if nums["score"] is None or nums["score"] < 68.0:
        return "LOW_SCORE"
    if nums["ev"] is None or nums["ev"] < 1.0:
        return "LOW_EV"
    if nums["rr"] is None or nums["rr"] < 1.5:
        return "LOW_RR"
    if nums["probability"] is not None and nums["probability"] < 60.0:
        return "LOW_PROBABILITY"
    if nums["risk_score"] is not None and nums["risk_score"] < 45.0:
        return "LOW_RISK_SCORE"
    if nums["event_risk"] is not None and nums["event_risk"] > 60.0:
        return "HIGH_EVENT_RISK"
    if not data_status or data_status in BAD_DATA_STATUS:
        return "BAD_DATA_STATUS"
    if trade_block in BAD_TRADE_BLOCKS:
        return "TRADE_BLOCKED"
    if nums["entry"] is None or nums["stop"] is None or nums["target"] is None:
        return "MISSING_PRICE_LEVELS"
    if not (nums["target"] > nums["entry"] > nums["stop"]):
        return "BAD_PRICE_LEVELS"
    if decision not in ALLOWED_DECISIONS:
        return "UNSUPPORTED_DECISION"
    return ""


def _session_note_from_item(
    item: dict[str, Any],
    journal_session: str,
    nums: dict[str, float | None],
    decision: str,
    data_status: str,
) -> str:
    existing = _text(item.get("sessionNote") or item.get("journalSessionNote"))
    if existing:
        return existing
    symbol = _text(item.get("symbol")).upper()
    name = _text(item.get("name") or symbol)
    regime = _text(item.get("marketRegime") or item.get("regime") or "UNKNOWN")
    confidence = _confidence_from_data_status(data_status)
    common = (
        f"{name}({symbol}) {decision or '후보'}: "
        f"entry {_fmt_plan_num(nums.get('entry'))}, stop {_fmt_plan_num(nums.get('stop'))}, "
        f"target {_fmt_plan_num(nums.get('target'))}, EV {_fmt_plan_num(nums.get('ev'))}, "
        f"RR {_fmt_plan_num(nums.get('rr'))}, prob {_fmt_plan_num(nums.get('probability'), '%')}, "
        f"regime {regime}, data {data_status}/{confidence}."
    )
    if journal_session == "PREMARKET_PLAN":
        return (
            "장전 계획: "
            + common
            + " 손절 우선으로 가정하고, 진입가를 주지 않으면 추격하지 않는다."
        )
    if journal_session == "INTRADAY_CHECK":
        return "장중 점검: " + common + " 장중 변동이 손절/목표 중 어디에 가까운지 확인한다."
    if journal_session == "FOLLOWUP_EVALUATION":
        return "후속 복기: " + common + " 결과가 실패패턴 보정 근거로 충분한지 검토한다."
    return "장후 가상매매: " + common + " 다음 거래일 체결 가정으로 평가 대기한다."


def _snapshot_from_item(
    item: dict[str, Any],
    source_type: str,
    as_of_date: str,
    journal_session: str = DEFAULT_JOURNAL_SESSION,
) -> dict[str, Any]:
    nums = _candidate_numbers(item)
    decision = _decision_bucket(item)
    generated_at = _text(item.get("generatedAt") or item.get("recoGeneratedAt") or item.get("recommendationDate"))
    if not generated_at:
        generated_at = f"{as_of_date}T00:00:00"
    data_status = _upper(item.get("dataStatus")) or "UNKNOWN"
    row = {
        "source_type": source_type,
        "journal_session": _journal_session(journal_session),
        "session_note": _session_note_from_item(item, _journal_session(journal_session), nums, decision, data_status),
        "as_of_date": as_of_date,
        "generated_at": generated_at,
        "captured_at": _now_iso(),
        "market": _text(item.get("market")).lower(),
        "mode": _text(item.get("mode")).lower(),
        "horizon": _text(item.get("horizon")).lower(),
        "symbol": _text(item.get("symbol")).upper(),
        "name": _text(item.get("name") or item.get("symbol")).strip(),
        "decision_bucket": decision,
        "entry_type": _entry_type(decision),
        "entry_price": nums["entry"],
        "stop_price": nums["stop"],
        "target_price": nums["target"],
        "current_price_at_signal": nums["current"],
        "final_rank_score": nums["score"],
        "expected_value": nums["ev"],
        "risk_reward_ratio": nums["rr"],
        "probability": nums["probability"],
        "risk_score": nums["risk_score"],
        "event_risk_score": nums["event_risk"],
        "news_event_tag": _text(item.get("newsEventTag")),
        "disclosure_event_tag": _text(item.get("disclosureEventTag")),
        "earnings_event_tag": _text(item.get("earningsEventTag")),
        "macro_event_tag": _text(item.get("macroEventTag")),
        "sector_event_tag": _text(item.get("sectorEventTag")),
        "event_summary": _text(item.get("eventSummary"))[:300],
        "event_data_source_type": _text(item.get("eventDataSourceType")),
        "event_reliability_score": _safe_float(item.get("eventReliabilityScore")),
        "data_status": data_status,
        "data_confidence": _confidence_from_data_status(data_status),
        "price_source": _text(item.get("priceSource") or item.get("currentPriceSource")),
        "market_regime_at_signal": _text(item.get("marketRegime") or item.get("regime")),
        "sector": _text(item.get("sector")),
        "reject_reason": "",
        # 팩터 귀속분석용 기술지표 — 추천 생성 시 계산된 값 저장
        "rsi_at_entry": _safe_float(item.get("rsi14")),
        "volume_ratio_at_entry": _safe_float(item.get("volumeRatio20")),
        "distance_to_ma20_at_entry": _safe_float(item.get("distanceToMa20")),
        "atr14_pct_at_entry": _safe_float(item.get("atr14Pct")),
        "ma_full_align_at_entry": str(item.get("maFullAlign", "")).lower() in ("true", "1"),
        "mdd20_at_entry": _safe_float(item.get("mdd20")),
        "momentum5_at_entry": _safe_float(item.get("recentMomentum5")),
        "raw_recommendation_json": _json(item),
    }
    row["decision_unit_id"] = _decision_unit_id(row)
    row.update(_strategy_identity(item, row))
    row["journal_id"] = _journal_id(row)
    return row


def _relative(path: Path) -> str:
    try:
        return path.relative_to(data.REPO_ROOT).as_posix()
    except Exception:
        return path.as_posix()


def _append_new_snapshots(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    existing = _read_journal_rows()
    seen = {str(row.get("journal_id")) for row in existing}
    natural_seen = {
        "|".join(_text(row.get(k)) for k in ("source_type", "journal_session", "as_of_date", "market", "mode", "horizon", "symbol"))
        for row in existing
    }
    added: list[dict[str, Any]] = []
    duplicates = 0
    for row in rows:
        row["journal_session"] = _journal_session(row.get("journal_session"))
        row.setdefault("session_note", "")
        natural = "|".join(_text(row.get(k)) for k in ("source_type", "journal_session", "as_of_date", "market", "mode", "horizon", "symbol"))
        if row["journal_id"] in seen or natural in natural_seen:
            duplicates += 1
            continue
        seen.add(str(row["journal_id"]))
        natural_seen.add(natural)
        added.append(row)
    if added:
        _write_rows(JOURNAL_CSV, existing + added, JOURNAL_COLS)
    return added, duplicates


def capture(
    market: str = "kr",
    mode: str = "balanced",
    horizon: str = "swing",
    source_type: str = "FORWARD_PAPER_TRADE",
    journal_session: str = DEFAULT_JOURNAL_SESSION,
    limit: int = 5,
    as_of_date: str | None = None,
    include_engine: bool = True,
) -> dict[str, Any]:
    _ensure()
    market = market.lower().strip()
    mode = mode.lower().strip()
    horizon = horizon.lower().strip()
    source_type = source_type.upper().strip()
    journal_session = _journal_session(journal_session)
    if market not in MARKETS or mode not in MODES or horizon not in HORIZONS:
        return {"status": "ERROR", "error": "INVALID_SCOPE", "items": []}
    if source_type not in SOURCE_TYPES:
        return {"status": "ERROR", "error": "INVALID_SOURCE_TYPE", "items": []}
    safe_limit = max(1, min(int(limit or 5), 10))
    source_items = _source_recommendation_items(market, mode, horizon, include_engine=include_engine)
    rejected = Counter()
    accepted_items: list[dict[str, Any]] = []
    for item in source_items:
        if not isinstance(item, dict):
            continue
        reason = _reject_reason(item)
        if reason:
            rejected[reason] += 1
            continue
        accepted_items.append(item)

    accepted_items.sort(key=_rank_key)
    selected = _unique_by_symbol(accepted_items)[:safe_limit]
    snap_date = (as_of_date or _infer_as_of_date(selected) or _today())[:10]
    new_rows = [_snapshot_from_item(item, source_type, snap_date, journal_session) for item in selected]
    added, duplicates = _append_new_snapshots(new_rows)
    return {
        "status": "OK",
        "source": _relative(JOURNAL_CSV),
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "sourceType": source_type,
        "journalSession": journal_session,
        "asOfDate": snap_date,
        "includeEngine": include_engine,
        "selected": len(new_rows),
        "added": len(added),
        "duplicates": duplicates,
        "rejected": dict(rejected),
        "items": _merge_evaluations(added),
    }


def historical_replay(
    market: str = "kr",
    mode: str = "balanced",
    horizon: str = "swing",
    as_of_date: str | None = None,
    limit: int = 5,
    evaluate_after: bool = True,
) -> dict[str, Any]:
    _ensure()
    market = market.lower().strip()
    mode = mode.lower().strip()
    horizon = horizon.lower().strip()
    snap_date = _text(as_of_date)[:10]
    if market not in MARKETS or mode not in MODES or horizon not in HORIZONS:
        return {"status": "ERROR", "error": "INVALID_SCOPE", "items": []}
    if not snap_date:
        return {"status": "ERROR", "error": "MISSING_AS_OF_DATE", "items": []}
    try:
        pd.Timestamp(snap_date)
    except Exception:
        return {"status": "ERROR", "error": "INVALID_AS_OF_DATE", "items": []}

    safe_limit = max(1, min(int(limit or 5), 10))
    source_items, rejected = _historical_replay_items(market, mode, horizon, snap_date)
    source_items.sort(key=_rank_key)
    selected = _unique_by_symbol(source_items)[:safe_limit]
    new_rows = [_snapshot_from_item(item, "HISTORICAL_REPLAY", snap_date, DEFAULT_JOURNAL_SESSION) for item in selected]
    added, duplicates = _append_new_snapshots(new_rows)
    evaluation = evaluate(market, mode, horizon, "HISTORICAL_REPLAY", DEFAULT_JOURNAL_SESSION, limit=500) if evaluate_after and added else {"status": "SKIPPED"}
    return {
        "status": "OK",
        "source": _relative(JOURNAL_CSV),
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "sourceType": "HISTORICAL_REPLAY",
        "journalSession": DEFAULT_JOURNAL_SESSION,
        "asOfDate": snap_date,
        "futureDataPolicy": "generation_uses_ohlcv_date_lte_as_of_date_only",
        "replayMethod": HISTORICAL_REPLAY_METHOD,
        "syntheticCutoffReplay": True,
        "selected": len(new_rows),
        "added": len(added),
        "duplicates": duplicates,
        "rejected": dict(rejected),
        "evaluation": evaluation,
        "items": _merge_evaluations(added),
    }


def historical_replay_backfill(
    market: str = "kr",
    mode: str = "balanced",
    horizon: str = "swing",
    start_date: str | None = None,
    end_date: str | None = None,
    step_days: int = 20,
    limit: int = 5,
    max_runs: int = 30,
    evaluate_after: bool = True,
) -> dict[str, Any]:
    _ensure()
    markets = sorted(MARKETS) if _text(market).lower() == "all" else [_text(market).lower()]
    modes = sorted(MODES) if _text(mode).lower() == "all" else [_text(mode).lower()]
    horizons = sorted(HORIZONS) if _text(horizon).lower() == "all" else [_text(horizon).lower()]
    if any(mk not in MARKETS for mk in markets) or any(md not in MODES for md in modes) or any(hz not in HORIZONS for hz in horizons):
        return {"status": "ERROR", "error": "INVALID_SCOPE", "items": []}

    try:
        start = pd.Timestamp(_text(start_date)[:10]).normalize()
        end = pd.Timestamp(_text(end_date)[:10]).normalize() if _text(end_date) else pd.Timestamp(_today()).normalize() - pd.Timedelta(days=90)
    except Exception:
        return {"status": "ERROR", "error": "INVALID_DATE_RANGE", "items": []}
    if end < start:
        return {"status": "ERROR", "error": "END_BEFORE_START", "items": []}

    safe_step = max(5, min(int(step_days or 20), 90))
    safe_limit = max(1, min(int(limit or 5), 10))
    safe_max_runs = max(1, min(int(max_runs or 30), 120))
    run_count = 0
    added_total = 0
    duplicate_total = 0
    items: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end and run_count < safe_max_runs:
        as_of = cursor.date().isoformat()
        for mk in markets:
            for md in modes:
                for hz in horizons:
                    if run_count >= safe_max_runs:
                        break
                    result = historical_replay(
                        market=mk,
                        mode=md,
                        horizon=hz,
                        as_of_date=as_of,
                        limit=safe_limit,
                        evaluate_after=evaluate_after,
                    )
                    run_count += 1
                    added_total += int(result.get("added") or 0)
                    duplicate_total += int(result.get("duplicates") or 0)
                    items.append({
                        "asOfDate": as_of,
                        "market": mk,
                        "mode": md,
                        "horizon": hz,
                        "status": result.get("status"),
                        "selected": result.get("selected", 0),
                        "added": result.get("added", 0),
                        "duplicates": result.get("duplicates", 0),
                        "rejected": result.get("rejected", {}),
                    })
        cursor += pd.Timedelta(days=safe_step)

    return {
        "status": "OK",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "sourceType": "HISTORICAL_REPLAY",
        "startDate": start.date().isoformat(),
        "endDate": end.date().isoformat(),
        "stepDays": safe_step,
        "limit": safe_limit,
        "maxRuns": safe_max_runs,
        "runs": run_count,
        "added": added_total,
        "duplicates": duplicate_total,
        "futureDataPolicy": "each_generation_uses_ohlcv_date_lte_as_of_date_only_then_evaluates_after_snapshot",
        "replayMethod": HISTORICAL_REPLAY_METHOD,
        "items": items,
    }


def market_analog_replay(
    market: str = "kr",
    mode: str = "balanced",
    horizon: str = "swing",
    as_of_date: str | None = None,
    analog_limit: int = 5,
    replay_limit: int = 5,
    run_replay: bool = True,
) -> dict[str, Any]:
    _ensure()
    market = market.lower().strip()
    mode = mode.lower().strip()
    horizon = horizon.lower().strip()
    if market not in MARKETS or mode not in MODES or horizon not in HORIZONS:
        return {"status": "ERROR", "error": "INVALID_SCOPE", "items": []}
    try:
        analogs_payload = _find_market_analogs(market, as_of_date=as_of_date, limit=analog_limit, horizon=horizon)
    except Exception as exc:
        return {"status": "ERROR", "error": f"ANALOG_BUILD_FAILED: {exc}", "items": []}
    if analogs_payload.get("status") != "OK":
        return analogs_payload

    items: list[dict[str, Any]] = []
    safe_replay_limit = max(1, min(int(replay_limit or 5), 10))
    for analog in analogs_payload.get("items", []):
        work = dict(analog)
        replay_result: dict[str, Any] = {"status": "SKIPPED"}
        if run_replay:
            replay_result = historical_replay(
                market=market,
                mode=mode,
                horizon=horizon,
                as_of_date=str(analog.get("date") or ""),
                limit=safe_replay_limit,
                evaluate_after=True,
            )
        work["replay"] = {
            "status": replay_result.get("status"),
            "selected": replay_result.get("selected", 0),
            "added": replay_result.get("added", 0),
            "duplicates": replay_result.get("duplicates", 0),
            "method": replay_result.get("replayMethod", HISTORICAL_REPLAY_METHOD),
        }
        work["outcomeSummary"] = _historical_replay_outcome_summary(market, mode, horizon, str(analog.get("date") or ""))
        work["lesson"] = _analog_lesson(work)
        items.append(work)
    summary = _analog_items_summary(items)
    return {
        "status": "OK",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "asOfDate": analogs_payload.get("asOfDate"),
        "benchmarkSymbol": analogs_payload.get("benchmarkSymbol"),
        "currentVector": analogs_payload.get("currentVector"),
        "history": analogs_payload.get("history"),
        "regimeFilter": analogs_payload.get("regimeFilter"),
        "marketOutcomeSummary": analogs_payload.get("marketOutcomeSummary"),
        "replayMethod": HISTORICAL_REPLAY_METHOD,
        "futureDataPolicy": "analogs_use_benchmark_data_lte_as_of_date_then_evaluate_future_after_snapshot",
        "count": len(items),
        "summary": summary,
        "items": items,
    }


def _find_market_analogs(
    market: str,
    as_of_date: str | None = None,
    limit: int = 5,
    horizon: str = "swing",
) -> dict[str, Any]:
    bench, benchmark_symbol = _load_benchmark_ohlcv(market)
    if bench.empty:
        return {"status": "ERROR", "error": "BENCHMARK_OHLCV_UNAVAILABLE", "items": []}
    target_date = _text(as_of_date)[:10]
    work = bench.copy()
    if target_date:
        target_ts = pd.Timestamp(target_date).normalize()
        work = work[work["_date_ts"] <= target_ts].reset_index(drop=True)
    if len(work) < 90:
        return {"status": "ERROR", "error": "INSUFFICIENT_BENCHMARK_HISTORY", "items": []}
    current_idx = len(work) - 1
    current_vector = _market_vector_at(work, current_idx)
    if not current_vector:
        return {"status": "ERROR", "error": "CURRENT_VECTOR_UNAVAILABLE", "items": []}
    eval_window = EVALUATION_WINDOWS.get(horizon, 20)
    close = pd.to_numeric(work["close"], errors="coerce")
    candidates: list[dict[str, Any]] = []
    latest_ts = work.iloc[current_idx]["_date_ts"]
    max_idx = current_idx - max(eval_window, 20)
    for idx in range(60, max_idx + 1):
        vector = _market_vector_at(work, idx)
        if not vector:
            continue
        distance = _analog_distance(current_vector, vector)
        if distance is None:
            continue
        base_close = _safe_float(close.iloc[idx])
        future_close = close.iloc[idx + 1: idx + eval_window + 1].dropna()
        market_outcome: dict[str, Any] = {}
        if base_close and not future_close.empty:
            market_outcome = {
                "windowDays": len(future_close),
                "returnPct": round((float(future_close.iloc[-1]) / base_close - 1.0) * 100.0, 4),
                "maxDrawdownPct": round((float(future_close.min()) / base_close - 1.0) * 100.0, 4),
                "maxRunupPct": round((float(future_close.max()) / base_close - 1.0) * 100.0, 4),
            }
        candidates.append({
            "_index": idx,
            "date": str(work.iloc[idx]["_date_ts"].date()),
            "similarity": round(max(0.0, 1.0 - distance / 4.0), 4),
            "distance": round(distance, 4),
            "marketVector": vector,
            "marketOutcome": market_outcome,
            "futureWindowAvailableDays": int((work["_date_ts"] > work.iloc[idx]["_date_ts"]).sum()),
        })
    candidates.sort(key=lambda item: (item["distance"], item["date"]))
    safe_limit = max(1, min(int(limit or 5), MAX_ANALOG_LIMIT))
    current_regime = _text(current_vector.get("regime")).upper()
    same_regime = [
        item for item in candidates
        if _text((item.get("marketVector") or {}).get("regime")).upper() == current_regime
    ]
    # Regime is a first-class constraint when enough independent analogs exist.
    # The fallback remains explicit so sparse bear data is never overstated.
    pool = same_regime if len(same_regime) >= safe_limit else candidates
    regime_filter = "SAME_REGIME" if pool is same_regime else "MIXED_REGIME_FALLBACK"
    separation = max(MIN_ANALOG_SEPARATION_BARS, eval_window)
    selected: list[dict[str, Any]] = []
    for item in pool:
        idx = int(item["_index"])
        if any(abs(idx - int(existing["_index"])) < separation for existing in selected):
            continue
        selected.append(item)
        if len(selected) >= safe_limit:
            break
    for item in selected:
        item.pop("_index", None)
    outcome_returns = [
        _safe_float((item.get("marketOutcome") or {}).get("returnPct"))
        for item in selected
    ]
    outcome_returns = [value for value in outcome_returns if value is not None]
    outcome_drawdowns = [
        _safe_float((item.get("marketOutcome") or {}).get("maxDrawdownPct"))
        for item in selected
    ]
    outcome_drawdowns = [value for value in outcome_drawdowns if value is not None]
    market_outcome_summary = {
        "horizon": horizon,
        "sampleCount": len(outcome_returns),
        "winRate": round(sum(value > 0 for value in outcome_returns) / len(outcome_returns), 4) if outcome_returns else None,
        "averageReturnPct": round(sum(outcome_returns) / len(outcome_returns), 4) if outcome_returns else None,
        "medianReturnPct": round(float(pd.Series(outcome_returns).median()), 4) if outcome_returns else None,
        "averageMaxDrawdownPct": round(sum(outcome_drawdowns) / len(outcome_drawdowns), 4) if outcome_drawdowns else None,
        "researchOnly": True,
    }
    return {
        "status": "OK",
        "market": market,
        "asOfDate": str(latest_ts.date()),
        "benchmarkSymbol": benchmark_symbol,
        "currentVector": current_vector,
        "history": {
            "startDate": str(work.iloc[0]["_date_ts"].date()),
            "endDate": str(latest_ts.date()),
            "tradingDays": len(work),
            "independentSpacingBars": separation,
        },
        "regimeFilter": regime_filter,
        "marketOutcomeSummary": market_outcome_summary,
        "count": len(selected),
        "items": selected,
    }


def _load_benchmark_ohlcv(market: str) -> tuple[pd.DataFrame, str]:
    for symbol in BENCHMARK_SYMBOLS.get(market, []):
        # The shared loader intentionally truncates chart payloads to recent bars.
        # Market analogs need the complete on-disk benchmark history instead.
        path = DATA_DIR / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv"
        if path.exists():
            try:
                raw = pd.read_csv(path, encoding="utf-8-sig")
                if not raw.empty and "date" in raw:
                    raw["_date_ts"] = pd.to_datetime(raw["date"], errors="coerce").dt.normalize()
                    for col in ("open", "high", "low", "close", "volume"):
                        if col in raw:
                            raw[col] = pd.to_numeric(raw[col], errors="coerce")
                    raw = raw.dropna(subset=["_date_ts", "close"]).sort_values("_date_ts").drop_duplicates("_date_ts").reset_index(drop=True)
                    if len(raw) >= 90:
                        return raw, symbol
            except Exception:
                pass
        df, _source, source_type = _load_ohlcv(market, symbol)
        if df is not None and not df.empty and source_type == "actual_ohlcv":
            return df, symbol
    return pd.DataFrame(), ""


def _market_vector_at(df: pd.DataFrame, idx: int) -> dict[str, Any]:
    if idx < 60 or idx >= len(df):
        return {}
    sub = df.iloc[: idx + 1].copy()
    close = pd.to_numeric(sub["close"], errors="coerce")
    high = pd.to_numeric(sub.get("high", close), errors="coerce")
    low = pd.to_numeric(sub.get("low", close), errors="coerce")
    volume = pd.to_numeric(sub.get("volume", pd.Series([0] * len(sub))), errors="coerce").fillna(0)
    if close.dropna().shape[0] < 61:
        return {}
    last = float(close.iloc[-1])
    if not last:
        return {}

    def ret(days: int) -> float | None:
        if len(close) <= days or not close.iloc[-days - 1]:
            return None
        return round((float(close.iloc[-1]) / float(close.iloc[-days - 1]) - 1.0) * 100.0, 4)

    daily = close.pct_change().dropna()
    ma20 = float(close.tail(20).mean())
    ma60 = float(close.tail(60).mean())
    high20 = float(high.tail(20).max())
    low20 = float(low.tail(20).min())
    volume5 = float(volume.tail(5).mean() or 0.0)
    volume20 = float(volume.tail(20).mean() or 0.0)
    vector = {
        "date": str(sub.iloc[-1]["_date_ts"].date()),
        "ret_1d_pct": ret(1),
        "ret_5d_pct": ret(5),
        "ret_20d_pct": ret(20),
        "ret_60d_pct": ret(60),
        "vol_20d_pct": round(float(daily.tail(20).std() or 0.0) * 100.0, 4),
        "ma20_gap_pct": round((last / ma20 - 1.0) * 100.0, 4) if ma20 else None,
        "ma60_gap_pct": round((last / ma60 - 1.0) * 100.0, 4) if ma60 else None,
        "drawdown_20d_pct": round((last / high20 - 1.0) * 100.0, 4) if high20 else None,
        "range_20d_pct": round((high20 - low20) / last * 100.0, 4) if last else None,
        "volume_20d_ratio": round(volume5 / volume20, 4) if volume20 > 0 else None,
    }
    vector["regime"] = _compute_regime(df, sub.iloc[-1]["_date_ts"])
    return vector


def _analog_distance(current: dict[str, Any], candidate: dict[str, Any]) -> float | None:
    total = 0.0
    used = 0
    for key, scale in ANALOG_FEATURES.items():
        a = _safe_float(current.get(key))
        b = _safe_float(candidate.get(key))
        if a is None or b is None:
            continue
        total += ((a - b) / scale) ** 2
        used += 1
    if used < 6:
        return None
    return math.sqrt(total / used)


def _historical_replay_outcome_summary(market: str, mode: str, horizon: str, as_of_date: str) -> dict[str, Any]:
    rows = _merge_evaluations(_read_journal_rows())
    filtered = [
        row for row in rows
        if _text(row.get("market")).lower() == market
        and _text(row.get("mode")).lower() == mode
        and _text(row.get("horizon")).lower() == horizon
        and _upper(row.get("source_type")) == "HISTORICAL_REPLAY"
        and _text(row.get("as_of_date"))[:10] == as_of_date[:10]
        and _upper(row.get("status")) in {"EVALUATED", "CANCELLED"}
    ]
    returns = [_safe_float(row.get("net_pnl_pct")) for row in filtered]
    returns = [value for value in returns if value is not None]
    wins = [row for row in filtered if _is_positive_outcome(row)]
    failures = Counter(_text(row.get("failure_reason") or "UNKNOWN") for row in filtered)
    outcomes = Counter(_text(row.get("outcome") or "UNKNOWN") for row in filtered)
    return {
        "evaluated": len(filtered),
        "winRate": round(len(wins) / len(filtered), 4) if filtered else None,
        "avgNetPnlPct": round(sum(returns) / len(returns), 4) if returns else None,
        "outcomeCounts": dict(outcomes),
        "failureCounts": dict(failures),
        "topFailures": [
            {"reason": reason, "count": count, "share": round(count / len(filtered), 4) if filtered else 0.0}
            for reason, count in failures.most_common(3)
            if reason not in {"NONE", ""}
        ],
    }


def _is_positive_outcome(row: dict[str, Any]) -> bool:
    outcome = _text(row.get("outcome"))
    pnl = _safe_float(row.get("net_pnl_pct"))
    return outcome == "TARGET_HIT" or (pnl is not None and pnl > 0)


def _analog_lesson(item: dict[str, Any]) -> str:
    date_text = _text(item.get("date"))
    summary = item.get("outcomeSummary") if isinstance(item.get("outcomeSummary"), dict) else {}
    evaluated = int(summary.get("evaluated") or 0)
    if evaluated <= 0:
        return f"{date_text}와 유사한 장세를 찾았지만 아직 평가 가능한 replay 결과가 없습니다."
    win_rate = summary.get("winRate")
    avg = summary.get("avgNetPnlPct")
    failures = summary.get("topFailures") if isinstance(summary.get("topFailures"), list) else []
    top_failure = failures[0].get("reason") if failures else "NONE"
    win_text = "-" if win_rate is None else f"{float(win_rate) * 100:.1f}%"
    avg_text = "-" if avg is None else f"{float(avg):+.2f}%"
    return f"{date_text} 유사 장세 replay {evaluated}건: 승률 {win_text}, 평균 {avg_text}, 주요 실패 {top_failure}."


def _analog_items_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = sum(int((item.get("outcomeSummary") or {}).get("evaluated") or 0) for item in items)
    returns: list[float] = []
    failures: Counter[str] = Counter()
    for item in items:
        summary = item.get("outcomeSummary") if isinstance(item.get("outcomeSummary"), dict) else {}
        avg = _safe_float(summary.get("avgNetPnlPct"))
        count = int(summary.get("evaluated") or 0)
        if avg is not None and count:
            returns.extend([avg] * count)
        failures.update(summary.get("failureCounts") or {})
    return {
        "evaluated": evaluated,
        "avgNetPnlPct": round(sum(returns) / len(returns), 4) if returns else None,
        "topFailures": [
            {"reason": reason, "count": count, "share": round(count / evaluated, 4) if evaluated else 0.0}
            for reason, count in failures.most_common(5)
            if reason not in {"NONE", ""}
        ],
    }


def _historical_replay_items(market: str, mode: str, horizon: str, as_of_date: str) -> tuple[list[dict[str, Any]], Counter]:
    rejected: Counter[str] = Counter()
    items: list[dict[str, Any]] = []
    for symbol in _ohlcv_symbols_for_market(market):
        try:
            df, source, source_type = _load_ohlcv(market, symbol)
        except Exception:
            rejected["OHLCV_LOAD_ERROR"] += 1
            continue
        if df.empty or source_type != "actual_ohlcv":
            rejected["OHLCV_UNAVAILABLE"] += 1
            continue
        cutoff = _cutoff_ohlcv(df, as_of_date)
        if len(cutoff) < 80:
            rejected["INSUFFICIENT_CUTOFF_HISTORY"] += 1
            continue
        item = _historical_item_from_cutoff(symbol, market, mode, horizon, as_of_date, cutoff, source)
        reason = _reject_reason(item)
        if reason:
            rejected[reason] += 1
            continue
        items.append(item)
    return items, rejected


def _ohlcv_symbols_for_market(market: str) -> list[str]:
    root = DATA_DIR / "market" / "ohlcv"
    if not root.exists():
        return []
    symbols: list[str] = []
    prefix = f"{market}_"
    suffix = "_daily.csv"
    for path in sorted(root.glob(f"{prefix}*{suffix}")):
        name = path.name
        symbol = name[len(prefix): -len(suffix)]
        if symbol:
            symbols.append(symbol.upper())
    return symbols


def _cutoff_ohlcv(df: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    work = df.copy()
    if "_date_ts" not in work:
        work["_date_ts"] = pd.to_datetime(work.get("date"), errors="coerce").dt.normalize()
    cutoff = pd.Timestamp(as_of_date).normalize()
    work = work.dropna(subset=["_date_ts"]).sort_values("_date_ts")
    return work[work["_date_ts"] <= cutoff].reset_index(drop=True)


def _historical_item_from_cutoff(
    symbol: str,
    market: str,
    mode: str,
    horizon: str,
    as_of_date: str,
    cutoff: pd.DataFrame,
    source: str,
) -> dict[str, Any]:
    close = pd.to_numeric(cutoff["close"], errors="coerce").dropna()
    high = pd.to_numeric(cutoff["high"], errors="coerce").dropna() if "high" in cutoff else close
    low = pd.to_numeric(cutoff["low"], errors="coerce").dropna() if "low" in cutoff else close
    last = float(close.iloc[-1])
    ret20 = float(close.iloc[-1] / close.iloc[-21] - 1) if len(close) >= 21 and close.iloc[-21] else 0.0
    ret60 = float(close.iloc[-1] / close.iloc[-61] - 1) if len(close) >= 61 and close.iloc[-61] else 0.0
    ma20 = float(close.tail(20).mean())
    ma60 = float(close.tail(60).mean())
    vol20 = float(close.pct_change().dropna().tail(20).std() or 0.0)
    range20 = float(((high.tail(20).max() - low.tail(20).min()) / last) if last else 0.0)
    trend_bonus = 8 if ma20 > ma60 else -8
    momentum = max(-12.0, min(18.0, ret20 * 100 * 0.9 + ret60 * 100 * 0.35))
    risk_penalty = max(0.0, min(14.0, vol20 * 220 + range20 * 14))
    mode_bonus = {"conservative": -2, "balanced": 0, "aggressive": 3}.get(mode, 0)
    horizon_bonus = {"short": -1, "swing": 1, "mid": 2}.get(horizon, 0)
    score = round(64 + trend_bonus + momentum - risk_penalty + mode_bonus + horizon_bonus, 2)
    probability = round(max(50.0, min(78.0, 56 + ret20 * 95 + (4 if ma20 > ma60 else -4) - vol20 * 90 + mode_bonus)), 2)
    target_pct = {"short": 0.045, "swing": 0.085, "mid": 0.13}[horizon] * {"conservative": 0.85, "balanced": 1.0, "aggressive": 1.1}[mode]
    stop_pct = {"short": 0.025, "swing": 0.05, "mid": 0.075}[horizon] * {"conservative": 0.9, "balanced": 1.0, "aggressive": 1.1}[mode]
    rr = target_pct / stop_pct if stop_pct else 0.0
    p = probability / 100
    ev = round((p * target_pct - (1 - p) * stop_pct) * 100, 2)
    regime = "RISK_ON" if ma20 > ma60 and ret20 > 0 else "RISK_OFF" if ma20 < ma60 and ret20 < 0 else "NEUTRAL"
    return {
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "symbol": symbol,
        "name": symbol,
        "decisionBucket": TODAY_ENTRY,
        "entry": round(last, 6),
        "stop": round(last * (1 - stop_pct), 6),
        "target": round(last * (1 + target_pct), 6),
        "currentPrice": round(last, 6),
        "finalRankScore": score,
        "expectedValue": ev,
        "riskRewardRatio": round(rr, 2),
        "probability": probability,
        "riskScore": round(max(45.0, min(90.0, 76 - vol20 * 360)), 2),
        "eventRiskScore": round(max(5.0, min(55.0, vol20 * 480 + range20 * 20)), 2),
        "dataStatus": "NORMAL",
        "tradeBlockStatus": "",
        "priceSource": f"historical_ohlcv_cutoff:{_relative(Path(source)) if source else 'unknown'}",
        "marketRegime": regime,
        "generatedAt": f"{as_of_date}T23:59:00",
        "journalCaptureSource": "historical_replay_cutoff_ohlcv",
        "dataCutoffDate": as_of_date,
        "futureDataBlocked": True,
    }


def _source_recommendation_items(market: str, mode: str, horizon: str, include_engine: bool = True) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if include_engine:
        try:
            payload = final_engine.final_recommendations(market, mode, horizon, limit=200)
            api_items = payload.get("items") if isinstance(payload.get("items"), list) else []
            for item in api_items:
                if isinstance(item, dict):
                    item = dict(item)
                    item.setdefault("journalCaptureSource", "api/final/recommendations")
                    items.append(item)
        except Exception:
            pass
    report_path = data.REPORT_DIR / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"
    if report_path.exists():
        for encoding in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with report_path.open("r", encoding=encoding, newline="") as f:
                    for row in csv.DictReader(f):
                        item = {str(k): v for k, v in row.items() if k is not None}
                        item.setdefault("market", market)
                        item.setdefault("mode", mode)
                        item.setdefault("horizon", horizon)
                        item.setdefault("journalCaptureSource", _relative(report_path))
                        items.append(item)
                break
            except UnicodeDecodeError:
                continue
            except Exception:
                break
    return items


def _unique_by_symbol(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        symbol = _text(item.get("symbol")).upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(item)
    return out


def _infer_as_of_date(items: list[dict[str, Any]]) -> str:
    for item in items:
        for key in ("generatedAt", "recoGeneratedAt", "recommendationDate", "dataAsOf"):
            text = _text(item.get(key))
            if len(text) >= 10 and text[:4].isdigit():
                return text[:10]
    return ""


def _rank_key(item: dict[str, Any]) -> tuple[int, float, float, float]:
    nums = _candidate_numbers(item)
    return (
        DECISION_PRIORITY.get(_decision_bucket(item), 99),
        -(nums["ev"] or 0.0),
        -(nums["score"] or 0.0),
        -(nums["rr"] or 0.0),
    )


def list_trades(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
    status: str = "all",
    limit: int = 100,
) -> dict[str, Any]:
    _ensure()
    rows = _merge_evaluations(_read_journal_rows())
    rows = _filter_rows(rows, market, mode, horizon, source_type, journal_session, status)
    rows.sort(key=lambda r: _text(r.get("captured_at") or r.get("generated_at")), reverse=True)
    safe_limit = max(1, min(int(limit or 100), 1000))
    return {
        "status": "OK",
        "source": _relative(JOURNAL_CSV),
        "count": len(rows),
        "items": rows[:safe_limit],
    }


def _filter_rows(
    rows: list[dict[str, Any]],
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
    status: str = "all",
) -> list[dict[str, Any]]:
    market = market.lower().strip()
    mode = mode.lower().strip()
    horizon = horizon.lower().strip()
    source_type = source_type.upper().strip()
    journal_session = _session_filter(journal_session)
    status = status.upper().strip()
    out = rows
    if market in MARKETS:
        out = [row for row in out if _text(row.get("market")).lower() == market]
    if mode in MODES:
        out = [row for row in out if _text(row.get("mode")).lower() == mode]
    if horizon in HORIZONS:
        out = [row for row in out if _text(row.get("horizon")).lower() == horizon]
    if source_type in SOURCE_TYPES:
        out = [row for row in out if _upper(row.get("source_type")) == source_type]
    if journal_session in JOURNAL_SESSIONS:
        out = [row for row in out if _journal_session(row.get("journal_session")) == journal_session]
    if status != "ALL":
        out = [row for row in out if _upper(row.get("status") or "OPEN") == status]
    return out


def _merge_evaluations(journal_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eval_rows = _read_rows(EVALUATION_CSV, EVALUATION_COLS)
    latest: dict[str, dict[str, Any]] = {}
    for row in eval_rows:
        jid = _text(row.get("journal_id"))
        if not jid:
            continue
        old = latest.get(jid)
        if old is None or _text(row.get("evaluated_at")) >= _text(old.get("evaluated_at")):
            latest[jid] = row
    merged: list[dict[str, Any]] = []
    for row in journal_rows:
        jid = _text(row.get("journal_id"))
        item = dict(row)
        ev = latest.get(jid)
        if ev:
            item.update(ev)
        else:
            item["status"] = "OPEN"
            item["outcome"] = "PENDING"
        item["raw_recommendation"] = _from_json(item.pop("raw_recommendation_json", "{}"))
        merged.append(item)
    return merged


def evaluate(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
    limit: int = 200,
    force: bool = False,
) -> dict[str, Any]:
    _ensure()
    journal_rows = _read_journal_rows()
    merged = _merge_evaluations(journal_rows)
    scope = _filter_rows(merged, market, mode, horizon, source_type, journal_session, "all")
    scope = [row for row in scope if _is_trade_evaluation_session(row)]
    if not force:
        scope = [row for row in scope if _upper(row.get("status") or "OPEN") not in {"EVALUATED", "CANCELLED", "DATA_INVALID"}]
    safe_limit = max(1, min(int(limit or 200), 1000))
    scope = scope[:safe_limit]
    existing_eval = _read_rows(EVALUATION_CSV, EVALUATION_COLS)
    replaced = {_text(row.get("journal_id")) for row in scope}
    kept_eval = [row for row in existing_eval if _text(row.get("journal_id")) not in replaced]
    evaluated = [_evaluate_one(row) for row in scope]
    if evaluated:
        _write_rows(EVALUATION_CSV, kept_eval + evaluated, EVALUATION_COLS)
        # A loss gets one immutable entry-time event snapshot for postmortem.
        # The postmortem service de-duplicates journal/date/failure keys, so
        # force-evaluation cannot create duplicate explanations.
        try:
            from app.services import postmortem

            for source_row, evaluation in zip(scope, evaluated):
                raw = source_row.get("raw_recommendation") if isinstance(source_row.get("raw_recommendation"), dict) else {}
                postmortem_row = {
                    **source_row,
                    **evaluation,
                    "exitStatus": evaluation.get("outcome"),
                    "executionStatus": "EXECUTED" if evaluation.get("filled") else "NOT_EXECUTED",
                    "pnlPct": evaluation.get("net_pnl_pct"),
                    "execution": {"exitStatus": evaluation.get("outcome"), "pnlPct": evaluation.get("net_pnl_pct")},
                    "newsEventTag": source_row.get("news_event_tag") or raw.get("newsEventTag"),
                    "disclosureEventTag": source_row.get("disclosure_event_tag") or raw.get("disclosureEventTag"),
                    "earningsEventTag": source_row.get("earnings_event_tag") or raw.get("earningsEventTag"),
                    "macroEventTag": source_row.get("macro_event_tag") or raw.get("macroEventTag"),
                    "sectorEventTag": source_row.get("sector_event_tag") or raw.get("sectorEventTag"),
                    "eventRiskScore": source_row.get("event_risk_score"),
                    "eventSummary": source_row.get("event_summary") or raw.get("eventSummary"),
                    "eventDataSourceType": source_row.get("event_data_source_type") or raw.get("eventDataSourceType"),
                    "dataSourceType": source_row.get("data_confidence"),
                }
                postmortem.save_postmortem(postmortem_row, validation_date=str(evaluation.get("evaluated_at") or "")[:10] or None)
        except Exception:
            pass
    counts = Counter(row.get("outcome") for row in evaluated)
    return {
        "status": "OK",
        "source": _relative(EVALUATION_CSV),
        "evaluated": len(evaluated),
        "outcomes": dict(counts),
        "items": evaluated,
    }


def _load_ohlcv(market: str, symbol: str) -> tuple[pd.DataFrame, str, str]:
    try:
        df, source = data._load_ohlcv(symbol, market)  # type: ignore[attr-defined]
    except Exception:
        path = data.REPO_ROOT / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv"
        if not path.exists():
            return pd.DataFrame(), "", "unavailable"
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
            source = str(path)
        except Exception:
            return pd.DataFrame(), "", "unavailable"
    if df is None or df.empty or "date" not in df:
        return pd.DataFrame(), str(source or ""), "unavailable"
    work = df.copy()
    work["_date_ts"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    for col in ("open", "high", "low", "close"):
        if col in work:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["_date_ts"]).sort_values("_date_ts").reset_index(drop=True)
    source_type = "actual_ohlcv"
    if "close-history fallback" in str(source).lower():
        source_type = "close_history_fallback"
    return work, str(source or ""), source_type


def _liquidity_slippage_multiplier(ohlcv: pd.DataFrame, market: str, as_of_ts: "pd.Timestamp") -> float:
    """as_of 시점까지(미래 데이터 누출 없이)의 최근 20거래일 평균 거래금액으로 슬리피지 배수를 정한다."""
    try:
        past = ohlcv[ohlcv["_date_ts"] <= as_of_ts].tail(20)
        if past.empty or "volume" not in past or "close" not in past:
            return 1.0
        dollar_vol = float((pd.to_numeric(past["close"], errors="coerce") * pd.to_numeric(past["volume"], errors="coerce")).mean())
        if not math.isfinite(dollar_vol) or dollar_vol <= 0:
            return 1.0
        for threshold, mult in LIQUIDITY_SLIPPAGE_TIERS.get(market, LIQUIDITY_SLIPPAGE_TIERS["kr"]):
            if dollar_vol >= threshold:
                return mult
        return 2.5
    except Exception:
        return 1.0


def _evaluate_one(row: dict[str, Any]) -> dict[str, Any]:
    market = _text(row.get("market")).lower()
    symbol = _text(row.get("symbol")).upper()
    horizon = _text(row.get("horizon")).lower()
    as_of_date = _text(row.get("as_of_date"))[:10]
    entry = _safe_float(row.get("entry_price"))
    stop = _safe_float(row.get("stop_price"))
    target = _safe_float(row.get("target_price"))
    if market not in MARKETS or horizon not in HORIZONS or not symbol or not as_of_date:
        return _evaluation_stub(row, "DATA_INVALID", "DATA_INVALID", "Invalid journal scope.", failure_reason="SYMBOL_OR_DATE_MISMATCH")
    if entry is None:
        return _evaluation_stub(row, "DATA_INVALID", "DATA_INVALID", "Missing entry price.", failure_reason="MISSING_ENTRY_PRICE")
    if stop is None or target is None:
        return _evaluation_stub(row, "DATA_INVALID", "DATA_INVALID", "Missing target or stop price.", failure_reason="MISSING_TARGET_OR_STOP")
    if entry <= 0 or stop <= 0 or target <= 0 or not (target > entry > stop):
        return _evaluation_stub(row, "DATA_INVALID", "DATA_INVALID", "Invalid price levels.", failure_reason="PRICE_INVALID")
    ohlcv, _source, source_type = _load_ohlcv(market, symbol)
    if ohlcv.empty:
        return _evaluation_stub(row, "DATA_PENDING", "DATA_PENDING", "No OHLCV available.", failure_reason="SYMBOL_OR_DATE_MISMATCH")
    try:
        as_of_ts = pd.Timestamp(as_of_date).normalize()
    except Exception:
        return _evaluation_stub(row, "DATA_INVALID", "DATA_INVALID", "Invalid as_of_date.", failure_reason="SYMBOL_OR_DATE_MISMATCH")
    future = ohlcv[ohlcv["_date_ts"] > as_of_ts].reset_index(drop=True)
    if future.empty:
        return _evaluation_stub(row, "DATA_PENDING", "DATA_PENDING", "No future bars yet.", failure_reason="NO_FUTURE_BARS_YET")

    entry_window = ENTRY_WINDOWS[horizon]
    eval_window = EVALUATION_WINDOWS[horizon]
    entry_type = _upper(row.get("entry_type")) or "LIMIT_TOUCH"
    fill_idx, fill_date, raw_fill = _find_fill(future, entry, entry_type, entry_window)
    if fill_idx is None:
        if len(future) < entry_window:
            return _evaluation_stub(row, "PENDING", "PENDING", "Entry window still open.", failure_reason="PENDING_EVALUATION")
        out = _evaluation_stub(row, "CANCELLED", "CANCELLED_NOT_FILLED", "Entry price was not touched.")
        out.update({"entry_window_days": entry_window, "evaluation_window_days": eval_window, "failureReason": "ENTRY_NOT_TOUCHED"})
        return out

    holding = future.iloc[fill_idx: fill_idx + eval_window].reset_index(drop=True)
    if holding.empty:
        return _evaluation_stub(row, "PENDING", "PENDING", "No holding bars after fill.", failure_reason="INSUFFICIENT_HOLDING_PERIOD", diagnostic_reason="ENTRY_TOUCHED_BUT_NO_EXIT")

    costs = MARKET_COSTS.get(market, MARKET_COSTS["kr"])
    liquidity_mult = _liquidity_slippage_multiplier(ohlcv, market, as_of_ts)
    actual_buy = raw_fill * (1 + costs["buy_slippage"] * liquidity_mult)
    exit_info = _find_exit(
        holding,
        entry,
        stop,
        target,
        eval_window,
        allow_first_bar_target=entry_type == "NEXT_OPEN",
    )
    if not exit_info["completed"] and not exit_info["terminal"]:
        return _pending_eval(row, fill_date, actual_buy, entry_window, eval_window, holding, entry, stop, target)

    raw_exit = float(exit_info["exit_price"])
    actual_sell = raw_exit * (1 - costs["sell_slippage"] * liquidity_mult - costs["tax_commission"])
    gross = _round_pct((raw_exit - raw_fill) / raw_fill * 100) if raw_fill else None
    net = _round_pct((actual_sell - actual_buy) / actual_buy * 100) if actual_buy else None
    mfe, mae = _mfe_mae(holding.iloc[: int(exit_info["bars_held"])], entry)
    target_progress, stop_progress = _progress(entry, target, stop, mfe, mae)
    exit_ts = pd.Timestamp(exit_info["exit_date"]).normalize() if exit_info.get("exit_date") else None
    regime_at_exit = _compute_regime(ohlcv, exit_ts) if exit_ts is not None else ""
    outcome = _outcome(exit_info["exit_kind"], target_progress, stop_progress, net)
    failure = _failure_reason(row, outcome, mfe, mae, net, regime_at_exit, fill_price=raw_fill)
    touch_failure = _touch_failure_reason(outcome, net)
    sec_tags = _secondary_tags(outcome, failure, _text(row.get("sector")), mfe, mae)
    review_text = _review_text(row, outcome, failure, net, mfe, mae, regime_at_exit)
    return {
        "journal_id": row.get("journal_id"),
        "evaluation_policy_version": EVALUATION_POLICY["version"],
        "evaluation_policy_fingerprint": _evaluation_policy_fingerprint(),
        "status": "EVALUATED" if outcome not in {"CANCELLED_NOT_FILLED", "PENDING"} else "CANCELLED",
        "outcome": outcome,
        "filled": True,
        "fill_date": fill_date,
        "fill_price": round(actual_buy, 6),
        "exit_date": exit_info["exit_date"],
        "exit_price": round(actual_sell, 6),
        "gross_pnl_pct": gross,
        "net_pnl_pct": net,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "bars_held": exit_info["bars_held"],
        "entry_window_days": entry_window,
        "evaluation_window_days": eval_window,
        "target_progress": target_progress,
        "stop_progress": stop_progress,
        "failure_reason": failure,
        "entryTouched": True,
        "targetTouched": bool(exit_info.get("targetTouched")),
        "stopTouched": bool(exit_info.get("stopTouched")),
        "targetBeforeStop": exit_info.get("targetBeforeStop", ""),
        "entryTouchDate": fill_date,
        "targetTouchDate": exit_info.get("targetTouchDate", ""),
        "stopTouchDate": exit_info.get("stopTouchDate", ""),
        "maxFavorableExcursion": mfe,
        "maxAdverseExcursion": mae,
        "holdingDays": exit_info["bars_held"],
        "failureReason": touch_failure,
        "diagnosticReason": failure,
        "unknownDetail": "",
        "secondary_tags": sec_tags,
        "regime_at_entry": row.get("market_regime_at_signal", ""),
        "regime_at_exit": regime_at_exit,
        "signal_confidence": _signal_confidence(row),
        "data_confidence": "LOW" if source_type != "actual_ohlcv" else row.get("data_confidence", ""),
        "review_text": review_text,
        "evaluated_at": _now_iso(),
    }


def _evaluation_stub(
    row: dict[str, Any],
    status: str,
    outcome: str,
    review_text: str,
    failure_reason: str = "",
    diagnostic_reason: str = "",
    unknown_detail: str = "",
) -> dict[str, Any]:
    canonical_reason = failure_reason or classify_failure_reason({"status": status, "outcome": outcome, "review_text": review_text})
    detail = unknown_detail or review_text if canonical_reason == "UNKNOWN" else ""
    return {
        "journal_id": row.get("journal_id"),
        "evaluation_policy_version": EVALUATION_POLICY["version"],
        "evaluation_policy_fingerprint": _evaluation_policy_fingerprint(),
        "status": status,
        "outcome": outcome,
        "filled": False,
        "fill_date": "",
        "fill_price": "",
        "exit_date": "",
        "exit_price": "",
        "gross_pnl_pct": "",
        "net_pnl_pct": "",
        "mfe_pct": "",
        "mae_pct": "",
        "bars_held": 0,
        "entry_window_days": "",
        "evaluation_window_days": "",
        "target_progress": "",
        "stop_progress": "",
        "failure_reason": "DATA_QUALITY" if canonical_reason in DATA_QUALITY_FAILURE_REASONS else "",
        "entryTouched": False,
        "targetTouched": False,
        "stopTouched": False,
        "targetBeforeStop": "",
        "entryTouchDate": "",
        "targetTouchDate": "",
        "stopTouchDate": "",
        "maxFavorableExcursion": "",
        "maxAdverseExcursion": "",
        "holdingDays": 0,
        "failureReason": canonical_reason,
        "diagnosticReason": diagnostic_reason or canonical_reason,
        "unknownDetail": detail,
        "secondary_tags": "",
        "regime_at_entry": row.get("market_regime_at_signal", ""),
        "regime_at_exit": "",
        "signal_confidence": _signal_confidence(row),
        "data_confidence": row.get("data_confidence", ""),
        "review_text": review_text,
        "evaluated_at": _now_iso(),
    }


def _find_fill(future: pd.DataFrame, entry: float, entry_type: str, entry_window: int) -> tuple[int | None, str, float]:
    if entry_type == "NEXT_OPEN":
        row = future.iloc[0]
        raw_fill = _safe_float(row.get("open")) or _safe_float(row.get("close")) or entry
        return 0, _row_date(row), float(raw_fill)
    entry_window_df = future.head(entry_window)
    for idx, bar in entry_window_df.iterrows():
        high = _safe_float(bar.get("high")) or _safe_float(bar.get("close"))
        low = _safe_float(bar.get("low")) or _safe_float(bar.get("close"))
        if high is None or low is None:
            continue
        if low <= entry <= high:
            return int(idx), _row_date(bar), float(entry)
    return None, "", 0.0


def _row_date(row: Any) -> str:
    value = row.get("date") if hasattr(row, "get") else ""
    return str(value or "")[:10]


def _find_exit(
    holding: pd.DataFrame,
    entry: float,
    stop: float,
    target: float,
    eval_window: int,
    *,
    allow_first_bar_target: bool = True,
) -> dict[str, Any]:
    first_target_date = ""
    first_stop_date = ""
    for idx, bar in holding.iterrows():
        high = _safe_float(bar.get("high")) or _safe_float(bar.get("close"))
        low = _safe_float(bar.get("low")) or _safe_float(bar.get("close"))
        open_price = _safe_float(bar.get("open")) or _safe_float(bar.get("close"))
        close = _safe_float(bar.get("close")) or entry
        if high is None or low is None:
            continue
        target_hit = high >= target
        stop_hit = low <= stop
        # A daily LIMIT_TOUCH bar does not reveal whether its high occurred
        # before or after the entry was filled. Never credit a target on that
        # first bar unless entry was fixed at the opening print.
        if int(idx) == 0 and not allow_first_bar_target:
            target_hit = False
        row_date = _row_date(bar)
        if target_hit and stop_hit:
            first_target_date = first_target_date or row_date
            first_stop_date = first_stop_date or row_date
            stop_fill = min(stop, open_price) if open_price is not None else stop
            return _exit_payload("STOP", stop_fill, row_date, int(idx) + 1, first_target_date, first_stop_date, target_before_stop=False)
        if stop_hit:
            first_stop_date = first_stop_date or row_date
            stop_fill = min(stop, open_price) if open_price is not None else stop
            return _exit_payload("STOP", stop_fill, row_date, int(idx) + 1, first_target_date, first_stop_date, target_before_stop=False)
        if target_hit:
            first_target_date = first_target_date or row_date
            return _exit_payload("TARGET", target, row_date, int(idx) + 1, first_target_date, first_stop_date, target_before_stop=True)
        if int(idx) + 1 >= eval_window:
            return _exit_payload("TIME", close, row_date, int(idx) + 1, first_target_date, first_stop_date, target_before_stop="")
    last = holding.iloc[-1]
    close = _safe_float(last.get("close")) or entry
    return _exit_payload("PENDING", close, _row_date(last), len(holding), first_target_date, first_stop_date, target_before_stop="", completed=False)


def _exit_payload(
    exit_kind: str,
    exit_price: float,
    exit_date: str,
    bars_held: int,
    target_date: str,
    stop_date: str,
    target_before_stop: bool | str,
    completed: bool = True,
) -> dict[str, Any]:
    return {
        "terminal": exit_kind in {"TARGET", "STOP"},
        "completed": completed,
        "exit_kind": exit_kind,
        "exit_price": exit_price,
        "exit_date": exit_date,
        "bars_held": bars_held,
        "targetTouched": bool(target_date),
        "stopTouched": bool(stop_date),
        "targetBeforeStop": target_before_stop,
        "targetTouchDate": target_date,
        "stopTouchDate": stop_date,
    }


def _pending_eval(
    row: dict[str, Any],
    fill_date: str,
    actual_buy: float,
    entry_window: int,
    eval_window: int,
    holding: pd.DataFrame,
    entry: float,
    stop: float,
    target: float,
) -> dict[str, Any]:
    mfe, mae = _mfe_mae(holding, entry)
    target_progress, stop_progress = _progress(entry, target, stop, mfe, mae)
    out = _evaluation_stub(
        row,
        "PENDING",
        "PENDING",
        "Evaluation window still open.",
        failure_reason="INSUFFICIENT_HOLDING_PERIOD",
        diagnostic_reason="ENTRY_TOUCHED_BUT_NO_EXIT",
    )
    out.update({
        "filled": True,
        "fill_date": fill_date,
        "fill_price": round(actual_buy, 6),
        "bars_held": len(holding),
        "entry_window_days": entry_window,
        "evaluation_window_days": eval_window,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "target_progress": target_progress,
        "stop_progress": stop_progress,
        "entryTouched": True,
        "targetTouched": False,
        "stopTouched": False,
        "targetBeforeStop": "",
        "entryTouchDate": fill_date,
        "maxFavorableExcursion": mfe,
        "maxAdverseExcursion": mae,
        "holdingDays": len(holding),
        "failureReason": "INSUFFICIENT_HOLDING_PERIOD",
        "diagnosticReason": "ENTRY_TOUCHED_BUT_NO_EXIT",
        "unknownDetail": "",
    })
    return out


def _mfe_mae(holding: pd.DataFrame, entry: float) -> tuple[float | None, float | None]:
    highs = [_safe_float(v) for v in holding.get("high", pd.Series(dtype=float)).tolist()]
    lows = [_safe_float(v) for v in holding.get("low", pd.Series(dtype=float)).tolist()]
    highs = [v for v in highs if v is not None]
    lows = [v for v in lows if v is not None]
    mfe = _round_pct((max(highs) - entry) / entry * 100) if highs and entry else None
    mae = _round_pct((min(lows) - entry) / entry * 100) if lows and entry else None
    return mfe, mae


def _progress(entry: float, target: float, stop: float, mfe: float | None, mae: float | None) -> tuple[float | None, float | None]:
    target_dist = (target - entry) / entry * 100 if entry and target > entry else None
    stop_dist = (entry - stop) / entry * 100 if entry and stop < entry else None
    target_progress = round((mfe or 0.0) / target_dist, 4) if target_dist and target_dist > 0 else None
    stop_progress = round(abs(mae or 0.0) / stop_dist, 4) if stop_dist and stop_dist > 0 else None
    return target_progress, stop_progress


def _outcome(exit_kind: str, target_progress: float | None, stop_progress: float | None, net: float | None) -> str:
    if exit_kind == "TARGET":
        return "TARGET_HIT"
    if exit_kind == "STOP":
        return "STOP_HIT"
    tp = target_progress or 0.0
    sp = stop_progress or 0.0
    if tp >= 0.80 and sp < 0.80:
        return "TIME_EXIT_NEAR_TARGET"
    if sp >= 0.80 and tp < 0.80:
        return "TIME_EXIT_NEAR_STOP"
    if tp >= 0.80 and sp >= 0.80:
        return "TIME_EXIT_NEAR_STOP" if (net or 0.0) < 0 else "TIME_EXIT_MID"
    if abs(net or 0.0) <= 0.5 and tp < 0.40 and sp < 0.40:
        return "TIME_EXIT_FLAT"
    return "TIME_EXIT_MID"


def _touch_failure_reason(outcome: str, net: float | None) -> str:
    if outcome == "TARGET_HIT":
        return "TARGET_BEFORE_STOP"
    if outcome == "STOP_HIT":
        return "STOP_BEFORE_TARGET"
    if outcome in {"TIME_EXIT_NEAR_TARGET", "TIME_EXIT_MID", "TIME_EXIT_FLAT"}:
        return "TARGET_NOT_REACHED" if (net or 0.0) >= 0 else "DIRECTION_FAILED"
    if outcome == "TIME_EXIT_NEAR_STOP":
        return "DIRECTION_FAILED"
    if outcome == "CANCELLED_NOT_FILLED":
        return "ENTRY_NOT_TOUCHED"
    if outcome.startswith("DATA"):
        return "DATA_MISSING"
    if outcome == "PENDING":
        return "PENDING_EVALUATION"
    return "UNKNOWN"


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return None


def classify_failure_reason(row: dict[str, Any]) -> str:
    """Normalize legacy and pending virtual-trade outcomes into diagnostic failureReason codes."""
    explicit = _upper(row.get("failureReason"))
    if explicit and explicit not in {"UNKNOWN", "NONE", "NAN"}:
        return explicit

    detail_reason = _upper(row.get("failure_reason"))
    if detail_reason and detail_reason not in {"UNKNOWN", "NONE", "NAN", "DATA_QUALITY"}:
        if detail_reason == "STOP_HIT":
            return "STOP_BEFORE_TARGET"
        if detail_reason == "TARGET_HIT":
            return "TARGET_BEFORE_STOP"
        if detail_reason.startswith("TIME_EXIT"):
            return "TARGET_NOT_REACHED"
        return detail_reason

    status = _upper(row.get("status"))
    outcome = _upper(row.get("outcome"))
    review_text = _text(row.get("review_text")).lower()
    entry_touched = _boolish(row.get("entryTouched"))
    target_touched = _boolish(row.get("targetTouched"))
    stop_touched = _boolish(row.get("stopTouched"))

    if "no future bars yet" in review_text:
        return "NO_FUTURE_BARS_YET"
    if "entry window still open" in review_text:
        return "PENDING_EVALUATION"
    if "evaluation window still open" in review_text or "no holding bars after fill" in review_text:
        return "INSUFFICIENT_HOLDING_PERIOD"
    if "no ohlcv available" in review_text or "invalid as_of_date" in review_text or "invalid journal scope" in review_text:
        return "SYMBOL_OR_DATE_MISMATCH"
    if "missing entry price" in review_text:
        return "MISSING_ENTRY_PRICE"
    if "missing target or stop" in review_text:
        return "MISSING_TARGET_OR_STOP"
    if "invalid price levels" in review_text:
        return "PRICE_INVALID"

    if outcome == "STOP_HIT":
        return "STOP_BEFORE_TARGET"
    if outcome == "TARGET_HIT":
        return "TARGET_BEFORE_STOP"
    if outcome == "CANCELLED_NOT_FILLED" or entry_touched is False:
        return "ENTRY_NOT_TOUCHED"
    if outcome.startswith("DATA"):
        return "DATA_MISSING"
    if outcome.startswith("TIME_EXIT"):
        return "TARGET_NOT_REACHED"
    if status == "PENDING":
        return "INSUFFICIENT_HOLDING_PERIOD" if entry_touched is True else "PENDING_EVALUATION"
    if entry_touched is True and target_touched is False and stop_touched is False:
        return "ENTRY_TOUCHED_BUT_NO_EXIT"
    if entry_touched is True:
        return "UNCLASSIFIED_PRICE_PATH"
    return "UNKNOWN"


def _failure_reason(
    row: dict[str, Any],
    outcome: str,
    mfe: float | None,
    mae: float | None,
    net: float | None,
    regime_at_exit: str = "",
    fill_price: float | None = None,
) -> str:
    if outcome == "TARGET_HIT" and (net or 0.0) > 0:
        return "NONE"
    data_conf = _upper(row.get("data_confidence"))
    data_status = _upper(row.get("data_status"))
    if data_conf == "LOW" or data_status == "PARTIAL":
        return "DATA_QUALITY"
    if outcome == "CANCELLED_NOT_FILLED":
        return "ENTRY_TIMING"
    if outcome == "TIME_EXIT_NEAR_TARGET":
        return "TARGET_TOO_FAR"
    if outcome in {"TIME_EXIT_MID", "TIME_EXIT_FLAT"} and (net or 0.0) >= 0:
        return "THESIS_VALID_BUT_SLOW"
    if outcome == "TIME_EXIT_NEAR_STOP":
        return "ENTRY_TIMING"
    if outcome == "STOP_HIT":
        entry = _safe_float(row.get("entry_price"))
        # Gap at fill: next-open deviated > 2% from expected entry
        if (
            _upper(row.get("entry_type")) == "NEXT_OPEN"
            and fill_price is not None
            and entry is not None
            and entry > 0
            and abs(fill_price / entry - 1) > 0.02
        ):
            return "MARKET_GAP"
        # Regime deterioration
        regime_entry = _upper(row.get("market_regime_at_signal"))
        if regime_at_exit == "RISK_OFF" and regime_entry in {"RISK_ON", "NEUTRAL"}:
            return "REGIME_MISMATCH"
        # Stop too narrow relative to normal daily moves → effective overleveraging
        stop = _safe_float(row.get("stop_price"))
        if entry is not None and stop is not None and entry > 0:
            stop_dist_pct = (entry - stop) / entry * 100
            if stop_dist_pct < 2.5 and (mfe is None or mfe < 0.5):
                return "POSITION_SIZE"
        if mfe is not None and mfe > 1.5:
            return "STOP_TOO_TIGHT"
        if mae is not None and abs(mae) > 3.0:
            return "OVEREXTENDED_ENTRY"
        return "FALSE_SIGNAL"
    if mae is not None and mfe is not None and mfe > 0 and abs(mae) / (mfe + 1e-6) > 1.2:
        return "VOLATILITY_SPIKE"
    return "FALSE_SIGNAL" if (net or 0.0) < 0 else "NONE"


def _signal_confidence(row: dict[str, Any]) -> str:
    score = _safe_float(row.get("final_rank_score")) or 0.0
    ev = _safe_float(row.get("expected_value")) or 0.0
    if score >= 75 and ev >= 3:
        return "HIGH"
    if score >= 68 and ev >= 1:
        return "MED"
    return "LOW"


def _review_text(
    row: dict[str, Any],
    outcome: str,
    failure: str,
    net: float | None,
    mfe: float | None,
    mae: float | None,
    regime_at_exit: str = "",
) -> str:
    name = _text(row.get("name")) or _text(row.get("symbol"))
    pnl = f"{net:+.2f}%" if net is not None else "미확정"
    mfe_text = f"{mfe:+.2f}%" if mfe is not None else "n/a"
    mae_text = f"{mae:+.2f}%" if mae is not None else "n/a"
    regime_entry = _upper(row.get("market_regime_at_signal")) or ""
    signal_conf = _signal_confidence(row)

    _regime_kr = {"RISK_ON": "상승 레짐", "RISK_OFF": "하락 레짐", "NEUTRAL": "중립 레짐"}
    _conf_kr = {"HIGH": "높은 신호 신뢰도", "MED": "중간 신호 신뢰도", "LOW": "낮은 신호 신뢰도"}

    ctx_signal = _conf_kr.get(signal_conf, "신호")
    if regime_entry:
        ctx_signal += f" ({_regime_kr.get(regime_entry, regime_entry)} 환경)"

    _outcome_kr = {
        "TARGET_HIT": "목표가에 도달하며 성공 종료됐습니다",
        "STOP_HIT": "목표가 도달 전 손절가를 터치했습니다",
        "TIME_EXIT_NEAR_TARGET": "목표가에 근접했으나 평가 기간 만료로 종료됐습니다",
        "TIME_EXIT_NEAR_STOP": "손절 구간에 근접한 채 평가 기간이 만료됐습니다",
        "TIME_EXIT_FLAT": "방향성 없이 평가 기간이 만료됐습니다",
        "TIME_EXIT_MID": "중간 구간에서 평가 기간이 만료됐습니다",
        "CANCELLED_NOT_FILLED": "진입가에 도달하지 못해 미체결 취소됐습니다",
    }
    ctx_outcome = _outcome_kr.get(outcome, f"{outcome}로 기록됐습니다")
    ctx_move = f"손익 {pnl}"
    if mfe is not None and mae is not None:
        ctx_move += f" (MFE {mfe_text} / MAE {mae_text})"

    _failure_kr: dict[str, str] = {
        "NONE": "",
        "REGIME_MISMATCH": (
            f"진입 시 {_regime_kr.get(regime_entry, '양호')} 레짐이"
            f" 종료 시 {_regime_kr.get(regime_at_exit, '하락')} 레짐으로 전환됐습니다."
            " 종목 신호보다 시장 환경 리스크를 과소반영한 사례입니다"
        ),
        "ENTRY_TIMING": "진입 타이밍 또는 진입가 설정이 실제 가격 흐름과 맞지 않았습니다",
        "FALSE_SIGNAL": "추천 당시 신호 강도에 비해 이후 가격 흐름이 뒷받침되지 않았습니다",
        "OVEREXTENDED_ENTRY": "진입 시점이 고점 부근이거나 이미 과매수 구간이었습니다",
        "POSITION_SIZE": "손절 폭이 평상시 변동폭 대비 좁아 포지션 크기 대비 리스크가 과했습니다",
        "VOLATILITY_SPIKE": "보유 기간 중 비정상적 변동성 확대로 손절 구간이 빠르게 침범됐습니다",
        "DATA_QUALITY": "데이터 신뢰도가 낮아 신호 품질을 보장하기 어렵습니다",
        "SECTOR_WEAKNESS": "종목 개별 요인보다 섹터 전반의 약세가 결과에 영향을 줬을 수 있습니다",
        "MARKET_GAP": "추천 후 갭 발생으로 예상 진입가와 실제 체결가 사이에 괴리가 생겼습니다",
        "THESIS_VALID_BUT_SLOW": "방향성은 맞았지만 평가 기간 내 목표가 도달 속도가 예상보다 느렸습니다",
        "STOP_TOO_TIGHT": "의미 있는 상승 이후 손절가가 좁아 되돌림에 청산됐습니다",
        "TARGET_TOO_FAR": "목표가 설정이 평가 기간 내 달성 가능한 수준보다 높았습니다",
    }
    ctx_failure = _failure_kr.get(failure or "NONE", f"실패 원인 {failure}")

    parts = [f"추천 당시 {ctx_signal}로 진입 검토됐습니다.", f"{ctx_outcome}, {ctx_move}."]
    if ctx_failure:
        parts.append(f"복기: {ctx_failure}.")
    parts.append(f"[{failure or 'NONE'}] 유형으로 기록합니다.")
    return " ".join(parts)


def _round_pct(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, 4)


def _compute_regime(ohlcv: pd.DataFrame, as_of_ts: pd.Timestamp) -> str:
    sub = ohlcv[ohlcv["_date_ts"] <= as_of_ts].tail(60)
    close = pd.to_numeric(sub["close"], errors="coerce").dropna()
    if len(close) < 20:
        return ""
    ma20 = float(close.tail(20).mean())
    ma60 = float(close.tail(60).mean()) if len(close) >= 60 else float(close.mean())
    ret20 = float(close.iloc[-1] / close.iloc[-21] - 1) if len(close) >= 21 else 0.0
    if ma20 > ma60 and ret20 > 0:
        return "RISK_ON"
    if ma20 < ma60 and ret20 < 0:
        return "RISK_OFF"
    return "NEUTRAL"


def _secondary_tags(outcome: str, failure: str, sector: str, mfe: float | None, mae: float | None) -> str:
    tags: list[str] = []
    if (
        outcome == "STOP_HIT"
        and failure not in {"REGIME_MISMATCH", "VOLATILITY_SPIKE", "OVEREXTENDED_ENTRY"}
        and sector
        and mae is not None
        and -4.0 <= mae <= -0.5
        and (mfe is None or mfe < 1.0)
    ):
        tags.append("SECTOR_WEAKNESS")
    return ",".join(tags)


def failure_patterns(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
) -> dict[str, Any]:
    _ensure()
    rows = _filter_rows(_merge_evaluations(_read_journal_rows()), market, mode, horizon, source_type, journal_session, "all")
    if _session_filter(journal_session) == "ALL":
        rows = [row for row in rows if _is_trade_evaluation_session(row)]
    raw_evaluated = [row for row in rows if _upper(row.get("status")) in {"EVALUATED", "CANCELLED"}]
    evaluated = _dedupe_decision_units(raw_evaluated, within_strategy=True)
    raw_group_counts = Counter(
        "|".join(
            _text(row.get(k))
            for k in ("market", "mode", "horizon", "source_type", "journal_session")
        )
        for row in raw_evaluated
    )
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evaluated:
        key = "|".join(
            _text(row.get(k))
            for k in ("market", "mode", "horizon", "source_type", "journal_session")
        )
        groups[key].append(row)
    items: list[dict[str, Any]] = []
    for key, sub in sorted(groups.items()):
        market_v, mode_v, horizon_v, source_v, session_v = key.split("|")
        counts = Counter(_text(row.get("failure_reason") or "UNKNOWN") for row in sub)
        outcome_counts = Counter(_text(row.get("outcome") or "UNKNOWN") for row in sub)
        returns = [_safe_float(row.get("net_pnl_pct")) for row in sub]
        returns = [v for v in returns if v is not None]
        total = len(sub)
        distinct_signal_dates = len({
            _text(row.get("as_of_date"))[:10]
            for row in sub if _text(row.get("as_of_date"))
        })
        source_weight = _source_weight(source_v)
        effective_total = round(total * source_weight, 3)
        items.append({
            "market": market_v,
            "mode": mode_v,
            "horizon": horizon_v,
            "sourceType": source_v,
            "journalSession": session_v,
            "sampleCount": total,
            "distinctSignalDates": distinct_signal_dates,
            "rawRowCount": raw_group_counts.get(key, total),
            "sampleUnit": "UNIQUE_AS_OF_DATE_MARKET_SYMBOL",
            "sourceWeight": source_weight,
            "effectiveSampleCount": effective_total,
            "avgNetPnlPct": round(sum(returns) / len(returns), 4) if returns else None,
            "failureCounts": dict(counts),
            "outcomeCounts": dict(outcome_counts),
            "topFailures": [
                {"reason": reason, "count": count, "share": round(count / total, 4) if total else 0}
                for reason, count in counts.most_common(5)
                if reason not in {"NONE", ""}
            ],
        })
    return {
        "status": "OK",
        "source": _relative(EVALUATION_CSV),
        "count": len(items),
        "items": items,
    }


def calibration_suggestions(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
) -> dict[str, Any]:
    patterns = failure_patterns(market, mode, horizon, source_type, journal_session)
    suggestions: list[dict[str, Any]] = []
    for item in patterns.get("items", []):
        total = int(item.get("sampleCount") or 0)
        st = _text(item.get("sourceType")).upper()
        min_samples = {"FORWARD_PAPER_TRADE": 30, "MANUAL_REVIEWED": 20, "HISTORICAL_REPLAY": 100}.get(st, 10**9)
        counts = item.get("failureCounts") if isinstance(item.get("failureCounts"), dict) else {}
        if total < min_samples:
            suggestions.append({**_suggestion_base(item), "status": "LOW_SAMPLE", "message": f"Need {min_samples} evaluated samples before calibration suggestions."})
            continue
        _add_suggestion(suggestions, item, counts, total, "REGIME_MISMATCH", 0.20, "Increase regime penalty or require regime confirmation.")
        _add_suggestion(suggestions, item, counts, total, "ENTRY_TIMING", 0.25, "Widen entry window or adjust limit-entry distance.")
        _add_suggestion(suggestions, item, counts, total, "TARGET_TOO_FAR", 0.20, "Reduce target multiplier.")
        _add_suggestion(suggestions, item, counts, total, "STOP_TOO_TIGHT", 0.15, "Widen stop or ATR multiplier.")
        _add_suggestion(suggestions, item, counts, total, "DATA_QUALITY", 0.10, "Exclude low-confidence rows from journal capture.")
    items = _attach_approval_state(suggestions)
    return {"status": "OK", "count": len(items), "items": items}


def _suggestion_base(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "market": item.get("market"),
        "mode": item.get("mode"),
        "horizon": item.get("horizon"),
        "sourceType": item.get("sourceType"),
        "journalSession": item.get("journalSession"),
        "sampleCount": item.get("sampleCount"),
        "distinctSignalDates": item.get("distinctSignalDates"),
    }


def _source_summary_id(item: dict[str, Any]) -> str:
    raw = "|".join(
        _text(item.get(key))
        for key in ("market", "mode", "horizon", "sourceType", "journalSession")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _suggestion_id(item: dict[str, Any]) -> str:
    raw = "|".join(
        _text(item.get(key))
        for key in (
            "market",
            "mode",
            "horizon",
            "sourceType",
            "journalSession",
            "status",
            "reason",
            "sampleCount",
            "distinctSignalDates",
            "count",
            "share",
            "threshold",
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _approval_index() -> dict[str, dict[str, Any]]:
    rows = _read_rows(CALIBRATION_APPROVALS_CSV, CALIBRATION_APPROVAL_COLS)
    rows.sort(key=lambda row: _text(row.get("reviewed_at")))
    return {_text(row.get("suggestion_id")): row for row in rows if _text(row.get("suggestion_id"))}


def _approval_scope_index() -> dict[str, dict[str, Any]]:
    rows = _read_rows(CALIBRATION_APPROVALS_CSV, CALIBRATION_APPROVAL_COLS)
    return _latest_approval_by_scope(rows)


def _approval_scope_key(row: dict[str, Any]) -> str:
    source_summary_id = _text(row.get("source_summary_id") or row.get("sourceSummaryId"))
    reason = _upper(row.get("reason"))
    return f"{source_summary_id}|{reason}" if source_summary_id and reason else ""


def _latest_approval_by_scope(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the latest decision per calibration scope; later rejection revokes approval."""
    ordered = sorted(enumerate(rows), key=lambda pair: (_text(pair[1].get("reviewed_at")), pair[0]))
    latest: dict[str, dict[str, Any]] = {}
    for _, row in ordered:
        key = _approval_scope_key(row)
        if key:
            latest[key] = row
    return latest


def _attach_approval_state(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approvals = _approval_index()
    scope_approvals = _approval_scope_index()
    applications = _application_by_approval()
    out: list[dict[str, Any]] = []
    for item in suggestions:
        work = dict(item)
        work["sourceSummaryId"] = _source_summary_id(work)
        work["suggestionId"] = _suggestion_id(work)
        approval = scope_approvals.get(
            f"{work['sourceSummaryId']}|{_upper(work.get('reason'))}"
        ) or approvals.get(work["suggestionId"])
        work["approvalStatus"] = _text(approval.get("decision")) if approval else "PENDING_REVIEW"
        work["approvalId"] = _text(approval.get("approval_id")) if approval else ""
        work["reviewedAt"] = _text(approval.get("reviewed_at")) if approval else ""
        approval_integrity = _approval_integrity_verdict(approval) if approval else {"eligible": False}
        # A sealed approval from an obsolete policy must not permanently block
        # the current policy from starting a fresh, independently fingerprinted
        # Shadow candidate.
        work["approvalPolicyCurrent"] = bool(approval_integrity.get("eligible"))
        work["approvalPolicyReason"] = approval_integrity.get("reason")
        application = applications.get(work["approvalId"])
        work["applicationStatus"] = _text(application.get("status")) if application else "NOT_APPLIED"
        work["appliedAt"] = _text(application.get("applied_at")) if application else ""
        out.append(work)
    return out


def review_calibration_suggestion(
    suggestion_id: str,
    decision: str = "APPROVED",
    reviewed_by: str = "local_admin",
    reviewer_note: str = "",
    before_params: Any = None,
    after_params: Any = None,
) -> dict[str, Any]:
    _ensure()
    sid = _text(suggestion_id)
    normalized_decision = _upper(decision or "APPROVED")
    if normalized_decision in {"APPROVE", "APPROVED"}:
        normalized_decision = "APPROVED"
    elif normalized_decision in {"REJECT", "REJECTED"}:
        normalized_decision = "REJECTED"
    else:
        return {"status": "ERROR", "error": "INVALID_DECISION"}
    all_suggestions = calibration_suggestions("all", "all", "all", "all", "all").get("items", [])
    match = next((item for item in all_suggestions if _text(item.get("suggestionId")) == sid), None)
    if not match:
        return {"status": "ERROR", "error": "SUGGESTION_NOT_FOUND", "suggestionId": sid}
    evidence = _calibration_evidence(match)
    reviewed_at = _now_iso()
    approval_id = hashlib.sha256(f"{sid}|{normalized_decision}|{reviewed_at}".encode("utf-8")).hexdigest()[:20]
    row = {
        "approval_id": approval_id,
        "suggestion_id": sid,
        "decision": normalized_decision,
        "reviewed_by": _text(reviewed_by or "local_admin"),
        "reviewed_at": reviewed_at,
        "source_summary_id": match.get("sourceSummaryId"),
        "market": match.get("market"),
        "mode": match.get("mode"),
        "horizon": match.get("horizon"),
        "source_type": match.get("sourceType"),
        "journal_session": match.get("journalSession"),
        "reason": match.get("reason"),
        "suggestion_status": match.get("status"),
        "sample_count": match.get("sampleCount"),
        "distinct_signal_dates": match.get("distinctSignalDates"),
        "count": match.get("count"),
        "share": match.get("share"),
        "threshold": match.get("threshold"),
        "message": match.get("message"),
        "before_params_json": _json(before_params or {}),
        "after_params_json": _json(after_params or {}),
        "reviewer_note": _text(reviewer_note),
        "policy_version": AUTO_CALIBRATION_POLICY.get("version"),
        "policy_fingerprint": _calibration_policy_fingerprint(),
        "evidence_fingerprint": evidence["fingerprint"],
    }
    row["record_hash"] = _sealed_row_hash(row, CALIBRATION_APPROVAL_COLS)
    rows = _read_rows(CALIBRATION_APPROVALS_CSV, CALIBRATION_APPROVAL_COLS)
    _write_rows(CALIBRATION_APPROVALS_CSV, rows + [row], CALIBRATION_APPROVAL_COLS)
    return {
        "status": "OK",
        "approval": row,
        "message": "Calibration suggestion reviewed. No strategy parameters were changed automatically.",
        "applied": False,
    }


def _application_index() -> set[str]:
    return {
        _text(row.get("approval_id"))
        for row in _read_rows(CALIBRATION_APPLICATIONS_CSV, CALIBRATION_APPLICATION_COLS)
        if _text(row.get("approval_id")) and _upper(row.get("status")) == "APPLIED"
    }


def _application_by_approval() -> dict[str, dict[str, Any]]:
    rows = _read_rows(CALIBRATION_APPLICATIONS_CSV, CALIBRATION_APPLICATION_COLS)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        aid = _text(row.get("approval_id"))
        if aid and _upper(row.get("status")) == "APPLIED":
            out[aid] = row
    return out


def _calibration_ledger_integrity() -> dict[str, Any]:
    def _audit(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, int]:
        sealed = invalid_hash = policy_mismatch = legacy_unsealed = 0
        for row in rows:
            record_hash = _text(row.get("record_hash"))
            if not record_hash:
                legacy_unsealed += 1
                continue
            if record_hash != _sealed_row_hash(row, columns):
                invalid_hash += 1
                continue
            sealed += 1
            if (
                _text(row.get("policy_version")) != _text(AUTO_CALIBRATION_POLICY.get("version"))
                or _text(row.get("policy_fingerprint")) != _calibration_policy_fingerprint()
            ):
                policy_mismatch += 1
        return {
            "rows": len(rows),
            "validSealedRows": sealed - policy_mismatch,
            "legacyUnsealedRows": legacy_unsealed,
            "invalidRecordHashes": invalid_hash,
            "policyMismatchRows": policy_mismatch,
        }

    approvals = _audit(_read_rows(CALIBRATION_APPROVALS_CSV, CALIBRATION_APPROVAL_COLS), CALIBRATION_APPROVAL_COLS)
    applications = _audit(_read_rows(CALIBRATION_APPLICATIONS_CSV, CALIBRATION_APPLICATION_COLS), CALIBRATION_APPLICATION_COLS)
    try:
        promotion_report = json.loads(CALIBRATION_PROMOTION_JSON.read_text(encoding="utf-8"))
    except Exception:
        promotion_report = {}
    certificates = promotion_report.get("certificates") if isinstance(promotion_report, dict) else []
    if not isinstance(certificates, list):
        certificates = []
    valid_certificates = sum(
        1 for row in certificates
        if isinstance(row, dict)
        and _text(row.get("recordHash")) == _promotion_certificate_hash(row)
        and _text(row.get("version")) == CALIBRATION_PROMOTION_VERSION
        and _text(row.get("calibrationPolicyFingerprint")) == _calibration_policy_fingerprint()
        and _text(row.get("decision")) == CALIBRATION_PROMOTION_DECISION
        and row.get("autoPromotionAllowed") is True
        and row.get("humanApprovalRequired") is False
    )
    return {
        "policyVersion": AUTO_CALIBRATION_POLICY.get("version"),
        "policyFingerprint": _calibration_policy_fingerprint(),
        "approvals": approvals,
        "applications": applications,
        "promotionCertificates": {
            "required": True,
            "rows": len(certificates),
            "validCurrentPolicyRows": valid_certificates,
            "source": _relative(CALIBRATION_PROMOTION_JSON),
        },
        "newApplicationsFailClosed": True,
        "integrityViolations": approvals["invalidRecordHashes"] + applications["invalidRecordHashes"],
    }


def _confidence_from_effective_samples(effective_samples: int) -> float:
    if effective_samples < 30:
        return 0.0
    if effective_samples >= 100:
        return 0.9
    return round(0.3 + (effective_samples - 30) / 70 * 0.6, 3)


def _merge_nested_adjustments(base: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    out = dict(base or {})
    for section, values in delta.items():
        if not isinstance(values, dict):
            continue
        current = dict(out.get(section) or {})
        for key, value in values.items():
            current[key] = round(float(current.get(key) or 0.0) + float(value or 0.0), 4)
        out[section] = current
    return out


def _clamp_nested_adjustments(params: dict[str, Any]) -> dict[str, Any]:
    out = dict(params or {})
    for section, limits in CORRECTION_LIMITS.items():
        values = out.get(section)
        if not isinstance(values, dict):
            continue
        clamped = dict(values)
        for key, bounds in limits.items():
            if key not in clamped:
                continue
            lo, hi = bounds
            value = _safe_float(clamped.get(key))
            if value is None:
                continue
            clamped[key] = round(max(lo, min(hi, value)), 4)
        out[section] = clamped
    return out


def _source_confidence_cap(source_type: str) -> float:
    return float((AUTO_CALIBRATION_POLICY.get("sourceConfidenceCaps") or {}).get(_upper(source_type), 0.50))


def _approved_delta(reason: str, share: float, source_weight: float) -> dict[str, dict[str, float]]:
    strength = max(0.25, min(1.0, share * 2.0)) * max(0.1, min(1.2, source_weight))
    reason = _upper(reason)
    if reason == "REGIME_MISMATCH":
        return {"weightAdjustments": {"riskScore": -0.16 * strength}, "priceAdjustments": {"entryAggressiveness": -0.04 * strength}}
    if reason == "ENTRY_TIMING":
        return {"filterAdjustments": {"maxDistanceToEntryPct": 0.35 * strength}, "priceAdjustments": {"entryAggressiveness": 0.03 * strength}}
    if reason == "TARGET_TOO_FAR":
        return {"priceAdjustments": {"targetMultiplier": -0.04 * strength}}
    if reason == "STOP_TOO_TIGHT":
        return {"priceAdjustments": {"stopAtrMultiplier": 0.08 * strength}}
    if reason == "DATA_QUALITY":
        return {"weightAdjustments": {"qualityScore": -0.18 * strength}}
    if reason in {"FALSE_SIGNAL", "SECTOR_WEAKNESS"}:
        return {"weightAdjustments": {"momentumScore": -0.08 * strength, "qualityScore": -0.06 * strength}}
    if reason == "POSITION_SIZE":
        return {"weightAdjustments": {"riskScore": -0.10 * strength}, "filterAdjustments": {"minRiskRewardRatio": 0.03 * strength}}
    return {}


def _approval_integrity_verdict(approval: dict[str, Any]) -> dict[str, Any]:
    stored_hash = _text(approval.get("record_hash"))
    if not stored_hash:
        return {"eligible": False, "reason": "UNSEALED_APPROVAL"}
    if stored_hash != _sealed_row_hash(approval, CALIBRATION_APPROVAL_COLS):
        return {"eligible": False, "reason": "APPROVAL_RECORD_HASH_MISMATCH"}
    if _text(approval.get("policy_version")) != _text(AUTO_CALIBRATION_POLICY.get("version")):
        return {"eligible": False, "reason": "CALIBRATION_POLICY_VERSION_MISMATCH"}
    if _text(approval.get("policy_fingerprint")) != _calibration_policy_fingerprint():
        return {"eligible": False, "reason": "CALIBRATION_POLICY_FINGERPRINT_MISMATCH"}
    return {"eligible": True, "reason": "SEALED_APPROVAL"}


def _approval_shadow_verdict(approval: dict[str, Any]) -> dict[str, Any]:
    """Validate the immutable approval snapshot used to start/continue Shadow."""
    integrity = _approval_integrity_verdict(approval)
    if not integrity.get("eligible"):
        return integrity
    snapshot = {
        "status": approval.get("suggestion_status"),
        "approvalStatus": "PENDING_REVIEW",
        "applicationStatus": "NOT_APPLIED",
        "sourceType": approval.get("source_type"),
        "sampleCount": approval.get("sample_count"),
        "distinctSignalDates": approval.get("distinct_signal_dates"),
        "share": approval.get("share"),
        "reason": approval.get("reason"),
        "threshold": approval.get("threshold"),
    }
    verdict = _shadow_calibration_verdict(snapshot)
    if not verdict.get("eligible"):
        return verdict
    return {
        **verdict,
        "approvedEvidenceFingerprint": _text(approval.get("evidence_fingerprint")),
        "currentEvidenceFingerprint": None,
        "currentSuggestionId": None,
    }


def _approval_application_verdict(
    approval: dict[str, Any],
    current_suggestions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    integrity = _approval_integrity_verdict(approval)
    if not integrity.get("eligible"):
        return integrity

    suggestion_id = _text(approval.get("suggestion_id"))
    current = current_suggestions.get(suggestion_id)
    if current is None:
        scope_id = _text(approval.get("source_summary_id"))
        reason = _upper(approval.get("reason"))
        current = next((
            item for item in current_suggestions.values()
            if _text(item.get("sourceSummaryId")) == scope_id
            and _upper(item.get("reason")) == reason
        ), None)
    if current is None:
        return {"eligible": False, "reason": "SUGGESTION_NO_LONGER_CURRENT"}
    field_pairs = {
        "source_summary_id": "sourceSummaryId",
        "market": "market",
        "mode": "mode",
        "horizon": "horizon",
        "source_type": "sourceType",
        "journal_session": "journalSession",
        "reason": "reason",
        "threshold": "threshold",
    }
    if any(
        str(approval.get(approval_field) if approval.get(approval_field) is not None else "").strip()
        != str(current.get(current_field) if current.get(current_field) is not None else "").strip()
        for approval_field, current_field in field_pairs.items()
    ):
        return {"eligible": False, "reason": "APPROVAL_EVIDENCE_FIELDS_MISMATCH"}

    approved_samples = int(_safe_float(approval.get("sample_count")) or 0)
    approved_dates = int(_safe_float(approval.get("distinct_signal_dates")) or 0)
    current_samples = int(_safe_float(current.get("sampleCount")) or 0)
    current_dates = int(_safe_float(current.get("distinctSignalDates")) or 0)
    if current_samples < approved_samples or current_dates < approved_dates:
        return {
            "eligible": False,
            "reason": "CURRENT_EVIDENCE_REGRESSED",
            "approvedSamples": approved_samples,
            "currentSamples": current_samples,
            "approvedDistinctSignalDates": approved_dates,
            "currentDistinctSignalDates": current_dates,
        }

    evidence = _calibration_evidence(current)
    candidate = {**current, "approvalStatus": "PENDING_REVIEW", "applicationStatus": "NOT_APPLIED"}
    verdict = _shadow_calibration_verdict(candidate)
    if not verdict.get("eligible"):
        return {
            "eligible": False,
            "reason": verdict.get("reason") or "CURRENT_EVIDENCE_GATE_FAILED",
            "validation": verdict.get("validation"),
        }
    return {
        "eligible": True,
        "reason": "SEALED_CURRENT_EVIDENCE_PASS",
        "suggestion": current,
        "approvedEvidenceFingerprint": _text(approval.get("evidence_fingerprint")),
        "currentEvidenceFingerprint": evidence["fingerprint"],
        "currentSuggestionId": _text(current.get("suggestionId")),
        "validation": verdict.get("validation") or evidence["validation"],
    }


def _correction_candidate_fingerprint(
    approval: dict[str, Any],
    evidence_fingerprint: str,
    before: dict[str, Any],
    after: dict[str, Any],
    delta: dict[str, Any],
) -> str:
    return _hash_payload({
        "approvalId": _text(approval.get("approval_id")),
        "approvalRecordHash": _text(approval.get("record_hash")),
        "evidenceFingerprint": evidence_fingerprint,
        "calibrationPolicyFingerprint": _calibration_policy_fingerprint(),
        "before": before,
        "after": after,
        "delta": delta,
    })


def _build_approved_correction_candidate(
    approval: dict[str, Any],
    markets: dict[str, Any],
) -> dict[str, Any]:
    """Build the exact immutable parameter candidate used by Shadow and apply."""
    try:
        from app.engine import correction_store, self_correction_v2
    except Exception as exc:
        return {"status": "ERROR", "reason": f"CORRECTION_STORE_UNAVAILABLE: {exc}"}
    market = _text(approval.get("market")).lower()
    mode = _text(approval.get("mode")).lower()
    horizon = _text(approval.get("horizon")).lower()
    source_type = _upper(approval.get("source_type"))
    reason = _upper(approval.get("reason"))
    if market not in MARKETS or mode not in MODES or horizon not in HORIZONS:
        return {"status": "ERROR", "reason": "INVALID_SCOPE"}
    raw_sample_count = int(_safe_float(approval.get("sample_count")) or 0)
    source_weight = _source_weight(source_type)
    effective_sample_count = max(30, int(round(raw_sample_count * source_weight)))
    share = float(_safe_float(approval.get("share")) or 0.0)
    delta = _approved_delta(reason, share, source_weight)
    if not delta:
        return {"status": "ERROR", "reason": "NO_PARAMETER_MAPPING"}
    key = f"{market}_{mode}_{horizon}"
    stored_before = dict(markets.get(key) or correction_store.load_correction(market, mode, horizon))
    before = (
        stored_before
        if self_correction_v2.live_correction_active(stored_before)
        else correction_store.neutral_correction(market, mode, horizon)
    )
    after = _clamp_nested_adjustments(_merge_nested_adjustments(before, delta))
    after.update({
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "sampleCount": max(int(before.get("sampleCount") or 0), effective_sample_count),
        "rawJournalSampleCount": raw_sample_count,
        "effectiveJournalSampleCount": effective_sample_count,
        "confidence": min(
            _source_confidence_cap(source_type),
            max(
                float(before.get("confidence") or 0.0),
                _confidence_from_effective_samples(effective_sample_count),
            ),
        ),
        "journalCalibrationApplied": True,
        "journalCalibrationSource": _text(approval.get("approval_id")),
        "journalCalibrationSourceType": source_type,
    })
    top = list(before.get("topFailureReasons") or [])
    if reason and reason not in top:
        top.insert(0, reason)
    after["topFailureReasons"] = top[:8]
    approved_evidence_fingerprint = _text(approval.get("evidence_fingerprint"))
    return {
        "status": "OK",
        "key": key,
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "sourceType": source_type,
        "reason": reason,
        "sourceWeight": source_weight,
        "rawSampleCount": raw_sample_count,
        "effectiveSampleCount": effective_sample_count,
        "distinctSignalDates": int(_safe_float(approval.get("distinct_signal_dates")) or 0),
        "delta": delta,
        "before": before,
        "after": after,
        "approvedEvidenceFingerprint": approved_evidence_fingerprint,
        "candidateFingerprint": _correction_candidate_fingerprint(
            approval,
            approved_evidence_fingerprint,
            before,
            after,
            delta,
        ),
    }


def calibration_shadow_readiness(
    suggestions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expose which suggestions can be reviewed for a Forward-only trial."""
    current = suggestions
    if current is None:
        current = calibration_suggestions("all", "all", "all", "all", "all").get("items", [])
    rows: list[dict[str, Any]] = []
    for item in current:
        if _upper(item.get("status")) != "SUGGESTED":
            continue
        verdict = _shadow_calibration_verdict(item)
        effective = float(verdict.get("effectiveSamples") or 0.0)
        share = float(_safe_float(item.get("share")) or 0.0)
        rows.append({
            "suggestionId": item.get("suggestionId"),
            "sourceSummaryId": item.get("sourceSummaryId"),
            "market": item.get("market"),
            "mode": item.get("mode"),
            "horizon": item.get("horizon"),
            "sourceType": item.get("sourceType"),
            "journalSession": item.get("journalSession"),
            "reason": item.get("reason"),
            "sampleCount": item.get("sampleCount"),
            "distinctSignalDates": item.get("distinctSignalDates"),
            "share": item.get("share"),
            "approvalStatus": item.get("approvalStatus"),
            "applicationStatus": item.get("applicationStatus"),
            "shadowEligible": bool(verdict.get("eligible")),
            "shadowGateReason": verdict.get("reason"),
            "estimatedAffectedSamples": round(effective * share, 3),
            "historicalHoldoutPassed": verdict.get("historicalHoldoutPassed") is True,
            "validation": verdict.get("validation"),
            "minRawSamples": verdict.get("minRawSamples"),
            "minDistinctSignalDates": verdict.get("minDistinctSignalDates"),
            "remainingRawSamples": max(
                0,
                int(verdict.get("minRawSamples") or 0) - int(_safe_float(item.get("sampleCount")) or 0),
            ),
            "remainingDistinctSignalDates": max(
                0,
                int(verdict.get("minDistinctSignalDates") or 0)
                - int(_safe_float(item.get("distinctSignalDates")) or 0),
            ),
            "requiresHumanReview": bool(CALIBRATION_SHADOW_POLICY.get("humanApprovalRequired", True)),
            "autoPromotionAllowed": bool(CALIBRATION_SHADOW_POLICY.get("autoPromotionAllowed", False)),
            "requiresForwardPromotion": True,
        })
    rows.sort(key=lambda row: (
        not bool(row.get("shadowEligible")),
        -float(row.get("estimatedAffectedSamples") or 0.0),
        _text(row.get("market")),
        _text(row.get("mode")),
        _text(row.get("horizon")),
        _text(row.get("reason")),
    ))
    return {
        "status": "SHADOW_ONLY",
        "readyForReview": sum(
            1 for row in rows
            if row.get("shadowEligible") and _upper(row.get("approvalStatus")) == "PENDING_REVIEW"
        ),
        "eligibleSuggestions": sum(1 for row in rows if row.get("shadowEligible")),
        "items": rows,
    }


def calibration_shadow_candidates() -> dict[str, Any]:
    """Return sealed approval-snapshot candidates without mutating live params."""
    try:
        from app.engine import correction_store
        params = correction_store.load_params()
    except Exception as exc:
        return {"status": "ERROR", "reason": f"CORRECTION_STORE_UNAVAILABLE: {exc}", "items": []}
    approval_rows = _read_rows(CALIBRATION_APPROVALS_CSV, CALIBRATION_APPROVAL_COLS)
    approvals = list(_latest_approval_by_scope(approval_rows).values())
    already_applied = _application_index()
    current_items = calibration_suggestions("all", "all", "all", "all", "all").get("items", [])
    readiness = calibration_shadow_readiness(current_items)
    markets = dict(params.get("markets") or {})
    items: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for approval in approvals:
        approval_id = _text(approval.get("approval_id"))
        if _upper(approval.get("decision")) != "APPROVED" or not approval_id:
            continue
        if approval_id in already_applied:
            blocked.append({"approvalId": approval_id, "reason": "ALREADY_APPLIED"})
            continue
        verdict = _approval_shadow_verdict(approval)
        if not verdict.get("eligible"):
            blocked.append({"approvalId": approval_id, "reason": verdict.get("reason")})
            continue
        candidate = _build_approved_correction_candidate(approval, markets)
        if candidate.get("status") != "OK":
            blocked.append({"approvalId": approval_id, "reason": candidate.get("reason")})
            continue
        items.append({
            **candidate,
            "approvalId": approval_id,
            "approvalRecordHash": approval.get("record_hash"),
            "suggestionId": approval.get("suggestion_id"),
            "approvedAt": approval.get("reviewed_at"),
            "currentSuggestionId": verdict.get("currentSuggestionId"),
            "currentEvidenceFingerprint": verdict.get("currentEvidenceFingerprint"),
            "calibrationPolicyVersion": AUTO_CALIBRATION_POLICY.get("version"),
            "calibrationPolicyFingerprint": _calibration_policy_fingerprint(),
        })
    items.sort(key=lambda item: (_text(item.get("approvedAt")), _text(item.get("approvalId"))))
    active_limit = max(1, int(AUTO_CALIBRATION_POLICY.get("maxActiveShadowCandidates") or 1))
    for queued in items[active_limit:]:
        blocked.append({
            "approvalId": queued.get("approvalId"),
            "reason": "ACTIVE_SHADOW_CANDIDATE_LIMIT",
        })
    items = items[:active_limit]
    return {
        "status": "SHADOW_ONLY",
        "policyVersion": AUTO_CALIBRATION_POLICY.get("version"),
        "policyFingerprint": _calibration_policy_fingerprint(),
        "items": items,
        "blocked": blocked,
        "readiness": readiness,
    }


def _promotion_certificate_hash(certificate: dict[str, Any]) -> str:
    return _hash_payload({key: value for key, value in certificate.items() if key != "recordHash"})


def _calibration_promotion_verdict(
    approval: dict[str, Any],
    evidence_fingerprint: str,
    candidate_fingerprint: str,
) -> dict[str, Any]:
    try:
        report = json.loads(CALIBRATION_PROMOTION_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {"passed": False, "reason": "MISSING_PROMOTION_CERTIFICATE"}
    certificates = report.get("certificates") if isinstance(report, dict) else []
    if not isinstance(certificates, list):
        certificates = []
    certificate = next((
        row for row in certificates
        if isinstance(row, dict)
        and _text(row.get("approvalId")) == _text(approval.get("approval_id"))
        and _text(row.get("candidateFingerprint")) == candidate_fingerprint
    ), None)
    if certificate is None:
        return {"passed": False, "reason": "MISSING_PROMOTION_CERTIFICATE"}
    if _text(certificate.get("recordHash")) != _promotion_certificate_hash(certificate):
        return {"passed": False, "reason": "PROMOTION_CERTIFICATE_HASH_MISMATCH"}
    checks = [
        (_text(certificate.get("version")) == CALIBRATION_PROMOTION_VERSION, "PROMOTION_CERTIFICATE_VERSION_MISMATCH"),
        (_text(certificate.get("shadowPolicyVersion")) == _text(CALIBRATION_SHADOW_POLICY.get("version")), "PROMOTION_SHADOW_POLICY_VERSION_MISMATCH"),
        (_text(certificate.get("shadowPolicyFingerprint")) == _calibration_shadow_policy_fingerprint(), "PROMOTION_SHADOW_POLICY_FINGERPRINT_MISMATCH"),
        (_text(certificate.get("calibrationPolicyFingerprint")) == _calibration_policy_fingerprint(), "PROMOTION_POLICY_FINGERPRINT_MISMATCH"),
        (_text(certificate.get("evaluationPolicyVersion")) == _text(EVALUATION_POLICY.get("version")), "PROMOTION_EVALUATION_POLICY_VERSION_MISMATCH"),
        (_text(certificate.get("evaluationPolicyFingerprint")) == _evaluation_policy_fingerprint(), "PROMOTION_EVALUATION_POLICY_FINGERPRINT_MISMATCH"),
        (_text(certificate.get("approvalRecordHash")) == _text(approval.get("record_hash")), "PROMOTION_APPROVAL_HASH_MISMATCH"),
        (_text(certificate.get("evidenceFingerprint")) == evidence_fingerprint, "PROMOTION_EVIDENCE_MISMATCH"),
        (certificate.get("promotionEligible") is True, "PROMOTION_NOT_ELIGIBLE"),
        (_text(certificate.get("decision")) == CALIBRATION_PROMOTION_DECISION, "PROMOTION_DECISION_NOT_READY"),
        (certificate.get("autoPromotionAllowed") is True, "PROMOTION_AUTO_APPLY_NOT_AUTHORIZED"),
        (certificate.get("humanApprovalRequired") is False, "PROMOTION_HUMAN_REVIEW_STILL_REQUIRED"),
        (int(_safe_float(certificate.get("completedSignalDates")) or 0) >= CALIBRATION_PROMOTION_MIN_SIGNAL_DATES, "LOW_PROMOTION_SIGNAL_DATES"),
        (int(_safe_float(certificate.get("evaluatedChallengerTrades")) or 0) >= CALIBRATION_PROMOTION_MIN_TRADES, "LOW_PROMOTION_TRADES"),
        (float(_safe_float(certificate.get("avgAfterCostReturnPct")) or 0.0) > 0, "NON_POSITIVE_PROMOTION_RETURN"),
        (float(_safe_float(certificate.get("profitFactor")) or 0.0) > 1.0, "PROMOTION_PROFIT_FACTOR_NOT_ABOVE_ONE"),
        (
            float(_safe_float(certificate.get("payoffRatio")) or 0.0)
            >= float(CALIBRATION_SHADOW_POLICY.get("minPayoffRatio") or 1.0),
            "PROMOTION_PAYOFF_RATIO_TOO_LOW",
        ),
        (
            _text(certificate.get("residualAlphaPolicyVersion")) == "shadow-residual-alpha-v1.1.2",
            "PROMOTION_RESIDUAL_ALPHA_POLICY_MISMATCH",
        ),
        (bool(_text(certificate.get("residualAlphaModelFingerprint"))), "PROMOTION_RESIDUAL_ALPHA_MODEL_MISSING"),
    ]
    expectancy_ci = certificate.get("afterCostExpectancyBootstrapCi95") if isinstance(certificate.get("afterCostExpectancyBootstrapCi95"), list) else []
    checks.append((
        len(expectancy_ci) >= 2 and float(_safe_float(expectancy_ci[0]) or 0.0) > 0,
        "PROMOTION_AFTER_COST_EXPECTANCY_NOT_PROVEN",
    ))
    uplift_ci = certificate.get("pairedUpliftCi95") if isinstance(certificate.get("pairedUpliftCi95"), list) else []
    checks.append((len(uplift_ci) >= 2 and float(_safe_float(uplift_ci[0]) or 0.0) > 0, "PROMOTION_UPLIFT_NOT_PROVEN"))
    champion_dd = _safe_float(certificate.get("championMaxDrawdownPct"))
    challenger_dd = _safe_float(certificate.get("challengerMaxDrawdownPct"))
    checks.append((
        champion_dd is not None and challenger_dd is not None and challenger_dd <= champion_dd,
        "PROMOTION_DRAWDOWN_WORSE",
    ))
    residual_ci = certificate.get("residualAlphaSelectedCi95") if isinstance(certificate.get("residualAlphaSelectedCi95"), list) else []
    checks.append((
        len(residual_ci) >= 2 and float(_safe_float(residual_ci[0]) or 0.0) > 0,
        "PROMOTION_RESIDUAL_ALPHA_NOT_PROVEN",
    ))
    blockers = [reason for passed, reason in checks if not passed]
    return {
        "passed": not blockers,
        "reason": "PROMOTION_CERTIFICATE_PASS" if not blockers else blockers[0],
        "blockingReasons": blockers,
        "certificate": certificate,
    }


def apply_approved_calibrations(
    applied_by: str = "local_admin",
    approval_ids: list[str] | None = None,
    max_applications: int | None = None,
) -> dict[str, Any]:
    _ensure()
    try:
        from app.engine import correction_store
    except Exception as exc:
        return {"status": "ERROR", "error": f"CORRECTION_STORE_UNAVAILABLE: {exc}"}

    approval_rows = _read_rows(CALIBRATION_APPROVALS_CSV, CALIBRATION_APPROVAL_COLS)
    approvals = list(_latest_approval_by_scope(approval_rows).values())
    already_applied = _application_index()
    params = correction_store.load_params()
    markets = dict(params.get("markets") or {})
    old_version = int(params.get("version") or 0)
    applied_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    requested_ids = {_text(v) for v in (approval_ids or []) if _text(v)}
    policy_limit = max(0, int(AUTO_CALIBRATION_POLICY.get("maxApplicationsPerRun") or 1))
    application_limit = policy_limit if max_applications is None else min(policy_limit, max(0, int(max_applications)))
    current_items = calibration_suggestions("all", "all", "all", "all", "all").get("items", [])
    current_suggestions = {
        _text(item.get("suggestionId")): item
        for item in current_items if _text(item.get("suggestionId"))
    }

    for approval in approvals:
        approval_id = _text(approval.get("approval_id"))
        if _upper(approval.get("decision")) != "APPROVED":
            continue
        if not approval_id:
            continue
        if requested_ids and approval_id not in requested_ids:
            continue
        if application_limit is not None and len(applied_rows) >= application_limit:
            skipped.append({"approvalId": approval_id, "reason": "MAX_APPLICATIONS_REACHED"})
            continue
        if approval_id in already_applied:
            skipped.append({"approvalId": approval_id, "reason": "ALREADY_APPLIED"})
            continue
        evidence_gate = _approval_application_verdict(approval, current_suggestions)
        if not evidence_gate.get("eligible"):
            skipped.append({
                "approvalId": approval_id,
                "reason": evidence_gate.get("reason") or "CURRENT_EVIDENCE_GATE_FAILED",
                "validation": evidence_gate.get("validation"),
            })
            continue
        if _upper(approval.get("suggestion_status")) != "SUGGESTED":
            skipped.append({"approvalId": approval_id, "reason": "NOT_SUGGESTED"})
            continue
        candidate = _build_approved_correction_candidate(approval, markets)
        if candidate.get("status") != "OK":
            skipped.append({"approvalId": approval_id, "reason": candidate.get("reason")})
            continue
        market = _text(candidate.get("market"))
        mode = _text(candidate.get("mode"))
        horizon = _text(candidate.get("horizon"))
        source_type = _text(candidate.get("sourceType"))
        reason = _text(candidate.get("reason"))
        source_weight = float(candidate.get("sourceWeight") or 0.0)
        raw_sample_count = int(candidate.get("rawSampleCount") or 0)
        effective_sample_count = int(candidate.get("effectiveSampleCount") or 0)
        key = _text(candidate.get("key"))
        before = dict(candidate.get("before") or {})
        after = dict(candidate.get("after") or {})
        candidate_fingerprint = _text(candidate.get("candidateFingerprint"))
        promotion_gate = _calibration_promotion_verdict(
            approval,
            _text(evidence_gate.get("approvedEvidenceFingerprint")),
            candidate_fingerprint,
        )
        if not promotion_gate.get("passed"):
            skipped.append({
                "approvalId": approval_id,
                "reason": promotion_gate.get("reason") or "PROMOTION_CERTIFICATE_REQUIRED",
                "blockingReasons": promotion_gate.get("blockingReasons") or [],
                "candidateFingerprint": candidate_fingerprint,
            })
            continue
        promotion_certificate = dict(promotion_gate.get("certificate") or {})
        applied_at = _now_iso()
        after.update({
            "journalCalibrationAppliedBy": _text(applied_by or "local_admin"),
            "appliedAt": applied_at,
            "journalCalibrationPromoted": True,
            "calibrationPolicyVersion": AUTO_CALIBRATION_POLICY.get("version"),
            "calibrationPolicyFingerprint": _calibration_policy_fingerprint(),
            "candidateFingerprint": candidate_fingerprint,
            "promotionCertificateHash": promotion_certificate.get("recordHash"),
            "promotionCertificate": promotion_certificate,
        })
        markets[key] = after
        application_id = hashlib.sha256(f"{approval_id}|{applied_at}".encode("utf-8")).hexdigest()[:20]
        applied_rows.append({
            "application_id": application_id,
            "approval_id": approval_id,
            "suggestion_id": approval.get("suggestion_id"),
            "applied_by": _text(applied_by or "local_admin"),
            "applied_at": applied_at,
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "source_type": source_type,
            "journal_session": approval.get("journal_session"),
            "source_weight": source_weight,
            "raw_sample_count": raw_sample_count,
            "distinct_signal_dates": approval.get("distinct_signal_dates"),
            "effective_sample_count": effective_sample_count,
            "reason": reason,
            "before_params_json": _json(before),
            "after_params_json": _json(after),
            "correction_version": old_version + 1,
            "status": "APPLIED",
            "policy_version": AUTO_CALIBRATION_POLICY.get("version"),
            "policy_fingerprint": _calibration_policy_fingerprint(),
            "evidence_fingerprint": evidence_gate.get("approvedEvidenceFingerprint"),
            "approval_record_hash": approval.get("record_hash"),
            "current_suggestion_id": evidence_gate.get("currentSuggestionId"),
            "current_evidence_fingerprint": evidence_gate.get("currentEvidenceFingerprint"),
            "candidate_fingerprint": candidate_fingerprint,
            "promotion_certificate_hash": (promotion_gate.get("certificate") or {}).get("recordHash"),
        })
        applied_rows[-1]["record_hash"] = _sealed_row_hash(applied_rows[-1], CALIBRATION_APPLICATION_COLS)

    if applied_rows:
        new_params = {
            **params,
            "version": old_version + 1,
            "generatedAt": _now_iso(),
            "source": "virtual_trade_journal_approved_calibrations",
            "markets": markets,
        }
        correction_store.save_params(new_params)
        existing = _read_rows(CALIBRATION_APPLICATIONS_CSV, CALIBRATION_APPLICATION_COLS)
        _write_rows(CALIBRATION_APPLICATIONS_CSV, existing + applied_rows, CALIBRATION_APPLICATION_COLS)

    return {
        "status": "OK",
        "applied": len(applied_rows),
        "skipped": skipped,
        "items": applied_rows,
        "correctionVersion": old_version + 1 if applied_rows else old_version,
        "source": _relative(CALIBRATION_APPLICATIONS_CSV),
    }


def _shadow_calibration_verdict(item: dict[str, Any]) -> dict[str, Any]:
    """Gate an immutable, zero-capital Forward experiment.

    This is intentionally different from the unattended auto-approval gate:
    historical holdout drift or a large proposed effect can require human
    review without preventing a pre-registered Forward test.  Promotion and
    live mutation still require the independent Forward certificate.
    """
    status = _upper(item.get("status"))
    application_status = _upper(item.get("applicationStatus"))
    source_type = _upper(item.get("sourceType"))
    raw_samples = int(_safe_float(item.get("sampleCount")) or 0)
    distinct_dates = int(_safe_float(item.get("distinctSignalDates")) or 0)
    source_weight = _source_weight(source_type)
    effective_samples = raw_samples * source_weight
    share = float(_safe_float(item.get("share")) or 0.0)
    source_mins = AUTO_CALIBRATION_POLICY.get("sourceMinSamples") or {}
    min_raw = int(source_mins.get(source_type, 999999))
    min_effective = float(AUTO_CALIBRATION_POLICY.get("minEffectiveSamples") or 40)
    min_dates = int(AUTO_CALIBRATION_POLICY.get("shadowIncubationMinDistinctSignalDates") or 10)
    allowed_sources = {
        _upper(value)
        for value in (AUTO_CALIBRATION_POLICY.get("shadowIncubationSourceTypes") or [])
        if _upper(value)
    }
    base = {
        "effectiveSamples": round(effective_samples, 3),
        "minRawSamples": min_raw,
        "distinctSignalDates": distinct_dates,
        "minDistinctSignalDates": min_dates,
        "requiresForwardPromotion": True,
    }
    if status != "SUGGESTED":
        return {"eligible": False, "reason": "NOT_SUGGESTED", **base}
    if application_status == "APPLIED":
        return {"eligible": False, "reason": "ALREADY_APPLIED", **base}
    if source_type not in allowed_sources:
        return {"eligible": False, "reason": "SHADOW_SOURCE_NOT_FORWARD", **base}
    if raw_samples < min_raw:
        return {"eligible": False, "reason": "RAW_SAMPLE_GATE", **base}
    if effective_samples < min_effective:
        return {"eligible": False, "reason": "EFFECTIVE_SAMPLE_GATE", **base}
    if distinct_dates < min_dates:
        return {"eligible": False, "reason": "SHADOW_TRAINING_DATE_GATE", **base}
    if not _approved_delta(_upper(item.get("reason")), share, source_weight):
        return {"eligible": False, "reason": "NO_PARAMETER_MAPPING", **base}
    validation = _holdout_validation(item)
    return {
        "eligible": True,
        "reason": "SHADOW_INCUBATION_ELIGIBLE",
        **base,
        "validation": validation,
        "historicalHoldoutPassed": validation.get("status") == "OK",
    }


def _auto_calibration_verdict(item: dict[str, Any]) -> dict[str, Any]:
    status = _upper(item.get("status"))
    approval_status = _upper(item.get("approvalStatus"))
    application_status = _upper(item.get("applicationStatus"))
    source_type = _upper(item.get("sourceType"))
    raw_samples = int(_safe_float(item.get("sampleCount")) or 0)
    source_weight = _source_weight(source_type)
    effective_samples = raw_samples * source_weight
    share = float(_safe_float(item.get("share")) or 0.0)
    source_mins = AUTO_CALIBRATION_POLICY.get("sourceMinSamples") or {}
    min_raw = int(source_mins.get(source_type, 999999))
    min_effective = float(AUTO_CALIBRATION_POLICY.get("minEffectiveSamples") or 40)
    max_share = float(AUTO_CALIBRATION_POLICY.get("maxFailureShareForAutoApply") or 0.45)
    if status != "SUGGESTED":
        return {"eligible": False, "reason": "NOT_SUGGESTED", "effectiveSamples": round(effective_samples, 3), "minRawSamples": min_raw}
    approval_policy_current = item.get("approvalPolicyCurrent")
    if approval_policy_current is None:
        # Direct callers and legacy tests that do not carry the attachment
        # metadata keep the conservative historical behavior.
        approval_policy_current = True
    if approval_status != "PENDING_REVIEW" and bool(approval_policy_current):
        return {"eligible": False, "reason": f"APPROVAL_{approval_status or 'UNKNOWN'}", "effectiveSamples": round(effective_samples, 3), "minRawSamples": min_raw}
    if application_status == "APPLIED" and bool(approval_policy_current):
        return {"eligible": False, "reason": "ALREADY_APPLIED", "effectiveSamples": round(effective_samples, 3), "minRawSamples": min_raw}
    if raw_samples < min_raw:
        return {"eligible": False, "reason": "RAW_SAMPLE_GATE", "effectiveSamples": round(effective_samples, 3), "minRawSamples": min_raw}
    if effective_samples < min_effective:
        return {"eligible": False, "reason": "EFFECTIVE_SAMPLE_GATE", "effectiveSamples": round(effective_samples, 3), "minRawSamples": min_raw}
    if share > max_share:
        return {"eligible": False, "reason": "MANUAL_REVIEW_LARGE_EFFECT", "effectiveSamples": round(effective_samples, 3), "minRawSamples": min_raw}
    if not _approved_delta(_upper(item.get("reason")), share, source_weight):
        return {"eligible": False, "reason": "NO_PARAMETER_MAPPING", "effectiveSamples": round(effective_samples, 3), "minRawSamples": min_raw}
    validation = _holdout_validation(item)
    if validation.get("status") != "OK":
        return {
            "eligible": False,
            "reason": "HOLDOUT_DRIFT" if validation.get("status") == "DRIFT" else "LOW_HOLDOUT",
            "effectiveSamples": round(effective_samples, 3),
            "minRawSamples": min_raw,
            "validation": validation,
        }
    return {
        "eligible": True,
        "reason": "AUTO_ELIGIBLE",
        "effectiveSamples": round(effective_samples, 3),
        "minRawSamples": min_raw,
        "validation": validation,
    }


def _row_event_date(row: dict[str, Any]) -> str:
    return _text(
        row.get("evaluated_at")
        or row.get("exit_date")
        or row.get("fill_date")
        or row.get("as_of_date")
        or row.get("generated_at")
    )[:19]


def _rows_for_suggestion_scope(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _filter_rows(
        _merge_evaluations(_read_journal_rows()),
        _text(item.get("market") or "all").lower(),
        _text(item.get("mode") or "all").lower(),
        _text(item.get("horizon") or "all").lower(),
        _text(item.get("sourceType") or "all"),
        _text(item.get("journalSession") or "all"),
        "all",
    )
    out = [
        row for row in rows
        if _upper(row.get("status")) in {"EVALUATED", "CANCELLED"}
        and _text(row.get("failure_reason") or "NONE")
    ]
    out = _dedupe_decision_units(out)
    out.sort(key=_row_event_date)
    return out


def _holdout_validation(item: dict[str, Any]) -> dict[str, Any]:
    rows = _rows_for_suggestion_scope(item)
    reason = _upper(item.get("reason"))
    threshold = float(_safe_float(item.get("threshold")) or 0.0)
    total = len(rows)
    min_holdout = int(AUTO_CALIBRATION_POLICY.get("minHoldoutSamples") or 10)
    fraction = float(AUTO_CALIBRATION_POLICY.get("holdoutFraction") or 0.25)
    min_distinct_dates = int(AUTO_CALIBRATION_POLICY.get("minDistinctSignalDates") or 30)
    min_holdout_dates = int(AUTO_CALIBRATION_POLICY.get("minHoldoutSignalDates") or 8)

    def _signal_date(row: dict[str, Any]) -> str:
        return _text(row.get("as_of_date"))[:10] or _row_event_date(row)[:10]

    signal_dates = sorted({_signal_date(row) for row in rows if _signal_date(row)})
    holdout_date_count = max(min_holdout_dates, int(math.ceil(len(signal_dates) * fraction))) if signal_dates else min_holdout_dates
    if total < min_holdout * 2 or len(signal_dates) < min_distinct_dates or len(signal_dates) <= holdout_date_count:
        return {
            "status": "LOW_HOLDOUT",
            "passed": False,
            "total": total,
            "holdoutSamples": 0,
            "distinctSignalDates": len(signal_dates),
            "requiredDistinctSignalDates": min_distinct_dates,
            "holdoutSignalDates": 0,
            "requiredHoldoutSignalDates": min_holdout_dates,
            "reason": "NOT_ENOUGH_INDEPENDENT_DATES_FOR_STRICT_HOLDOUT",
        }
    holdout_dates = set(signal_dates[-holdout_date_count:])
    holdout = [row for row in rows if _signal_date(row) in holdout_dates]
    train = [row for row in rows if _signal_date(row) not in holdout_dates]
    if len(holdout) < min_holdout or not train:
        return {
            "status": "LOW_HOLDOUT",
            "passed": False,
            "total": total,
            "trainSamples": len(train),
            "holdoutSamples": len(holdout),
            "distinctSignalDates": len(signal_dates),
            "requiredDistinctSignalDates": min_distinct_dates,
            "holdoutSignalDates": len(holdout_dates),
            "requiredHoldoutSignalDates": min_holdout_dates,
            "reason": "HOLDOUT_BLOCK_HAS_TOO_FEW_SAMPLES",
        }

    def _share(sub: list[dict[str, Any]]) -> float:
        if not sub:
            return 0.0
        return sum(1 for row in sub if _upper(row.get("failure_reason")) == reason) / len(sub)

    def _avg_pnl(sub: list[dict[str, Any]]) -> float | None:
        vals = [_safe_float(row.get("net_pnl_pct")) for row in sub]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    train_share = _share(train)
    holdout_share = _share(holdout)
    required_share = max(0.06, threshold * float(AUTO_CALIBRATION_POLICY.get("holdoutShareFloor") or 0.65))
    passed = holdout_share >= required_share
    return {
        "status": "OK" if passed else "DRIFT",
        "passed": passed,
        "total": total,
        "trainSamples": len(train),
        "holdoutSamples": len(holdout),
        "distinctSignalDates": len(signal_dates),
        "holdoutSignalDates": len(holdout_dates),
        "holdoutUnit": "SIGNAL_DATE_BLOCK",
        "trainReasonShare": round(train_share, 4),
        "holdoutReasonShare": round(holdout_share, 4),
        "requiredHoldoutShare": round(required_share, 4),
        "trainAvgPnlPct": _avg_pnl(train),
        "holdoutAvgPnlPct": _avg_pnl(holdout),
    }


def _calibration_evidence(item: dict[str, Any]) -> dict[str, Any]:
    validation = _holdout_validation(item)
    payload = {
        "policyVersion": AUTO_CALIBRATION_POLICY.get("version"),
        "policyFingerprint": _calibration_policy_fingerprint(),
        "suggestionId": item.get("suggestionId"),
        "sourceSummaryId": item.get("sourceSummaryId"),
        "market": item.get("market"),
        "mode": item.get("mode"),
        "horizon": item.get("horizon"),
        "sourceType": item.get("sourceType"),
        "journalSession": item.get("journalSession"),
        "status": item.get("status"),
        "reason": item.get("reason"),
        "sampleCount": int(_safe_float(item.get("sampleCount")) or 0),
        "distinctSignalDates": int(_safe_float(item.get("distinctSignalDates")) or 0),
        "count": int(_safe_float(item.get("count")) or 0),
        "share": round(float(_safe_float(item.get("share")) or 0.0), 8),
        "threshold": round(float(_safe_float(item.get("threshold")) or 0.0), 8),
        "validation": validation,
    }
    return {
        "fingerprint": _hash_payload(payload),
        "payload": payload,
        "validation": validation,
    }


def _self_learning_quality(market: str = "all") -> dict[str, Any]:
    rows = _filter_rows(
        _merge_evaluations(_read_journal_rows()),
        market,
        "all",
        "all",
        "all",
        "all",
        "all",
    )
    raw_evaluated = [
        row for row in rows
        if _upper(row.get("status")) in {"EVALUATED", "CANCELLED"}
        and _is_trade_evaluation_session(row)
    ]
    evaluated = _dedupe_decision_units(raw_evaluated)
    by_source = Counter(_upper(row.get("source_type") or "UNKNOWN") for row in evaluated)
    effective_samples = sum(_source_weight(row.get("source_type")) for row in evaluated)
    forward = by_source.get("FORWARD_PAPER_TRADE", 0) + by_source.get("MANUAL_REVIEWED", 0)
    historical = by_source.get("HISTORICAL_REPLAY", 0)
    source_count = sum(1 for source, count in by_source.items() if count > 0 and source != "UNKNOWN")
    pnl_values = [_safe_float(row.get("net_pnl_pct")) for row in evaluated]
    pnl_values = [v for v in pnl_values if v is not None]
    avg_pnl = round(sum(pnl_values) / len(pnl_values), 4) if pnl_values else None
    distinct_signal_dates = len({_text(row.get("as_of_date"))[:10] for row in evaluated if _text(row.get("as_of_date"))})
    fingerprinted = sum(
        1 for row in evaluated
        if _text(row.get("strategy_fingerprint")) not in {"", "LEGACY_UNFINGERPRINTED"}
    )
    fingerprint_coverage = fingerprinted / len(evaluated) if evaluated else 0.0
    score = 0
    score += min(35, int(effective_samples / 120 * 35))
    score += min(25, int(forward / 50 * 25))
    score += min(20, int(distinct_signal_dates / 60 * 20))
    score += int(fingerprint_coverage * 10)
    score += 10 if avg_pnl is not None and avg_pnl > 0 else 0
    gates = [
        {"name": "effective_samples", "status": "PASS" if effective_samples >= AUTO_CALIBRATION_POLICY["minEffectiveSamples"] else "LOW_SAMPLE", "value": round(effective_samples, 3), "target": AUTO_CALIBRATION_POLICY["minEffectiveSamples"]},
        {"name": "forward_samples", "status": "PASS" if forward >= 30 else "WATCH", "value": forward, "target": 30},
        {"name": "distinct_signal_dates", "status": "PASS" if distinct_signal_dates >= 60 else "LOW_INDEPENDENCE", "value": distinct_signal_dates, "target": 60},
        {"name": "strategy_fingerprint_coverage", "status": "PASS" if fingerprint_coverage >= 0.95 else "LEGACY_MIXED", "value": round(fingerprint_coverage, 4), "target": 0.95},
        {"name": "positive_after_cost_expectancy", "status": "PASS" if avg_pnl is not None and avg_pnl > 0 else "FAIL", "value": avg_pnl, "target": "> 0"},
    ]
    return {
        "score": min(100, score),
        "grade": "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D",
        "evaluatedSamples": len(evaluated),
        "rawEvaluatedRows": len(raw_evaluated),
        "sampleUnit": "UNIQUE_AS_OF_DATE_MARKET_SYMBOL",
        "distinctSignalDates": distinct_signal_dates,
        "strategyFingerprintCoverage": round(fingerprint_coverage, 4),
        "effectiveSamples": round(effective_samples, 3),
        "forwardSamples": forward,
        "historicalReplaySamples": historical,
        "sourceCounts": dict(by_source),
        "avgNetPnlPct": avg_pnl,
        "gates": gates,
    }


def _read_self_learning_report() -> dict[str, Any]:
    if not SELF_LEARNING_STATUS_JSON.exists():
        return {"runs": []}
    try:
        data = json.loads(SELF_LEARNING_STATUS_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"runs": []}
    except Exception:
        return {"runs": []}


def _persisted_self_learning_status(market: str) -> dict[str, Any]:
    """Read the latest completed learning run without recalculating it for a UI health check."""
    report = _read_self_learning_report()
    latest = report.get("latest") if isinstance(report.get("latest"), dict) else {}
    latest_market = _text(latest.get("market") or "all").lower()
    requested_market = _text(market or "all").lower()
    compatible = requested_market == "all" or latest_market in {"all", requested_market}
    current_policy_fingerprint = _calibration_policy_fingerprint()
    latest_policy_fingerprint = _text(latest.get("policyFingerprint"))
    policy_current = latest_policy_fingerprint == current_policy_fingerprint
    if not latest or not compatible or not policy_current:
        return {
            "status": "STALE",
            "source": "PERSISTED_RUN",
            "reason": (
                "POLICY_MISMATCH"
                if latest and compatible and not policy_current
                else "NO_COMPATIBLE_RUN"
            ),
            "policyFingerprint": current_policy_fingerprint,
            "persistedPolicyFingerprint": latest_policy_fingerprint or None,
            "quality": None,
            "lastSelfLearningRun": latest or None,
            "performanceGate": {"status": "DEFERRED", "message": "Use self-learning status for a fresh performance gate."},
        }
    return {
        "status": _upper(latest.get("status") or "OK"),
        "source": "PERSISTED_RUN",
        "generatedAt": report.get("generatedAt"),
        "policyFingerprint": current_policy_fingerprint,
        "quality": latest.get("quality"),
        "eligibleAutoCount": latest.get("eligibleCount"),
        "lowSampleCount": None,
        "appliedCount": latest.get("applied"),
        "correctionVersion": None,
        "lastSelfLearningRun": latest,
        "performanceGate": {"status": "DEFERRED", "message": "Use self-learning status for a fresh performance gate."},
    }


def _write_self_learning_report(run: dict[str, Any]) -> None:
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        data = _read_self_learning_report()
        runs = data.get("runs") if isinstance(data.get("runs"), list) else []
        runs.insert(0, run)
        payload = {
            "status": "OK",
            "generatedAt": _now_iso(),
            "latest": run,
            "runs": runs[:50],
        }
        SELF_LEARNING_STATUS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def auto_self_calibrate(
    market: str = "all",
    applied_by: str = "auto_self_learning",
    apply: bool = True,
    max_applications: int | None = None,
) -> dict[str, Any]:
    _ensure()
    quality_before = _self_learning_quality(market)
    suggestions = calibration_suggestions(market, "all", "all", "all", "all").get("items", [])
    evaluated: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in suggestions:
        verdict = _auto_calibration_verdict(item)
        work = {
            "suggestionId": item.get("suggestionId"),
            "market": item.get("market"),
            "mode": item.get("mode"),
            "horizon": item.get("horizon"),
            "sourceType": item.get("sourceType"),
            "reason": item.get("reason"),
            "sampleCount": item.get("sampleCount"),
            "share": item.get("share"),
            **verdict,
        }
        evaluated.append(work)
        if verdict.get("eligible"):
            eligible.append(work)
        elif _upper(item.get("status")) == "SUGGESTED":
            blocked.append(work)

    eligible.sort(key=lambda row: (float(row.get("effectiveSamples") or 0) * float(row.get("share") or 0)), reverse=True)
    policy_limit = int(AUTO_CALIBRATION_POLICY.get("maxApplicationsPerRun") or 1)
    limit = policy_limit if max_applications is None else min(policy_limit, max(0, int(max_applications)))
    selected = eligible[:max(0, int(limit))]
    auto_apply_enabled = bool(AUTO_CALIBRATION_POLICY.get("enabled"))
    approvals: list[dict[str, Any]] = []
    if auto_apply_enabled:
        for row in selected:
            reviewed = review_calibration_suggestion(
                str(row.get("suggestionId") or ""),
                decision="APPROVED",
                reviewed_by=applied_by,
                reviewer_note=(
                    "Auto-approved by VTJ self-learning policy. "
                    f"effectiveSamples={row.get('effectiveSamples')}, share={row.get('share')}, "
                    "bounded by correction clamps and source confidence caps."
                ),
            )
            if reviewed.get("status") == "OK":
                approvals.append(reviewed.get("approval") or {})
            else:
                blocked.append({**row, "eligible": False, "reason": reviewed.get("error") or "AUTO_APPROVAL_FAILED"})

    apply_result: dict[str, Any] = {
        "status": "SKIPPED",
        "reason": "AUTO_APPLY_FROZEN" if not auto_apply_enabled else "APPLY_FALSE",
    }
    if auto_apply_enabled and apply:
        # Scan every latest current-policy approval, not just approvals created
        # in this run. A Forward promotion certificate necessarily arrives on
        # a later scheduled run, after the candidate has accumulated its
        # independent evidence. The certificate/lineage gate below remains the
        # sole authority to mutate advisory parameters.
        apply_result = apply_approved_calibrations(
            applied_by=applied_by,
            approval_ids=None,
            max_applications=limit,
        )

    result = {
        "status": "OK" if auto_apply_enabled else "SHADOW_ONLY",
        "generatedAt": _now_iso(),
        "market": market,
        "policy": AUTO_CALIBRATION_POLICY,
        "policyFingerprint": _calibration_policy_fingerprint(),
        "calibrationLedgerIntegrity": _calibration_ledger_integrity(),
        "quality": quality_before,
        "suggestionCount": len(suggestions),
        "eligibleCount": len(eligible),
        "wouldApplyCount": len(selected),
        "selectedCount": len(selected),
        "approvedCount": len(approvals),
        "applied": int(apply_result.get("applied") or 0) if isinstance(apply_result, dict) else 0,
        "applyResult": apply_result,
        "selected": selected,
        "blocked": blocked[:20],
        "evaluated": evaluated[:50],
    }
    _write_self_learning_report(result)
    return result


def self_learning_status(market: str = "all") -> dict[str, Any]:
    _ensure()
    try:
        from app.engine import correction_store
        params = correction_store.load_params()
    except Exception:
        params = {"version": 0, "markets": {}}
    suggestions = calibration_suggestions(market, "all", "all", "all", "all").get("items", [])
    evaluated = [{**item, **_auto_calibration_verdict(item)} for item in suggestions]
    eligible = [item for item in evaluated if item.get("eligible")]
    low_sample = [item for item in suggestions if _upper(item.get("status")) == "LOW_SAMPLE"]
    applications = _read_rows(CALIBRATION_APPLICATIONS_CSV, CALIBRATION_APPLICATION_COLS)
    applications.sort(key=lambda row: _text(row.get("applied_at")), reverse=True)
    approvals = _read_rows(CALIBRATION_APPROVALS_CSV, CALIBRATION_APPROVAL_COLS)
    auto_approvals = [
        row for row in approvals
        if _text(row.get("reviewed_by")) in {AUTO_CALIBRATION_POLICY["reviewer"], "github-actions-vtj-self-learning"}
        or "Auto-approved by VTJ self-learning policy" in _text(row.get("reviewer_note"))
    ]
    quality = _self_learning_quality(market)
    report = _read_self_learning_report()
    performance_gate = calibration_performance_gate(market=market, auto_rollback=False)
    return {
        "status": "OK",
        "generatedAt": _now_iso(),
        "market": market,
        "correctionVersion": int(params.get("version") or 0),
        "policy": AUTO_CALIBRATION_POLICY,
        "policyFingerprint": _calibration_policy_fingerprint(),
        "calibrationLedgerIntegrity": _calibration_ledger_integrity(),
        "quality": quality,
        "sourceWeights": SOURCE_CALIBRATION_WEIGHTS,
        "suggestionCount": len(suggestions),
        "eligibleAutoCount": len(eligible),
        "lowSampleCount": len(low_sample),
        "autoApprovalCount": len(auto_approvals),
        "appliedCount": sum(1 for row in applications if _upper(row.get("status")) == "APPLIED"),
        "lastApplications": applications[:8],
        "lastSelfLearningRun": report.get("latest"),
        "performanceGate": performance_gate,
        "eligible": eligible[:12],
        "blocked": [item for item in evaluated if _upper(item.get("status")) == "SUGGESTED" and not item.get("eligible")][:12],
    }


def _performance_scope_rows(
    application: dict[str, Any],
    merged_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = _filter_rows(
        merged_rows if merged_rows is not None else _merge_evaluations(_read_journal_rows()),
        _text(application.get("market") or "all").lower(),
        _text(application.get("mode") or "all").lower(),
        _text(application.get("horizon") or "all").lower(),
        "all",
        "all",
        "all",
    )
    out = [
        row for row in rows
        if _upper(row.get("status")) in {"EVALUATED", "CANCELLED"}
        and _upper(row.get("source_type")) in {"FORWARD_PAPER_TRADE", "MANUAL_REVIEWED"}
        and _safe_float(row.get("net_pnl_pct")) is not None
    ]
    out = _dedupe_decision_units(out)
    out.sort(key=_row_event_date)
    return out


def _performance_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [_safe_float(row.get("net_pnl_pct")) for row in rows]
    vals = [v for v in vals if v is not None]
    wins = sum(1 for row in rows if (_safe_float(row.get("net_pnl_pct")) or 0.0) > 0 or _upper(row.get("outcome")) == "TARGET_HIT")
    winning_values = [value for value in vals if value > 0]
    losing_values = [value for value in vals if value < 0]
    gross_profit = sum(winning_values)
    gross_loss = abs(sum(losing_values))
    average_win = sum(winning_values) / len(winning_values) if winning_values else None
    average_loss = abs(sum(losing_values) / len(losing_values)) if losing_values else None
    payoff_ratio = average_win / average_loss if average_win is not None and average_loss else None
    return {
        "samples": len(rows),
        "distinctSignalDates": len({_row_event_date(row)[:10] for row in rows if _row_event_date(row)}),
        "winRate": round(wins / len(rows), 4) if rows else None,
        "avgNetPnlPct": round(sum(vals) / len(vals), 4) if vals else None,
        "afterCostExpectancyPct": round(sum(vals) / len(vals), 4) if vals else None,
        "profitFactor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else (999.0 if gross_profit > 0 else None),
        "avgWinPct": round(average_win, 4) if average_win is not None else None,
        "avgLossPct": round(average_loss, 4) if average_loss is not None else None,
        "payoffRatio": round(payoff_ratio, 4) if payoff_ratio is not None else None,
        "maxDrawdownPct": _max_drawdown(vals),
    }


def _performance_objective_breaches(
    metrics: dict[str, Any],
    min_profit_factor: float,
    min_payoff_ratio: float,
) -> list[str]:
    breaches: list[str] = []
    if float(metrics.get("afterCostExpectancyPct") or 0.0) <= 0:
        breaches.append("AFTER_COST_EXPECTANCY_NON_POSITIVE")
    if float(metrics.get("profitFactor") or 0.0) <= min_profit_factor:
        breaches.append("PROFIT_FACTOR_FLOOR_BREACHED")
    if float(metrics.get("payoffRatio") or 0.0) < min_payoff_ratio:
        breaches.append("PAYOFF_RATIO_FLOOR_BREACHED")
    return breaches


def _row_used_live_correction(row: dict[str, Any]) -> bool:
    raw = row.get("raw_recommendation")
    if isinstance(raw, dict):
        return raw.get("correctionApplied") is True
    try:
        raw = json.loads(_text(row.get("raw_recommendation_json")) or "{}")
    except Exception:
        return False
    return isinstance(raw, dict) and raw.get("correctionApplied") is True


def _daily_performance_series(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        event_date = _row_event_date(row)[:10]
        if event_date:
            grouped[event_date].append(row)
    pnl: list[float] = []
    wins: list[float] = []
    for event_date in sorted(grouped):
        day_rows = grouped[event_date]
        day_pnl = [_safe_float(row.get("net_pnl_pct")) for row in day_rows]
        day_pnl = [value for value in day_pnl if value is not None]
        if not day_pnl:
            continue
        pnl.append(sum(day_pnl) / len(day_pnl))
        day_wins = sum(
            1
            for row in day_rows
            if (_safe_float(row.get("net_pnl_pct")) or 0.0) > 0
            or _upper(row.get("outcome")) == "TARGET_HIT"
        )
        wins.append(day_wins / len(day_rows))
    return {"pnl": pnl, "wins": wins}


def _mean_difference_upper_bound(before: list[float], after: list[float], z_score: float) -> float | None:
    if len(before) < 2 or len(after) < 2:
        return None

    def _variance(values: list[float]) -> float:
        average = sum(values) / len(values)
        return sum((value - average) ** 2 for value in values) / (len(values) - 1)

    difference = (sum(after) / len(after)) - (sum(before) / len(before))
    standard_error = math.sqrt((_variance(before) / len(before)) + (_variance(after) / len(after)))
    return difference + z_score * standard_error


def _performance_application_lineage(
    application: dict[str, Any],
    current_params: dict[str, Any],
) -> dict[str, Any]:
    from app.engine import correction_store

    blockers: list[str] = []
    if _text(application.get("record_hash")) != _sealed_row_hash(application, CALIBRATION_APPLICATION_COLS):
        blockers.append("APPLICATION_RECORD_HASH_MISMATCH")
    if not correction_store.params_lineage_verdict(current_params, require_integrity=True)["valid"]:
        blockers.append("CURRENT_CORRECTION_LINEAGE_INVALID")
    current_version = int(_safe_float(current_params.get("version")) or 0)
    application_version = int(_safe_float(application.get("correction_version")) or -1)
    if application_version != current_version:
        blockers.append("APPLICATION_NOT_CURRENT_VERSION")
    key = f"{_text(application.get('market')).lower()}_{_text(application.get('mode')).lower()}_{_text(application.get('horizon')).lower()}"
    correction = (current_params.get("markets") or {}).get(key)
    if not isinstance(correction, dict) or not correction_store.promoted_correction_lineage_valid(correction):
        blockers.append("APPLICATION_CORRECTION_NOT_ACTIVE")
        correction = {}
    if _text(application.get("policy_version")) != _text(correction.get("calibrationPolicyVersion")):
        blockers.append("APPLICATION_POLICY_VERSION_MISMATCH")
    if _text(application.get("policy_fingerprint")) != _text(correction.get("calibrationPolicyFingerprint")):
        blockers.append("APPLICATION_POLICY_FINGERPRINT_MISMATCH")
    if _text(application.get("candidate_fingerprint")) != _text(correction.get("candidateFingerprint")):
        blockers.append("APPLICATION_CANDIDATE_FINGERPRINT_MISMATCH")
    if _text(application.get("promotion_certificate_hash")) != _text(correction.get("promotionCertificateHash")):
        blockers.append("APPLICATION_PROMOTION_CERTIFICATE_MISMATCH")
    return {"valid": not blockers, "blockingReasons": blockers, "key": key}


def _quarantine_degraded_correction(application: dict[str, Any], rollback_result: dict[str, Any]) -> dict[str, Any]:
    from app.engine import correction_store

    params = correction_store.load_params()
    lineage = _performance_application_lineage(application, params)
    if not lineage["valid"]:
        return {"status": "ERROR", "error": "QUARANTINE_LINEAGE_FAILED", **lineage}
    key = lineage["key"]
    markets = dict(params.get("markets") or {})
    correction = dict(markets[key])
    correction.update({
        "journalCalibrationPromoted": False,
        "journalCalibrationQuarantined": True,
        "quarantineReason": "POST_PROMOTION_PERFORMANCE_DEGRADED",
        "quarantineAt": _now_iso(),
        "failedRollback": rollback_result,
    })
    markets[key] = correction
    quarantined = {
        **params,
        "version": int(params.get("version") or 0) + 1,
        "generatedAt": _now_iso(),
        "source": "performance_gate_fail_closed_quarantine",
        "markets": markets,
    }
    correction_store.save_params(quarantined)
    return {"status": "OK", "key": key, "correctionVersion": quarantined["version"]}


def calibration_performance_gate(market: str = "all", auto_rollback: bool = False) -> dict[str, Any]:
    _ensure()
    from app.engine import correction_store

    applications = [
        row for row in _read_rows(CALIBRATION_APPLICATIONS_CSV, CALIBRATION_APPLICATION_COLS)
        if _upper(row.get("status")) == "APPLIED"
        and (_text(market).lower() == "all" or _text(row.get("market")).lower() == _text(market).lower())
    ]
    applications.sort(key=lambda row: _text(row.get("applied_at")), reverse=True)
    if not applications:
        return {"status": "NO_APPLICATIONS", "items": [], "autoRollback": False}

    merged_rows = _merge_evaluations(_read_journal_rows())
    current_params = correction_store.load_params()
    min_samples = int(CALIBRATION_PERFORMANCE_POLICY.get("minPrePostSamples") or 30)
    min_dates = int(CALIBRATION_PERFORMANCE_POLICY.get("minPrePostDistinctSignalDates") or 30)
    pnl_drop = float(CALIBRATION_PERFORMANCE_POLICY.get("rollbackAvgPnlDropPct") or 1.5)
    win_drop = float(CALIBRATION_PERFORMANCE_POLICY.get("rollbackWinRateDrop") or 0.10)
    min_profit_factor = float(CALIBRATION_PERFORMANCE_POLICY.get("rollbackMinProfitFactor") or 1.0)
    min_payoff_ratio = float(CALIBRATION_PERFORMANCE_POLICY.get("rollbackMinPayoffRatio") or 1.0)
    confidence_z = float(CALIBRATION_PERFORMANCE_POLICY.get("rollbackConfidenceZ") or 1.96)
    emergency_min_dates = int(CALIBRATION_PERFORMANCE_POLICY.get("rollbackEmergencyMinDistinctSignalDates") or 10)
    emergency_drawdown = float(CALIBRATION_PERFORMANCE_POLICY.get("rollbackEmergencyDrawdownPct") or 8.0)
    items: list[dict[str, Any]] = []
    rollback_candidates: list[dict[str, Any]] = []
    for app in applications[:12]:
        applied_at = _text(app.get("applied_at"))
        rows = _performance_scope_rows(app, merged_rows=merged_rows)
        application_version = int(_safe_float(app.get("correction_version")) or -1)
        before = [row for row in rows if _row_event_date(row) < applied_at]
        after = [
            row
            for row in rows
            if _row_event_date(row) >= applied_at
            and int(_safe_float(row.get("correction_version_at_signal")) or -1) == application_version
            and _row_used_live_correction(row)
        ]
        before_m = _performance_metrics(before[-max(min_samples, 100):])
        after_m = _performance_metrics(after)
        daily_before = _daily_performance_series(before[-max(min_samples, 100):])
        daily_after = _daily_performance_series(after)
        cluster_adjusted_drawdown = _max_drawdown(daily_after["pnl"])
        pnl_upper = _mean_difference_upper_bound(daily_before["pnl"], daily_after["pnl"], confidence_z)
        win_upper = _mean_difference_upper_bound(daily_before["wins"], daily_after["wins"], confidence_z)
        status = "LOW_SAMPLE"
        reason = f"Need {min_samples} samples and {min_dates} distinct signal dates before and after."
        degraded = False
        confirmed_window = (
            before_m["samples"] >= min_samples
            and after_m["samples"] >= min_samples
            and before_m["distinctSignalDates"] >= min_dates
            and after_m["distinctSignalDates"] >= min_dates
        )
        statistical_drop = confirmed_window and (
            (pnl_upper is not None and pnl_upper <= -pnl_drop)
            or (win_upper is not None and win_upper <= -win_drop)
        )
        objective_breaches = _performance_objective_breaches(after_m, min_profit_factor, min_payoff_ratio)
        objective_floor_breached = confirmed_window and bool(objective_breaches)
        statistically_degraded = statistical_drop or objective_floor_breached
        emergency_degraded = (
            after_m["distinctSignalDates"] >= emergency_min_dates
            and float(cluster_adjusted_drawdown or 0.0) >= emergency_drawdown
        )
        degraded = statistically_degraded or emergency_degraded
        if confirmed_window or emergency_degraded:
            status = "DEGRADED" if degraded else "PASS"
            if statistically_degraded:
                reason = "Post-calibration expectancy, payoff, profit factor, or confidence-adjusted performance breached the rollback policy."
            elif emergency_degraded:
                reason = "Post-calibration drawdown breached the emergency capital guardrail."
            else:
                reason = "Post-calibration performance is within guardrails."
        lineage = _performance_application_lineage(app, current_params)
        rollback_ready = degraded and bool(lineage.get("valid"))
        if degraded and not rollback_ready:
            status = "DEGRADED_BLOCKED"
            reason = "Degradation detected, but immutable application-to-current lineage did not match."
        item = {
            "applicationId": app.get("application_id"),
            "approvalId": app.get("approval_id"),
            "market": app.get("market"),
            "mode": app.get("mode"),
            "horizon": app.get("horizon"),
            "reason": app.get("reason"),
            "appliedAt": applied_at,
            "correctionVersion": app.get("correction_version"),
            "status": status,
            "degraded": degraded,
            "rollbackReady": rollback_ready,
            "message": reason,
            "before": before_m,
            "after": after_m,
            "statistics": {
                "confidenceZ": confidence_z,
                "pnlDifferenceUpperBound": round(pnl_upper, 6) if pnl_upper is not None else None,
                "winRateDifferenceUpperBound": round(win_upper, 6) if win_upper is not None else None,
                "statisticallyDegraded": statistically_degraded,
                "statisticalDrop": statistical_drop,
                "objectiveFloorBreached": objective_floor_breached,
                "objectiveBreaches": objective_breaches if confirmed_window else [],
                "emergencyDegraded": emergency_degraded,
                "clusterAdjustedMaxDrawdownPct": cluster_adjusted_drawdown,
            },
            "lineage": lineage,
        }
        if rollback_ready:
            rollback_candidates.append(item)
        items.append(item)

    rollback_result: dict[str, Any] | None = None
    quarantine_result: dict[str, Any] | None = None
    capital_blocked = False
    if auto_rollback and rollback_candidates:
        latest_version = int(_safe_float(rollback_candidates[0].get("correctionVersion")) or 0)
        rollback_result = rollback_self_learning(version=max(0, latest_version - 1), requested_by="auto_performance_gate")
        capital_blocked = rollback_result.get("status") == "OK"
        if not capital_blocked:
            try:
                application_id = _text(rollback_candidates[0].get("applicationId"))
                application = next(
                    row for row in applications if _text(row.get("application_id")) == application_id
                )
                quarantine_result = _quarantine_degraded_correction(application, rollback_result)
                capital_blocked = quarantine_result.get("status") == "OK"
            except Exception as exc:
                quarantine_result = {"status": "ERROR", "error": "QUARANTINE_FAILED", "detail": str(exc)}

    degraded_blocked = any(item["status"] == "DEGRADED_BLOCKED" for item in items)
    if capital_blocked and rollback_result and rollback_result.get("status") == "OK":
        overall_status = "ROLLED_BACK"
    elif capital_blocked:
        overall_status = "QUARANTINED"
    elif rollback_candidates:
        overall_status = "ROLLBACK_READY"
    elif degraded_blocked:
        overall_status = "DEGRADED_BLOCKED"
    elif all(item["status"] == "LOW_SAMPLE" for item in items):
        overall_status = "LOW_SAMPLE"
    else:
        overall_status = "OK"

    return {
        "status": overall_status,
        "policy": {
            "version": CALIBRATION_PERFORMANCE_POLICY["version"],
            "fingerprint": _hash_payload(CALIBRATION_PERFORMANCE_POLICY)[:20],
            "minPrePostSamples": min_samples,
            "minPrePostDistinctSignalDates": min_dates,
            "rollbackAvgPnlDropPct": pnl_drop,
            "rollbackWinRateDrop": win_drop,
            "rollbackMinProfitFactor": min_profit_factor,
            "rollbackMinPayoffRatio": min_payoff_ratio,
            "rollbackConfidenceZ": confidence_z,
            "rollbackEmergencyMinDistinctSignalDates": emergency_min_dates,
            "rollbackEmergencyDrawdownPct": emergency_drawdown,
        },
        "autoRollbackRequested": bool(auto_rollback),
        "autoRollback": bool(auto_rollback and rollback_candidates),
        "rollbackResult": rollback_result,
        "quarantineResult": quarantine_result,
        "capitalBlocked": capital_blocked,
        "candidateCount": len(rollback_candidates),
        "items": items,
    }


def _latest_text(rows: list[dict[str, Any]], fields: list[str]) -> str | None:
    values = [
        _text(row.get(field))
        for row in rows
        for field in fields
        if _text(row.get(field))
    ]
    return max(values) if values else None


def _duplicate_id_stats(rows: list[dict[str, Any]], key: str = "journal_id") -> dict[str, int]:
    counts = Counter(_text(row.get(key)) for row in rows if _text(row.get(key)))
    duplicate_groups = sum(1 for count in counts.values() if count > 1)
    duplicate_rows = sum(count - 1 for count in counts.values() if count > 1)
    return {"groups": duplicate_groups, "extraRows": duplicate_rows}


def _open_reason(row: dict[str, Any]) -> str:
    return _upper(
        row.get("failureReason")
        or row.get("failure_reason")
        or row.get("diagnosticReason")
        or row.get("unknownDetail")
        or row.get("outcome")
        or row.get("status")
        or "OPEN"
    )


def _journal_integrity(
    raw_journal_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    journal_ids = {_text(row.get("journal_id")) for row in raw_journal_rows if _text(row.get("journal_id"))}
    evaluation_ids = {_text(row.get("journal_id")) for row in evaluation_rows if _text(row.get("journal_id"))}
    return {
        "journalDuplicateIds": _duplicate_id_stats(raw_journal_rows),
        "evaluationDuplicateIds": _duplicate_id_stats(evaluation_rows),
        "missingEvaluationRows": len(journal_ids - evaluation_ids),
        "orphanEvaluationRows": len(evaluation_ids - journal_ids),
        "journalRows": len(raw_journal_rows),
        "evaluationRows": len(evaluation_rows),
    }


def _journal_operational_verdict(
    *,
    raw_journal_rows: list[dict[str, Any]],
    merged_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    warnings: list[str],
    self_status: dict[str, Any],
    perf_gate: dict[str, Any],
) -> dict[str, Any]:
    integrity = _journal_integrity(raw_journal_rows, evaluation_rows)
    status_counts = Counter(_upper(row.get("status") or "OPEN") for row in merged_rows)
    outcome_counts = Counter(_upper(row.get("outcome") or "UNKNOWN") for row in merged_rows)
    source_counts = Counter(_upper(row.get("source_type") or "UNKNOWN") for row in merged_rows)
    session_counts = Counter(_journal_session(row.get("journal_session")) for row in merged_rows)
    mode_horizon_counts = Counter(
        f"{_text(row.get('mode')).lower()}:{_text(row.get('horizon')).lower()}"
        for row in merged_rows
    )
    open_rows = [
        row for row in merged_rows
        if _upper(row.get("status") or "OPEN") not in {"EVALUATED", "CANCELLED"}
    ]
    open_reason_counts = Counter(_open_reason(row) for row in open_rows)
    expected_pending = {
        "OPEN",
        "PENDING",
        "DATA_PENDING",
        "NO_FUTURE_BARS_YET",
        "PENDING_EVALUATION",
        "INSUFFICIENT_HOLDING_PERIOD",
    }
    unexpected_open = [
        row for row in open_rows
        if _open_reason(row) not in expected_pending
        and _upper(row.get("status") or "OPEN") not in expected_pending
    ]
    file_ok = not warnings
    duplicate_ok = (
        integrity["journalDuplicateIds"]["extraRows"] == 0
        and integrity["evaluationDuplicateIds"]["extraRows"] == 0
        and integrity["orphanEvaluationRows"] == 0
    )
    recording_ok = file_ok and len(raw_journal_rows) > 0 and duplicate_ok
    evaluation_ok = (
        len(evaluation_rows) > 0
        and integrity["missingEvaluationRows"] == 0
        and not unexpected_open
    )
    perf_status = _upper(perf_gate.get("status") or "UNKNOWN")
    self_status_code = _upper(self_status.get("status") or "UNKNOWN")
    caveats: list[str] = []
    next_actions: list[str] = []
    if open_rows:
        caveats.append(
            f"{len(open_rows)} forward rows are still waiting for future bars or holding-period completion."
        )
    if perf_status == "LOW_SAMPLE":
        caveats.append("Performance gate is LOW_SAMPLE until enough before/after calibration samples accumulate.")
        next_actions.append("Keep collecting forward-paper results before trusting auto-calibration impact checks.")
    if status_counts.get("DATA_PENDING", 0):
        caveats.append("Some rows are DATA_PENDING because required future OHLCV is not available yet.")
    if warnings:
        next_actions.append("Restore required journal/evaluation files before using self-learning decisions.")
    if unexpected_open:
        next_actions.append("Review unexpected open rows before applying new calibration.")
    if perf_status == "ROLLBACK_READY":
        next_actions.append("Review rollback candidates before applying or keeping the latest calibration.")
    if not next_actions:
        next_actions.append("No immediate operator action required; continue scheduled capture and evaluation.")

    status = "RUNNING"
    if not recording_ok or perf_status == "ROLLBACK_READY":
        status = "ATTENTION"
    if warnings or not len(raw_journal_rows):
        status = "ERROR"

    return {
        "status": status,
        "recordingStatus": "OK" if recording_ok else "CHECK",
        "evaluationStatus": "OK" if evaluation_ok else "CHECK",
        "selfLearningStatus": self_status_code,
        "performanceGateStatus": perf_status,
        "summary": (
            "Journal capture and evaluation are operating normally; open rows are expected pending evaluations."
            if status == "RUNNING"
            else "Journal operation needs review before relying on self-learning decisions."
        ),
        "latestCapturedAt": _latest_text(raw_journal_rows, ["captured_at", "generated_at"]),
        "latestEvaluatedAt": _latest_text(evaluation_rows, ["evaluated_at"]),
        "integrity": integrity,
        "counts": {
            "status": dict(status_counts),
            "outcome": dict(outcome_counts),
            "source": dict(source_counts),
            "session": dict(session_counts),
            "modeHorizon": dict(mode_horizon_counts),
            "openReasons": dict(open_reason_counts),
        },
        "openRows": {
            "total": len(open_rows),
            "expectedPending": len(open_rows) - len(unexpected_open),
            "unexpected": len(unexpected_open),
            "reasonCounts": dict(open_reason_counts),
        },
        "caveats": caveats,
        "nextActions": next_actions,
    }


def ops_dashboard(market: str = "all") -> dict[str, Any]:
    _ensure()

    def _file_status(path: Path, required: bool = False) -> dict[str, Any]:
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        age_hours = None
        if exists:
            age_hours = round(max(0.0, (time.time() - path.stat().st_mtime) / 3600), 2)
        state = "OK" if exists and size > 0 else ("MISSING_REQUIRED" if required else "MISSING")
        return {"name": path.stem, "path": _relative(path), "exists": exists, "size": size, "ageHours": age_hours, "state": state}

    raw_journal_rows = _read_journal_rows()
    evaluation_rows = _read_rows(EVALUATION_CSV, EVALUATION_COLS)
    journal_rows = _merge_evaluations(raw_journal_rows)
    if _text(market).lower() != "all":
        raw_journal_rows = [row for row in raw_journal_rows if _text(row.get("market")).lower() == _text(market).lower()]
        journal_ids = {_text(row.get("journal_id")) for row in raw_journal_rows if _text(row.get("journal_id"))}
        evaluation_rows = [row for row in evaluation_rows if _text(row.get("journal_id")) in journal_ids]
        journal_rows = [row for row in journal_rows if _text(row.get("market")).lower() == _text(market).lower()]
    evaluated = [row for row in journal_rows if _upper(row.get("status")) in {"EVALUATED", "CANCELLED"}]
    source_counts = Counter(_upper(row.get("source_type") or "UNKNOWN") for row in journal_rows)
    files = [
        _file_status(JOURNAL_CSV, required=True),
        _file_status(EVALUATION_CSV, required=True),
        _file_status(CALIBRATION_APPROVALS_CSV),
        _file_status(CALIBRATION_APPLICATIONS_CSV),
        _file_status(SELF_LEARNING_STATUS_JSON),
        _file_status(DATA_DIR / "attribution_feedback.json"),
        _file_status(REPORTS_DIR / "factor_attribution.json"),
        _file_status(REPORTS_DIR / "kelly_position_sizes.json"),
        _file_status(REPORTS_DIR / "factor_based_filter_adjustments.json"),
    ]
    warnings = [f"{f['path']}:{f['state']}" for f in files if f["state"].startswith("MISSING_REQUIRED")]
    # The complete learning analysis has its own endpoint.  The dashboard uses
    # the last completed snapshot so opening the page never starts it again.
    self_status = _persisted_self_learning_status(market)
    perf_gate = self_status.get("performanceGate") or {"status": "DEFERRED"}
    operational = _journal_operational_verdict(
        raw_journal_rows=raw_journal_rows,
        merged_rows=journal_rows,
        evaluation_rows=evaluation_rows,
        warnings=warnings,
        self_status=self_status,
        perf_gate=perf_gate,
    )
    return {
        "status": "OK" if not warnings else "WARN",
        "generatedAt": _now_iso(),
        "market": market,
        "files": files,
        "warnings": warnings,
        "operational": operational,
        "journal": {
            "total": len(journal_rows),
            "totalRows": len(journal_rows),
            "evaluated": len(evaluated),
            "evaluatedRows": len(evaluated),
            "open": len(journal_rows) - len(evaluated),
            "openRows": len(journal_rows) - len(evaluated),
            "sourceCounts": dict(source_counts),
            "statusCounts": operational.get("counts", {}).get("status", {}),
            "openReasonCounts": operational.get("openRows", {}).get("reasonCounts", {}),
            "integrity": operational.get("integrity", {}),
            "latestCapturedAt": operational.get("latestCapturedAt"),
            "latestEvaluatedAt": operational.get("latestEvaluatedAt"),
        },
        "selfLearning": {
            "status": self_status.get("status"),
            "source": self_status.get("source"),
            "generatedAt": self_status.get("generatedAt"),
            "quality": self_status.get("quality"),
            "eligibleAutoCount": self_status.get("eligibleAutoCount"),
            "lowSampleCount": self_status.get("lowSampleCount"),
            "appliedCount": self_status.get("appliedCount"),
            "correctionVersion": self_status.get("correctionVersion"),
            "lastRunAt": (self_status.get("lastSelfLearningRun") or {}).get("generatedAt"),
        },
        "performanceGate": perf_gate,
    }


def rollback_self_learning(version: int | None = None, requested_by: str = "local_admin") -> dict[str, Any]:
    try:
        from app.engine import correction_store
    except Exception as exc:
        return {"status": "ERROR", "error": f"CORRECTION_STORE_UNAVAILABLE: {exc}"}
    current = correction_store.load_params()
    current_version = int(current.get("version") or 0)
    reports_dir = correction_store._reports_dir()
    if version is None:
        target_version = current_version - 1
    else:
        target_version = int(version)
    if target_version < 0:
        return {"status": "ERROR", "error": "NO_PREVIOUS_VERSION", "currentVersion": current_version}
    backup = reports_dir / f"self_correction_params_v{target_version}.json"
    if not backup.exists():
        return {"status": "ERROR", "error": "TARGET_VERSION_NOT_FOUND", "targetVersion": target_version, "currentVersion": current_version}
    try:
        restored = json.loads(backup.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "ERROR", "error": f"RESTORE_READ_FAILED: {exc}"}
    try:
        restored_version = int(restored.get("version"))
    except (AttributeError, TypeError, ValueError):
        restored_version = -1
    restore_verdict = correction_store.params_lineage_verdict(restored, require_integrity=True)
    if restored_version != target_version:
        restore_verdict["blockingReasons"] = [
            "ROLLBACK_VERSION_MISMATCH",
            *(restore_verdict.get("blockingReasons") or []),
        ]
        restore_verdict["valid"] = False
    if not restore_verdict.get("valid"):
        return {
            "status": "ERROR",
            "error": "ROLLBACK_INTEGRITY_FAILED",
            "targetVersion": target_version,
            "currentVersion": current_version,
            "blockingReasons": restore_verdict.get("blockingReasons") or [],
        }
    restored["rollbackFromVersion"] = current_version
    restored["rollbackToVersion"] = target_version
    restored["rollbackRequestedBy"] = _text(requested_by or "local_admin")
    restored["rollbackAt"] = _now_iso()
    try:
        correction_store.save_params(restored, backup_current=False)
    except Exception as exc:
        return {
            "status": "ERROR",
            "error": "ROLLBACK_WRITE_FAILED",
            "targetVersion": target_version,
            "currentVersion": current_version,
            "detail": str(exc),
        }
    run = {
        "status": "ROLLBACK",
        "generatedAt": _now_iso(),
        "requestedBy": _text(requested_by or "local_admin"),
        "fromVersion": current_version,
        "toVersion": target_version,
    }
    _write_self_learning_report(run)
    return {
        "status": "OK",
        "fromVersion": current_version,
        "toVersion": target_version,
        "requestedBy": _text(requested_by or "local_admin"),
        "path": "reports/self_correction_params.json",
    }


def upgrade_to_manual_reviewed(
    journal_id: str,
    reviewed_by: str = "local_admin",
    reviewer_note: str = "",
) -> dict[str, Any]:
    _ensure()
    jid = _text(journal_id)
    if not jid:
        return {"status": "ERROR", "error": "MISSING_JOURNAL_ID"}
    rows = _read_journal_rows()
    updated: list[dict[str, Any]] = []
    found: dict[str, Any] | None = None
    for row in rows:
        if _text(row.get("journal_id")) == jid:
            if _upper(row.get("source_type")) != "FORWARD_PAPER_TRADE":
                return {
                    "status": "ERROR",
                    "error": "ONLY_FORWARD_PAPER_TRADE_CAN_BE_UPGRADED",
                    "current_source_type": row.get("source_type"),
                }
            row = dict(row)
            row["source_type"] = "MANUAL_REVIEWED"
            found = row
        updated.append(row)
    if found is None:
        return {"status": "ERROR", "error": "JOURNAL_ID_NOT_FOUND"}
    _write_rows(JOURNAL_CSV, updated, JOURNAL_COLS)
    return {
        "status": "OK",
        "journal_id": jid,
        "source_type": "MANUAL_REVIEWED",
        "reviewed_by": reviewed_by,
        "reviewer_note": reviewer_note,
        "message": "Source type upgraded to MANUAL_REVIEWED. Calibration weight 1.2 applies on next suggestion run.",
    }


def analytics(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
) -> dict[str, Any]:
    _ensure()
    rows = _filter_rows(
        _merge_evaluations(_read_journal_rows()),
        market, mode, horizon, source_type, journal_session, "all",
    )
    if _session_filter(journal_session) == "ALL":
        rows = [row for row in rows if _is_trade_evaluation_session(row)]
    evaluated = [r for r in rows if _upper(r.get("status")) in {"EVALUATED", "CANCELLED"}]

    # 1. Regime transition matrix
    regime_matrix: dict[str, dict[str, Any]] = {}
    for r in evaluated:
        re_entry = _upper(r.get("regime_at_entry") or r.get("market_regime_at_signal") or "UNKNOWN")
        re_exit = _upper(r.get("regime_at_exit") or "UNKNOWN")
        key = f"{re_entry}→{re_exit}"
        if key not in regime_matrix:
            regime_matrix[key] = {"count": 0, "wins": 0, "pnls": []}
        regime_matrix[key]["count"] += 1
        if _text(r.get("outcome")) == "TARGET_HIT":
            regime_matrix[key]["wins"] += 1
        pnl = _safe_float(r.get("net_pnl_pct"))
        if pnl is not None:
            regime_matrix[key]["pnls"].append(pnl)
    regime_transition = [
        {
            "transition": key,
            "count": data["count"],
            "winRate": round(data["wins"] / data["count"], 4) if data["count"] else None,
            "avgPnlPct": round(sum(data["pnls"]) / len(data["pnls"]), 4) if data["pnls"] else None,
        }
        for key, data in sorted(regime_matrix.items(), key=lambda x: -x[1]["count"])
    ]

    # 2. Failure × signal confidence breakdown
    conf_failure: dict[str, dict[str, int]] = {}
    for r in evaluated:
        conf = _upper(r.get("signal_confidence") or "UNKNOWN")
        fail = _text(r.get("failure_reason") or "UNKNOWN")
        if conf not in conf_failure:
            conf_failure[conf] = {}
        conf_failure[conf][fail] = conf_failure[conf].get(fail, 0) + 1
    confidence_breakdown = [
        {"signalConfidence": conf, "failureCounts": counts, "total": sum(counts.values())}
        for conf, counts in sorted(conf_failure.items())
    ]

    # 3. Entry type performance comparison
    entry_perf: dict[str, dict[str, Any]] = {}
    for r in evaluated:
        et = _upper(r.get("entry_type") or "UNKNOWN")
        if et not in entry_perf:
            entry_perf[et] = {"count": 0, "wins": 0, "pnls": [], "cancelled": 0}
        entry_perf[et]["count"] += 1
        outcome_val = _text(r.get("outcome"))
        if outcome_val == "TARGET_HIT":
            entry_perf[et]["wins"] += 1
        if outcome_val == "CANCELLED_NOT_FILLED":
            entry_perf[et]["cancelled"] += 1
        pnl = _safe_float(r.get("net_pnl_pct"))
        if pnl is not None:
            entry_perf[et]["pnls"].append(pnl)
    entry_type_comparison = [
        {
            "entryType": et,
            "count": data["count"],
            "winRate": round(data["wins"] / data["count"], 4) if data["count"] else None,
            "cancelRate": round(data["cancelled"] / data["count"], 4) if data["count"] else None,
            "avgPnlPct": round(sum(data["pnls"]) / len(data["pnls"]), 4) if data["pnls"] else None,
        }
        for et, data in sorted(entry_perf.items())
    ]

    # 4. Source type comparison
    source_perf: dict[str, dict[str, Any]] = {}
    for r in evaluated:
        st = _upper(r.get("source_type") or "UNKNOWN")
        if st not in source_perf:
            source_perf[st] = {"count": 0, "wins": 0, "pnls": [], "failure_counts": Counter()}
        source_perf[st]["count"] += 1
        if _text(r.get("outcome")) == "TARGET_HIT":
            source_perf[st]["wins"] += 1
        pnl = _safe_float(r.get("net_pnl_pct"))
        if pnl is not None:
            source_perf[st]["pnls"].append(pnl)
        source_perf[st]["failure_counts"][_text(r.get("failure_reason") or "UNKNOWN")] += 1
    source_comparison = [
        {
            "sourceType": st,
            "count": data["count"],
            "winRate": round(data["wins"] / data["count"], 4) if data["count"] else None,
            "avgPnlPct": round(sum(data["pnls"]) / len(data["pnls"]), 4) if data["pnls"] else None,
            "topFailures": [
                {"reason": r, "share": round(c / data["count"], 4)}
                for r, c in data["failure_counts"].most_common(5)
                if r not in {"NONE", ""}
            ],
        }
        for st, data in sorted(source_perf.items())
    ]

    return {
        "status": "OK",
        "evaluatedCount": len(evaluated),
        "regimeTransition": regime_transition,
        "confidenceBreakdown": confidence_breakdown,
        "entryTypeComparison": entry_type_comparison,
        "sourceComparison": source_comparison,
    }


def _add_suggestion(
    suggestions: list[dict[str, Any]],
    item: dict[str, Any],
    counts: dict[str, Any],
    total: int,
    reason: str,
    threshold: float,
    message: str,
) -> None:
    count = int(counts.get(reason) or 0)
    share = count / total if total else 0.0
    if share >= threshold:
        suggestions.append({
            **_suggestion_base(item),
            "status": "SUGGESTED",
            "reason": reason,
            "count": count,
            "share": round(share, 4),
            "threshold": threshold,
            "message": message,
            "requiresApproval": True,
        })


def auto_capture_status() -> dict[str, Any]:
    status = _read_auto_status()
    status.setdefault("status", "NOT_RUN")
    status.setdefault("enabled", auto_capture_enabled())
    status.setdefault("timezone", "Asia/Seoul")
    status.setdefault("windows", _auto_capture_windows())
    status.setdefault("file", _relative(AUTO_CAPTURE_STATUS_JSON))
    return status


def auto_capture_enabled() -> bool:
    return runtime_limits.env_bool("MONE_VTJ_AUTO_CAPTURE", True)


def run_auto_capture(
    market: str = "all",
    source_type: str = "FORWARD_PAPER_TRADE",
    journal_session: str = DEFAULT_JOURNAL_SESSION,
    limit: int = 5,
    include_engine: bool = False,
    evaluate_after: bool = True,
    force: bool = False,
    source: str = "manual",
) -> dict[str, Any]:
    mk_list = ["kr", "us"] if str(market).lower() == "all" else [str(market).lower()]
    source_type = _upper(source_type or "FORWARD_PAPER_TRADE")
    journal_session = _journal_session(journal_session)
    now = _kst_now()
    runs: list[dict[str, Any]] = []
    before = _read_auto_status()
    for mk in mk_list:
        if mk not in MARKETS:
            continue
        trade_date = _auto_trade_date(mk, now, journal_session)
        run_key = f"{mk}:{trade_date}:{source_type}:{journal_session}"
        if not force and run_key in set(before.get("completedKeys") or []):
            runs.append({"market": mk, "tradeDate": trade_date, "journalSession": journal_session, "status": "SKIPPED_DUPLICATE", "runKey": run_key})
            continue
        if not _is_trading_day(mk, trade_date):
            runs.append({
                "market": mk,
                "tradeDate": trade_date,
                "journalSession": journal_session,
                "status": "SKIPPED_MARKET_CLOSED",
                "runKey": run_key,
            })
            continue
        market_items: list[dict[str, Any]] = []
        added_total = 0
        selected_total = 0
        rejected_total: Counter[str] = Counter()
        for mode in sorted(MODES):
            for horizon in sorted(HORIZONS):
                result = capture(
                    market=mk,
                    mode=mode,
                    horizon=horizon,
                    source_type=source_type,
                    journal_session=journal_session,
                    limit=limit,
                    as_of_date=trade_date,
                    include_engine=include_engine,
                )
                selected_total += int(result.get("selected") or 0)
                added_total += int(result.get("added") or 0)
                rejected_total.update(result.get("rejected") or {})
                market_items.append({
                    "mode": mode,
                    "horizon": horizon,
                    "selected": result.get("selected", 0),
                    "added": result.get("added", 0),
                    "duplicates": result.get("duplicates", 0),
                    "status": result.get("status", "UNKNOWN"),
                })
        run_status = "OK" if selected_total or added_total else "NO_CANDIDATES"
        runs.append({
            "market": mk,
            "tradeDate": trade_date,
            "journalSession": journal_session,
            "status": run_status,
            "runKey": run_key,
            "selected": selected_total,
            "added": added_total,
            "rejected": dict(rejected_total),
            "items": market_items,
        })
    completed = set(before.get("completedKeys") or [])
    for item in runs:
        if item.get("status") in {"OK", "NO_CANDIDATES", "SKIPPED_MARKET_CLOSED"}:
            completed.add(str(item.get("runKey")))
    should_evaluate = evaluate_after and journal_session not in PLAN_ONLY_SESSIONS
    evaluation = evaluate(market=market, source_type=source_type, journal_session=journal_session, limit=500) if should_evaluate else {"status": "SKIPPED", "reason": "PLAN_ONLY_SESSION" if evaluate_after else "EVALUATE_AFTER_FALSE"}
    status = {
        "status": "OK",
        "enabled": auto_capture_enabled(),
        "source": source,
        "lastRunAt": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Seoul",
        "includeEngine": include_engine,
        "evaluateAfter": evaluate_after,
        "journalSession": journal_session,
        "evaluation": evaluation,
        "completedKeys": sorted(completed)[-120:],
        "runs": runs,
        "windows": _auto_capture_windows(),
        "file": _relative(AUTO_CAPTURE_STATUS_JSON),
    }
    _write_auto_status(status)
    return status


def run_due_auto_capture(source: str = "background_scheduler") -> dict[str, Any]:
    if not auto_capture_enabled():
        return {"status": "DISABLED", "enabled": False}
    now = _kst_now()
    due_markets = _due_markets(now, DEFAULT_JOURNAL_SESSION)
    evaluation = evaluate(limit=500)
    if not due_markets:
        return {
            "status": "NOT_DUE",
            "enabled": True,
            "checkedAt": now.isoformat(timespec="seconds"),
            "evaluation": evaluation,
            "windows": _auto_capture_windows(),
        }
    results: list[dict[str, Any]] = []
    for market in due_markets:
        results.append(run_auto_capture(market=market, journal_session=DEFAULT_JOURNAL_SESSION, include_engine=False, evaluate_after=True, force=False, source=source))
    return {
        "status": "OK",
        "checkedAt": now.isoformat(timespec="seconds"),
        "dueMarkets": due_markets,
        "evaluation": evaluation,
        "results": results,
    }


def start_auto_capture_scheduler(interval_minutes: float | None = None) -> dict[str, Any]:
    global _SCHEDULER_STARTED
    if not auto_capture_enabled():
        return {"status": "DISABLED", "enabled": False}
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return {"status": "ALREADY_STARTED", "enabled": True}
        if interval_minutes is None:
            try:
                interval_minutes = float(os.environ.get("MONE_VTJ_AUTO_CAPTURE_INTERVAL_MIN", "30"))
            except Exception:
                interval_minutes = 30.0
        interval_minutes = max(5.0, min(float(interval_minutes), 180.0))
        thread = threading.Thread(target=_auto_capture_loop, args=(interval_minutes,), daemon=True)
        thread.start()
        _SCHEDULER_STARTED = True
    return {"status": "STARTED", "enabled": True, "intervalMinutes": interval_minutes, "windows": _auto_capture_windows()}


def _auto_capture_loop(interval_minutes: float) -> None:
    time.sleep(10)
    interval = interval_minutes * 60
    while True:
        try:
            result = run_due_auto_capture(source="background_scheduler")
            if result.get("status") == "OK":
                _write_auto_status({**auto_capture_status(), "lastBackgroundCheck": result})
        except Exception as exc:
            status = auto_capture_status()
            status.update({"status": "ERROR", "lastError": str(exc)[:500], "lastErrorAt": _kst_now().isoformat(timespec="seconds")})
            _write_auto_status(status)
        time.sleep(interval)


def _auto_capture_windows() -> dict[str, str]:
    return {
        "krPremarket": "KST 08:20, records PREMARKET_PLAN before KR regular session",
        "krAfterClose": "KST 16:40-23:59, records AFTER_CLOSE_TRADE after KR close data should be available",
        "usPremarket": "KST 21:30, records PREMARKET_PLAN before US regular session",
        "usAfterClose": "KST 07:10-15:00 Tue-Sat, records AFTER_CLOSE_TRADE after US close data should be available",
    }


def _kst_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _due_markets(now: datetime, journal_session: str = DEFAULT_JOURNAL_SESSION) -> list[str]:
    weekday = now.weekday()
    minutes = now.hour * 60 + now.minute
    due: list[str] = []
    session = _journal_session(journal_session)
    if session == "PREMARKET_PLAN":
        if weekday < 5 and (8 * 60 + 10) <= minutes <= (9 * 60 + 20):
            due.append("kr")
        if weekday < 5 and (21 * 60 + 20) <= minutes <= (22 * 60 + 20):
            due.append("us")
    else:
        # KR regular weekdays, after local close. Keep a wide window so a sleeping server can catch up later.
        if weekday < 5 and (16 * 60 + 40) <= minutes <= (23 * 60 + 59):
            due.append("kr")
        # US close is the next Korean morning. Tue-Sat KST covers Mon-Fri US sessions.
        if 1 <= weekday <= 5 and (7 * 60 + 10) <= minutes <= (15 * 60):
            due.append("us")
    status = _read_auto_status()
    completed = set(status.get("completedKeys") or [])
    return [mk for mk in due if f"{mk}:{_auto_trade_date(mk, now, session)}:FORWARD_PAPER_TRADE:{session}" not in completed]


def _auto_trade_date(market: str, now: datetime, journal_session: str = DEFAULT_JOURNAL_SESSION) -> str:
    if market == "us" and _journal_session(journal_session) != "PREMARKET_PLAN":
        d = now.date() - timedelta(days=1)
        while d.weekday() >= 5:  # Saturday=5, Sunday=6 → walk back to Friday
            d -= timedelta(days=1)
        return d.isoformat()
    return now.date().isoformat()


def _is_trading_day(market: str, trade_date: str) -> bool:
    try:
        d = date.fromisoformat(str(trade_date)[:10])
    except Exception:
        return False
    if d.weekday() >= 5:
        return False
    if market == "us" and d.isoformat() in US_MARKET_HOLIDAYS_2026:
        return False
    return True


def _read_auto_status() -> dict[str, Any]:
    try:
        if AUTO_CAPTURE_STATUS_JSON.exists():
            return json.loads(AUTO_CAPTURE_STATUS_JSON.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_auto_status(status: dict[str, Any]) -> None:
    try:
        AUTO_CAPTURE_STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
        AUTO_CAPTURE_STATUS_JSON.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _sharpe(pnls: list[float]) -> float | None:
    if len(pnls) < 3:
        return None
    mean = sum(pnls) / len(pnls)
    variance = sum((x - mean) ** 2 for x in pnls) / len(pnls)
    std = variance ** 0.5
    return round(mean / std, 3) if std > 0 else None


def _max_drawdown(pnls: list[float]) -> float | None:
    if not pnls:
        return None
    peak = 0.0
    max_dd = 0.0
    running = 0.0
    for p in pnls:
        running += p
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 4)


def performance_by_strategy(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
) -> dict[str, Any]:
    """전략별 성과 분석 — win rate, avg PnL, Sharpe, max drawdown, equity curve."""
    _ensure()
    rows = _filter_rows(
        _merge_evaluations(_read_journal_rows()),
        market, mode, horizon, "all", "all",
    )
    all_evaluated = sorted(
        [r for r in rows if _upper(r.get("status")) in {"EVALUATED", "CANCELLED"}],
        key=lambda r: str(r.get("as_of_date") or r.get("trade_date") or ""),
    )
    eligible_sources = {"FORWARD_PAPER_TRADE", "MANUAL_REVIEWED"}
    evaluated = [
        row for row in all_evaluated
        if _upper(row.get("source_type")) in eligible_sources
        and _safe_float(row.get("net_pnl_pct")) is not None
    ]
    research_rows = [
        row for row in all_evaluated
        if _upper(row.get("source_type")) not in eligible_sources
        or _safe_float(row.get("net_pnl_pct")) is None
    ]

    # ── 1. 전략 콤보별 집계 (mode × horizon) ─────────────────────────────
    combo_data: dict[str, dict[str, Any]] = {}
    for r in evaluated:
        mk = _text(r.get("market") or "all")
        md = _text(r.get("mode") or "all")
        hz = _text(r.get("horizon") or "all")
        for key in (f"{mk}_{md}_{hz}", f"all_{md}_{hz}", f"{mk}_all_{hz}", f"{mk}_{md}_all", "all_all_all"):
            if key not in combo_data:
                combo_data[key] = {"count": 0, "wins": 0, "pnls": [], "dates": []}
        for key in (f"{mk}_{md}_{hz}", f"all_{md}_{hz}", f"{mk}_all_{hz}", f"{mk}_{md}_all", "all_all_all"):
            combo_data[key]["count"] += 1
            pnl = _safe_float(r.get("net_pnl_pct"))
            if (pnl is not None and pnl > 0) or _text(r.get("outcome")) == "TARGET_HIT":
                combo_data[key]["wins"] += 1
            if pnl is not None:
                combo_data[key]["pnls"].append(pnl)
                combo_data[key]["dates"].append(str(r.get("as_of_date") or ""))

    strategy_rows = []
    for key, d in sorted(combo_data.items()):
        parts = key.split("_", 2)
        mk_part = parts[0] if len(parts) > 0 else "all"
        md_part = parts[1] if len(parts) > 1 else "all"
        hz_part = parts[2] if len(parts) > 2 else "all"
        pnls = d["pnls"]
        count = d["count"]
        wins = d["wins"]
        strategy_rows.append({
            "key": key,
            "market": mk_part,
            "mode": md_part,
            "horizon": hz_part,
            "count": count,
            "wins": wins,
            "winRate": round(wins / count, 4) if count else None,
            "avgPnlPct": round(sum(pnls) / len(pnls), 4) if pnls else None,
            "sharpe": _sharpe(pnls),
            "maxDrawdownPct": _max_drawdown(pnls),
            "totalPnlPct": round(sum(pnls), 4) if pnls else None,
        })

    # ── 2. 시간순 누적 equity curve (전체) ────────────────────────────────
    curve_points: list[dict[str, Any]] = []
    running_pnl = 0.0
    peak_pnl = 0.0
    max_dd = 0.0
    for r in evaluated:
        pnl = _safe_float(r.get("net_pnl_pct"))
        if pnl is None:
            continue
        running_pnl += pnl
        if running_pnl > peak_pnl:
            peak_pnl = running_pnl
        dd = peak_pnl - running_pnl
        if dd > max_dd:
            max_dd = dd
        curve_points.append({
            "date": str(r.get("as_of_date") or ""),
            "cumPnlPct": round(running_pnl, 4),
            "drawdownPct": round(dd, 4),
        })

    # ── 3. 전체 요약 ──────────────────────────────────────────────────────
    all_pnls = [p for r in evaluated for p in ([_safe_float(r.get("net_pnl_pct"))] if _safe_float(r.get("net_pnl_pct")) is not None else [])]
    all_wins = sum(1 for r in evaluated if (_safe_float(r.get("net_pnl_pct")) or 0) > 0 or _text(r.get("outcome")) == "TARGET_HIT")
    total_count = len(evaluated)

    summary = {
        "count": total_count,
        "wins": all_wins,
        "winRate": round(all_wins / total_count, 4) if total_count else None,
        "avgPnlPct": round(sum(all_pnls) / len(all_pnls), 4) if all_pnls else None,
        "totalPnlPct": round(sum(all_pnls), 4) if all_pnls else None,
        "sharpe": _sharpe(all_pnls),
        "maxDrawdownPct": round(max_dd, 4) if evaluated else None,
    }

    return {
        "status": "OK",
        "performanceDataPolicy": {
            "eligibleSources": sorted(eligible_sources),
            "requiresRealizedReturn": True,
            "researchRowsExcluded": len(research_rows),
        },
        "summary": summary,
        "strategyRows": strategy_rows,
        "equityCurve": curve_points,
        "researchOnly": {
            "count": len(research_rows),
            "sourceCounts": dict(Counter(_upper(row.get("source_type") or "UNKNOWN") for row in research_rows)),
        },
    }


# ──────────────────────────────────────────────────────────────────
# 귀속분석 (Attribution Analysis)
# ──────────────────────────────────────────────────────────────────

def _factor_stats(rows: list[dict[str, Any]], factor_key: str) -> list[dict[str, Any]]:
    """주어진 팩터 키로 그룹화하여 PnL 귀속 통계 계산."""
    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        val = _text(r.get(factor_key)) or "UNKNOWN"
        if val not in groups:
            groups[val] = {"pnls": [], "wins": 0, "count": 0}
        pnl = _safe_float(r.get("net_pnl_pct"))
        groups[val]["count"] += 1
        if pnl is not None:
            groups[val]["pnls"].append(pnl)
            if pnl > 0 or _text(r.get("outcome")) == "TARGET_HIT":
                groups[val]["wins"] += 1

    result = []
    total_pnl_sum = sum(p for g in groups.values() for p in g["pnls"])
    for val, d in sorted(groups.items(), key=lambda x: -(sum(x[1]["pnls"]) if x[1]["pnls"] else 0)):
        pnls = d["pnls"]
        n = d["count"]
        n_pnl = len(pnls)
        avg = sum(pnls) / n_pnl if n_pnl else None
        total = sum(pnls) if pnls else None
        variance = sum((p - (avg or 0)) ** 2 for p in pnls) / n_pnl if n_pnl > 1 else None
        std = variance ** 0.5 if variance is not None else None
        ir = round(avg / std, 3) if avg is not None and std and std > 0 else None
        contrib_pct = round(total / total_pnl_sum * 100, 1) if total is not None and total_pnl_sum != 0 else None
        result.append({
            "factor": val,
            "count": n,
            "wins": d["wins"],
            "winRate": round(d["wins"] / n, 4) if n else None,
            "avgPnlPct": round(avg, 4) if avg is not None else None,
            "totalPnlPct": round(total, 4) if total is not None else None,
            "stdPnlPct": round(std, 4) if std is not None else None,
            "ir": ir,
            "contribPct": contrib_pct,
        })
    return result


def _ev_accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """EV > 0 예측 신호의 실제 적중률 및 EV-실수익 상관 분석."""
    ev_pos, ev_neg, ev_zero = [], [], []
    for r in rows:
        ev = _safe_float(r.get("expected_value") or r.get("ev"))
        pnl = _safe_float(r.get("net_pnl_pct"))
        if ev is None or pnl is None:
            continue
        bucket = ev_pos if ev > 0 else (ev_neg if ev < 0 else ev_zero)
        bucket.append(pnl)

    def _grp(pnls: list[float]) -> dict[str, Any]:
        if not pnls:
            return {"n": 0, "winRate": None, "avgPnlPct": None}
        wins = sum(1 for p in pnls if p > 0)
        avg = sum(pnls) / len(pnls)
        return {"n": len(pnls), "winRate": round(wins / len(pnls), 4), "avgPnlPct": round(avg, 4)}

    # EV vs PnL 상관 (rank 없이 선형 근사: cov/var)
    all_ev, all_pnl = [], []
    for r in rows:
        ev = _safe_float(r.get("expected_value") or r.get("ev"))
        pnl = _safe_float(r.get("net_pnl_pct"))
        if ev is not None and pnl is not None:
            all_ev.append(ev)
            all_pnl.append(pnl)

    corr = None
    if len(all_ev) >= 5:
        n = len(all_ev)
        mean_ev = sum(all_ev) / n
        mean_pnl = sum(all_pnl) / n
        cov = sum((e - mean_ev) * (p - mean_pnl) for e, p in zip(all_ev, all_pnl)) / n
        var_ev = sum((e - mean_ev) ** 2 for e in all_ev) / n
        var_pnl = sum((p - mean_pnl) ** 2 for p in all_pnl) / n
        if var_ev > 0 and var_pnl > 0:
            corr = round(cov / (var_ev ** 0.5 * var_pnl ** 0.5), 3)

    # EV 사분위별 실수익 버킷
    ev_quartile_buckets: list[dict[str, Any]] = []
    if len(all_ev) >= 8:
        sorted_by_ev = sorted(zip(all_ev, all_pnl), key=lambda x: x[0])
        q = len(sorted_by_ev) // 4
        labels = ["Q1(저EV)", "Q2", "Q3", "Q4(고EV)"]
        for i, lbl in enumerate(labels):
            chunk = sorted_by_ev[i * q: (i + 1) * q] if i < 3 else sorted_by_ev[3 * q:]
            pnls_c = [p for _, p in chunk]
            ev_avg = sum(e for e, _ in chunk) / len(chunk) if chunk else None
            pnl_avg = sum(pnls_c) / len(pnls_c) if pnls_c else None
            wins_c = sum(1 for p in pnls_c if p > 0)
            ev_quartile_buckets.append({
                "label": lbl,
                "n": len(chunk),
                "avgEv": round(ev_avg, 3) if ev_avg is not None else None,
                "avgPnlPct": round(pnl_avg, 4) if pnl_avg is not None else None,
                "winRate": round(wins_c / len(pnls_c), 4) if pnls_c else None,
            })

    return {
        "evPositive": _grp(ev_pos),
        "evNegative": _grp(ev_neg),
        "correlation": corr,
        "correlationLabel": (
            "EV-수익 양의 상관 (신호 유효)" if corr is not None and corr > 0.1
            else "EV-수익 음의 상관 (신호 역작동)" if corr is not None and corr < -0.1
            else "EV-수익 무상관 (신호 노이즈)" if corr is not None
            else "데이터 부족"
        ),
        "evQuartileBuckets": ev_quartile_buckets,
    }


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    n = len(vector)
    if n == 0 or any(len(row) != n for row in matrix):
        return None
    work = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(work[r][col]))
        if abs(work[pivot][col]) < 1e-9:
            return None
        if pivot != col:
            work[col], work[pivot] = work[pivot], work[col]
        div = work[col][col]
        for j in range(col, n + 1):
            work[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            factor = work[r][col]
            if abs(factor) < 1e-12:
                continue
            for j in range(col, n + 1):
                work[r][j] -= factor * work[col][j]
    return [work[i][n] for i in range(n)]


def _ols_factor_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [r for r in rows if _safe_float(r.get("net_pnl_pct")) is not None]
    if len(usable) < 12:
        return {"status": "LOW_SAMPLE", "sampleCount": len(usable), "minRequired": 12, "r2": None, "coefficients": []}

    numeric_fields = [
        ("final_rank_score", "score"),
        ("expected_value", "ev"),
        ("risk_reward_ratio", "rr"),
        ("probability", "probability"),
        ("risk_score", "risk"),
        ("event_risk_score", "eventRisk"),
    ]
    categorical_fields = [
        ("market_regime_at_signal", "regime"),
        ("market", "market"),
        ("sector", "sector"),
        ("mode", "mode"),
        ("horizon", "horizon"),
        ("entry_type", "entryType"),
        ("source_type", "sourceType"),
    ]

    columns: list[dict[str, Any]] = [{"kind": "intercept", "name": "intercept", "label": "intercept"}]
    numeric_stats: dict[str, tuple[float, float]] = {}
    for field, label in numeric_fields:
        vals = [_safe_float(r.get(field)) for r in usable]
        vals = [v for v in vals if v is not None]
        if len(vals) < 5:
            continue
        mean = sum(vals) / len(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        if std <= 1e-9:
            continue
        numeric_stats[field] = (mean, std)
        columns.append({"kind": "numeric", "field": field, "name": label, "label": label})

    for field, label in categorical_fields:
        counts = Counter(_text(r.get(field)) or "UNKNOWN" for r in usable)
        categories = [cat for cat, count in counts.most_common(5) if count >= 3]
        for cat in categories[1:]:
            columns.append({"kind": "category", "field": field, "category": cat, "name": f"{label}:{cat}", "label": label})

    columns = columns[:18]
    if len(columns) < 2 or len(usable) <= len(columns) + 2:
        return {"status": "LOW_DEGREES_OF_FREEDOM", "sampleCount": len(usable), "featureCount": len(columns) - 1, "r2": None, "coefficients": []}

    y = [_safe_float(r.get("net_pnl_pct")) or 0.0 for r in usable]
    x_rows: list[list[float]] = []
    for r in usable:
        row: list[float] = []
        for col in columns:
            if col["kind"] == "intercept":
                row.append(1.0)
            elif col["kind"] == "numeric":
                mean, std = numeric_stats[col["field"]]
                value = _safe_float(r.get(col["field"]))
                row.append(((value if value is not None else mean) - mean) / std)
            else:
                row.append(1.0 if (_text(r.get(col["field"])) or "UNKNOWN") == col["category"] else 0.0)
        x_rows.append(row)

    p = len(columns)
    xtx = [[0.0 for _ in range(p)] for _ in range(p)]
    xty = [0.0 for _ in range(p)]
    for row, target in zip(x_rows, y):
        for i in range(p):
            xty[i] += row[i] * target
            for j in range(p):
                xtx[i][j] += row[i] * row[j]
    for i in range(1, p):
        xtx[i][i] += 0.15
    beta = _solve_linear_system(xtx, xty)
    if beta is None:
        return {"status": "SINGULAR", "sampleCount": len(usable), "featureCount": p - 1, "r2": None, "coefficients": []}

    preds = [sum(row[i] * beta[i] for i in range(p)) for row in x_rows]
    mean_y = sum(y) / len(y)
    sse = sum((target - pred) ** 2 for target, pred in zip(y, preds))
    sst = sum((target - mean_y) ** 2 for target in y)
    r2 = 1 - sse / sst if sst > 1e-9 else None
    coefficients = []
    for col, coef in zip(columns[1:], beta[1:]):
        coefficients.append({
            "factor": col["name"],
            "group": col["label"],
            "coef": round(coef, 4),
            "direction": "POSITIVE" if coef > 0.02 else ("NEGATIVE" if coef < -0.02 else "NEUTRAL"),
            "absImpact": round(abs(coef), 4),
        })
    coefficients.sort(key=lambda item: item["absImpact"], reverse=True)
    return {
        "status": "OK",
        "sampleCount": len(usable),
        "featureCount": p - 1,
        "r2": round(r2, 4) if r2 is not None else None,
        "coefficients": coefficients[:12],
    }


def attribution_analysis(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
) -> dict[str, Any]:
    """팩터별 PnL 귀속분석.

    팩터: 마켓 레짐, 시장(KR/US), 섹터, 전략모드, 투자기간, 진입유형, 소스유형
    지표: avgPnl, winRate, IR(정보비율), contribPct(전체 대비 기여 %)
    EV 정확도: EV > 0 예측 신호의 실제 적중률 + EV-실수익 상관계수
    """
    _ensure()
    rows = _filter_rows(
        _merge_evaluations(_read_journal_rows()),
        market, mode, horizon, "all", "all",
    )
    evaluated_candidates = [
        r for r in rows
        if _upper(r.get("status")) in {"EVALUATED", "CANCELLED"}
        and _safe_float(r.get("net_pnl_pct")) is not None
    ]
    source_breakdown = _source_breakdown(evaluated_candidates)
    replay_rows = [r for r in evaluated_candidates if not _is_calibration_admissible(r)]
    evaluated_candidates = [r for r in evaluated_candidates if _is_calibration_admissible(r)]
    inconsistent_outcomes = [r for r in evaluated_candidates if not _has_consistent_realized_outcome(r)]
    evaluated = [r for r in evaluated_candidates if _has_consistent_realized_outcome(r)]

    if not evaluated:
        return {
            "status": "OK",
            "count": 0,
            "excludedInconsistentOutcomeCount": len(inconsistent_outcomes),
            "excludedBySourcePolicyCount": len(replay_rows),
            "sourceBreakdown": source_breakdown,
            "byRegime": [],
            "byMarket": [],
            "bySector": [],
            "byMode": [],
            "byHorizon": [],
            "byEntryType": [],
            "bySourceType": [],
            "evAccuracy": {"evPositive": {"n": 0}, "correlation": None, "correlationLabel": "데이터 부족", "evQuartileBuckets": []},
        }

    return {
        "status": "OK",
        "count": len(evaluated),
        "excludedInconsistentOutcomeCount": len(inconsistent_outcomes),
        # 가중치 0인 소스(과거 리플레이)를 뺀 수와, 소스별 실측을 함께 낸다.
        # 빼기만 하고 숨기면 "표본이 왜 줄었나"를 나중에 알 수 없다.
        "excludedBySourcePolicyCount": len(replay_rows),
        "sourceBreakdown": source_breakdown,
        "byRegime": _factor_stats(evaluated, "market_regime_at_signal"),
        "byMarket": _factor_stats(evaluated, "market"),
        "bySector": _factor_stats(evaluated, "sector"),
        "byMode": _factor_stats(evaluated, "mode"),
        "byHorizon": _factor_stats(evaluated, "horizon"),
        "byEntryType": _factor_stats(evaluated, "entry_type"),
        "bySourceType": _factor_stats(evaluated, "source_type"),
        "evAccuracy": _ev_accuracy(evaluated),
        "regression": _ols_factor_attribution(evaluated),
    }


def _horizon_from_hold_days(value: Any) -> str:
    days = _safe_float(value)
    if days is None:
        return "unknown"
    if days <= 3:
        return "short"
    if days <= 10:
        return "swing"
    return "mid"


def _historical_result_kind(value: Any) -> str:
    raw = _text(value).strip().upper()
    if raw in {"TARGET", "TARGET_HIT", "WIN", "목표달성", "성공"}:
        return "WIN"
    if raw in {"STOP", "STOP_HIT", "STOP_FIRST", "LOSS", "손절", "실패"}:
        return "LOSS"
    if raw in {"CLOSE_EXIT", "TIME_EXIT", "HOLDING_EVAL"}:
        return "CLOSE"
    if raw in {"NOT_EXECUTED", "NOT_FILLED", "미체결", "NOT_EXECUTED"} or "NOT_EXECUTED" in raw:
        return "NOT_EXECUTED"
    if raw in {"PENDING", "DATA_PENDING", "검증 대기", "대기", ""}:
        return "PENDING"
    return "OTHER"


def _wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    phat = wins / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _historical_operation_rows(market: str = "all") -> list[dict[str, Any]]:
    if not HISTORY_EVALUATION_CSV.exists():
        return []
    try:
        eval_df = pd.read_csv(HISTORY_EVALUATION_CSV, dtype=str)
    except Exception:
        return []
    if HISTORY_OPERATION_CSV.exists():
        try:
            hist_df = pd.read_csv(
                HISTORY_OPERATION_CSV,
                dtype=str,
                usecols=lambda c: c in {"created_at", "market", "symbol", "mode", "hold_days", "snapshot_kind", "data_status"},
            )
            join_keys = ["created_at", "market", "symbol", "mode"]
            for df in (eval_df, hist_df):
                df["_join_ord"] = df.groupby(join_keys, dropna=False).cumcount()
            eval_df = eval_df.merge(hist_df, on=join_keys + ["_join_ord"], how="left", suffixes=("", "_source"))
        except Exception:
            pass
    if market != "all":
        eval_df = eval_df[eval_df.get("market", "").astype(str).str.lower() == market.lower()]
    rows: list[dict[str, Any]] = []
    for row in eval_df.to_dict("records"):
        mode = _text(row.get("mode")).lower()
        mk = _text(row.get("market")).lower()
        if mk not in MARKETS or mode not in MODES:
            continue
        result_kind = _historical_result_kind(row.get("outcome_result"))
        if result_kind in {"PENDING", "NOT_EXECUTED"}:
            continue
        horizon = _horizon_from_hold_days(row.get("hold_days"))
        if horizon not in HORIZONS:
            continue
        ret = _safe_float(row.get("realized_return_pct"))
        rows.append({
            "source": "HISTORICAL_OPERATION",
            "market": mk,
            "mode": mode,
            "horizon": horizon,
            "symbol": _text(row.get("symbol")),
            "createdAt": _text(row.get("created_at")),
            "resultKind": result_kind,
            "returnPct": ret,
            "dataStatus": _text(row.get("data_status")),
        })
    return rows


def _virtual_validation_result_rows(market: str = "all") -> list[dict[str, Any]]:
    if not VIRTUAL_VALIDATION_RESULTS_CSV.exists():
        return []
    try:
        df = pd.read_csv(VIRTUAL_VALIDATION_RESULTS_CSV, dtype=str)
    except Exception:
        return []
    if market != "all":
        df = df[df.get("market", "").astype(str).str.lower() == market.lower()]
    rows: list[dict[str, Any]] = []
    for row in df.to_dict("records"):
        mk = _text(row.get("market")).lower()
        mode = _text(row.get("mode")).lower()
        horizon = _text(row.get("horizon")).lower()
        if mk not in MARKETS or mode not in MODES or horizon not in HORIZONS:
            continue
        result_kind = _historical_result_kind(row.get("result") or row.get("status"))
        ret = _safe_float(row.get("returnPct"))
        if result_kind in {"PENDING", "NOT_EXECUTED"} and ret is None:
            continue
        rows.append({
            "source": "VIRTUAL_VALIDATION_RESULTS",
            "market": mk,
            "mode": mode,
            "horizon": horizon,
            "symbol": _text(row.get("symbol")),
            "createdAt": _text(row.get("createdAt")),
            "resultKind": result_kind,
            "returnPct": ret,
            "dataStatus": _text(row.get("dataStatus")),
        })
    return rows


def _historical_strategy_rows(rows: list[dict[str, Any]], min_samples: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["market"], row["mode"], row["horizon"])].append(row)
    out: list[dict[str, Any]] = []
    for (market, mode, horizon), sub in sorted(groups.items()):
        # Labels without a realised return are research diagnostics only.  They
        # cannot enter a win-rate denominator or generate a calibration action.
        evaluated = [
            r for r in sub
            if r["returnPct"] is not None and r["resultKind"] not in {"PENDING", "NOT_EXECUTED"}
        ]
        if not evaluated:
            continue
        wins = sum(1 for r in evaluated if (r["returnPct"] or 0) > 0)
        losses = sum(1 for r in evaluated if (r["returnPct"] or 0) < 0)
        returns = [r["returnPct"] for r in evaluated if r["returnPct"] is not None]
        low, high = _wilson_interval(wins, len(evaluated))
        source_counts = Counter(r["source"] for r in evaluated)
        stop_count = sum(1 for r in evaluated if r["resultKind"] == "LOSS")
        target_count = sum(1 for r in evaluated if r["resultKind"] == "WIN")
        out.append({
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "sampleCount": len(evaluated),
            "returnSampleCount": len(returns),
            "wins": wins,
            "losses": losses,
            "targetCount": target_count,
            "stopCount": stop_count,
            "winRate": round(wins / len(evaluated), 4) if evaluated else None,
            "winRateCi95": {
                "low": round(low, 4) if low is not None else None,
                "high": round(high, 4) if high is not None else None,
                "width": round(high - low, 4) if low is not None and high is not None else None,
            },
            "avgReturnPct": round(sum(returns) / len(returns), 4) if returns else None,
            "sourceCounts": dict(source_counts),
            "sampleStatus": "OK" if len(evaluated) >= min_samples else "LOW_SAMPLE",
        })
    return out


def _historical_calibration_suggestions(strategy_rows: list[dict[str, Any]], min_samples: int) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for row in strategy_rows:
        n = int(row.get("sampleCount") or 0)
        if n < min_samples:
            suggestions.append({
                "status": "LOW_SAMPLE",
                "market": row.get("market"),
                "mode": row.get("mode"),
                "horizon": row.get("horizon"),
                "sampleCount": n,
                "message": f"Need at least {min_samples} historical evaluated rows before changing this strategy.",
            })
            continue
        wr = float(row.get("winRate") or 0.0)
        avg = _safe_float(row.get("avgReturnPct"))
        stop_share = (int(row.get("stopCount") or 0) / n) if n else 0.0
        ci = row.get("winRateCi95") if isinstance(row.get("winRateCi95"), dict) else {}
        if stop_share >= 0.35 and (avg is None or avg < -1.5):
            action = "WIDEN_STOP_OR_TIGHTEN_ENTRY"
            message = "Losses cluster around stop outcomes; reduce entry eagerness or widen ATR-based stop only after checking slippage."
        elif avg is not None and avg < 0 and wr < 0.45:
            action = "RAISE_SIGNAL_THRESHOLD"
            message = "Historical win rate and average return are both weak; require stronger confluence or EV before capture."
        elif wr >= 0.55 and avg is not None and avg > 0:
            action = "PROMOTE_WITH_CAP"
            message = "Historical evidence is favorable; promote cautiously with position-size and sample caps."
        else:
            action = "OBSERVE"
            message = "Evidence is mixed; keep collecting and prefer UI warning over parameter change."
        suggestions.append({
            "status": "SUGGESTED" if action != "OBSERVE" else "WATCH",
            "action": action,
            "market": row.get("market"),
            "mode": row.get("mode"),
            "horizon": row.get("horizon"),
            "sampleCount": n,
            "winRate": row.get("winRate"),
            "winRateCi95": ci,
            "avgReturnPct": avg,
            "stopShare": round(stop_share, 4),
            "message": message,
        })
    return suggestions


def historical_strategy_calibration(
    market: str = "all",
    min_samples: int = 30,
    include_chart: bool = True,
    include_pattern: bool = True,
    symbol_limit: int = 12,
    max_cutoffs: int = 6,
) -> dict[str, Any]:
    _ensure()
    normalized_market = _text(market).lower() or "all"
    if normalized_market not in {"all", *MARKETS}:
        return {"status": "ERROR", "error": "INVALID_MARKET"}
    safe_min = max(10, min(int(min_samples or 30), 200))
    safe_symbol_limit = max(2, min(int(symbol_limit or 12), 30))
    safe_max_cutoffs = max(2, min(int(max_cutoffs or 6), 20))

    history_rows = _historical_operation_rows(normalized_market)
    validation_rows = _virtual_validation_result_rows(normalized_market)
    # Historical replay is useful for hypothesis generation, but never merges
    # with forward-paper results for a public performance or calibration gate.
    historical_research_rows = _historical_strategy_rows(history_rows, safe_min)
    strategy_rows = _historical_strategy_rows(validation_rows, safe_min)
    suggestions = _historical_calibration_suggestions(strategy_rows, safe_min)

    chart_summary: dict[str, Any] = {"status": "SKIPPED"}
    trendline_summary: dict[str, Any] = {"status": "SKIPPED"}
    supply_zone_summary: dict[str, Any] = {"status": "SKIPPED"}
    pattern_summary: dict[str, Any] = {"status": "SKIPPED"}
    if include_chart:
        try:
            from app.services import chart_accuracy
            chart_summary = chart_accuracy.chart_analysis_accuracy(
                market=normalized_market,
                future_bars=20,
                symbol_limit=min(safe_symbol_limit, 12),
                max_cutoffs=safe_max_cutoffs,
            )
            chart_summary.pop("items", None)
            chart_summary.pop("examples", None)
            trendline_summary = chart_accuracy.trendline_accuracy(
                market=normalized_market,
                future_bars=20,
                symbol_limit=safe_symbol_limit,
                max_cutoffs=safe_max_cutoffs,
                include_items=False,
            )
            supply_zone_summary = chart_accuracy.supply_zone_accuracy(
                market=normalized_market,
                future_bars=20,
                symbol_limit=safe_symbol_limit,
                max_cutoffs=safe_max_cutoffs,
                include_items=False,
            )
        except Exception as exc:
            chart_summary = {"status": "ERROR", "error": str(exc)}
    if include_pattern and normalized_market != "all":
        try:
            from app.engine.pattern_strategy import run_walkforward
            pattern_summary = run_walkforward(
                market=normalized_market,
                from_date=None,
                to_date=None,
                horizon_days=5,
                min_score=50,
            )
        except Exception as exc:
            pattern_summary = {"status": "ERROR", "error": str(exc)}

    payload = {
        "status": "OK",
        "generatedAt": _now_iso(),
        "market": normalized_market,
        "policy": {
            "futureLeakage": "historical operation rows are grouped from stored snapshots; chart and pattern checks use OHLCV only through each cutoff, then score future bars.",
            "separation": "Forward realised validation alone drives strategyRows and suggestions. Historical operation and chart evidence are research-only and never merge into the forward denominator.",
            "minSamples": safe_min,
        },
        "counts": {
            "historicalOperationRows": len(history_rows),
            "virtualValidationRows": len(validation_rows),
            "combinedRows": len(history_rows) + len(validation_rows),
            "forwardEligibleRows": sum(1 for row in validation_rows if row.get("returnPct") is not None),
            "forwardStrategyCells": len(strategy_rows),
            "historicalResearchCells": len(historical_research_rows),
        },
        "strategyRows": strategy_rows,
        "historicalResearchRows": historical_research_rows,
        "suggestions": suggestions,
        "patternEvidence": {
            "chartAnalysis": chart_summary,
            "trendlines": trendline_summary,
            "supplyZones": supply_zone_summary,
            "patternWalkforward": pattern_summary,
        },
        "errorReductionPlan": [
            "Use 95% confidence intervals before changing weights; wide intervals stay WATCH only.",
            "Treat STOP_FIRST and STOP clusters as entry/stop calibration evidence, not simple bad-symbol evidence.",
            "Promote a chart pattern only when walk-forward hit rate, trendline respect rate, and supply/demand reaction agree.",
            "Keep DATA_PENDING, NOT_EXECUTED, and low-confidence rows out of win-rate denominators; use them for data-quality and entry-touch diagnostics.",
            "Cap historical replay influence below live forward journal until live samples are sufficient.",
        ],
    }
    try:
        HISTORICAL_CALIBRATION_REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return payload


def entry_efficiency_stats(market: str = "all", horizon: str = "all") -> dict[str, Any]:
    """Measure how efficiently journal entries are actually filled."""
    _ensure()
    rows = _filter_rows(
        _merge_evaluations(_read_journal_rows()),
        market,
        "all",
        horizon,
        "all",
        "all",
        "all",
    )
    total = [r for r in rows if _upper(r.get("status")) not in {"PENDING", "PENDING_FILL", "OPEN"}]
    filled_rows = [r for r in total if str(r.get("filled", "")).lower() in {"true", "1", "yes"}]

    def _parse_date(s: Any) -> date | None:
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s)[:10]).date()
        except Exception:
            return None

    def _row_slippage(row: dict[str, Any]) -> float | None:
        entry = _safe_float(row.get("entry_price"))
        fill = _safe_float(row.get("fill_price"))
        if entry is None or fill is None or entry <= 0:
            return None
        return (fill - entry) / entry * 100

    def _row_fill_days(row: dict[str, Any]) -> int | None:
        signal_date = _parse_date(row.get("as_of_date") or row.get("generated_at"))
        fill_date = _parse_date(row.get("fill_date"))
        if signal_date and fill_date and fill_date >= signal_date:
            return (fill_date - signal_date).days
        return None

    def _avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    slippages = [v for r in filled_rows if (v := _row_slippage(r)) is not None]
    fill_days = [v for r in filled_rows if (v := _row_fill_days(r)) is not None]

    def _horizon_stats(hz: str) -> dict[str, Any]:
        sub_total = [r for r in total if _text(r.get("horizon")).lower() == hz]
        sub_filled = [r for r in sub_total if str(r.get("filled", "")).lower() in {"true", "1", "yes"}]
        sub_slippages = [v for r in sub_filled if (v := _row_slippage(r)) is not None]
        sub_days = [v for r in sub_filled if (v := _row_fill_days(r)) is not None]
        return {
            "horizon": hz,
            "total": len(sub_total),
            "filled": len(sub_filled),
            "fillRate": round(len(sub_filled) / len(sub_total), 4) if sub_total else None,
            "avgSlippagePct": _avg(sub_slippages),
            "avgFillDays": round(sum(sub_days) / len(sub_days), 1) if sub_days else None,
        }

    return {
        "status": "OK",
        "total": len(total),
        "filled": len(filled_rows),
        "fillRate": round(len(filled_rows) / len(total), 4) if total else None,
        "avgSlippagePct": _avg(slippages),
        "avgFillDays": round(sum(fill_days) / len(fill_days), 1) if fill_days else None,
        "byHorizon": [_horizon_stats(h) for h in ("short", "swing", "mid")],
    }


_FEEDBACK_JSON = DATA_DIR / "attribution_feedback.json"


def _attribution_multiplier(
    win_rate: float,
    avg_pnl: float,
    base_win_rate: float,
    base_avg_pnl: float,
) -> float:
    """Return a conservative score multiplier from realized trade outcomes."""
    # Dividing one negative PnL by another inverts performance: a larger loss
    # can look better than the baseline. Negative expectancy never earns a boost.
    if avg_pnl <= 0:
        loss_penalty = min(0.30, abs(avg_pnl) * 0.04)
        low_win_penalty = min(0.20, max(0.0, 0.45 - win_rate) * 0.5)
        return max(0.50, round(0.95 - loss_penalty - low_win_penalty, 3))

    win_edge = (win_rate - base_win_rate) if base_win_rate > 0 else 0.0
    pnl_edge = avg_pnl - max(0.0, base_avg_pnl)
    return max(0.50, min(1.25, round(1.0 + win_edge * 0.6 + min(0.25, pnl_edge * 0.04), 3)))


def attribution_feedback(market: str = "all") -> dict[str, Any]:
    """Generate manual score-adjustment suggestions from journal attribution."""
    _ensure()
    rows = _filter_rows(
        _merge_evaluations(_read_journal_rows()),
        market,
        "all",
        "all",
        "all",
        "all",
        "all",
    )
    evaluated_candidates = [
        r for r in rows
        if _upper(r.get("status")) in {"EVALUATED", "CANCELLED"}
        and _safe_float(r.get("net_pnl_pct")) is not None
    ]
    # 보정 배율의 근거이므로 SOURCE_CALIBRATION_WEIGHTS 정책을 반드시 통과시킨다.
    # 과거 리플레이를 섞으면 승률이 실제보다 좋아 보이고(실측 39.8% vs forward
    # 19.9%), 그 낙관값으로 라이브 점수를 조정하게 된다.
    source_breakdown = _source_breakdown(evaluated_candidates)
    replay_rows = [r for r in evaluated_candidates if not _is_calibration_admissible(r)]
    evaluated_candidates = [r for r in evaluated_candidates if _is_calibration_admissible(r)]
    inconsistent_outcomes = [r for r in evaluated_candidates if not _has_consistent_realized_outcome(r)]
    evaluated = [r for r in evaluated_candidates if _has_consistent_realized_outcome(r)]

    if len(evaluated) < 10:
        return {
            "status": "LOW_SAMPLE",
            "sampleCount": len(evaluated),
            "minRequired": 10,
            "excludedBySourcePolicyCount": len(replay_rows),
            "sourceBreakdown": source_breakdown,
            "adjustments": [],
        }

    all_pnls = [_safe_float(r.get("net_pnl_pct")) for r in evaluated if _safe_float(r.get("net_pnl_pct")) is not None]
    wins = sum(1 for r in evaluated if (_safe_float(r.get("net_pnl_pct")) or 0) > 0)
    base_win_rate = wins / len(evaluated) if evaluated else 0.5
    base_avg_pnl = sum(all_pnls) / len(all_pnls) if all_pnls else 0

    adjustments: list[dict[str, Any]] = []
    for mode in ("conservative", "balanced", "aggressive"):
        for hz in ("short", "swing", "mid"):
            sub = [
                r for r in evaluated
                if _text(r.get("mode")).lower() == mode and _text(r.get("horizon")).lower() == hz
            ]
            if len(sub) < 3:
                continue
            pnls = [_safe_float(r.get("net_pnl_pct")) for r in sub if _safe_float(r.get("net_pnl_pct")) is not None]
            sub_wins = sum(1 for r in sub if (_safe_float(r.get("net_pnl_pct")) or 0) > 0)
            win_rate = sub_wins / len(sub)
            avg_pnl = sum(pnls) / len(pnls) if pnls else 0
            multiplier = _attribution_multiplier(win_rate, avg_pnl, base_win_rate, base_avg_pnl)
            direction = "BOOST" if multiplier > 1.05 else ("REDUCE" if multiplier < 0.95 else "NEUTRAL")
            feedback_id = hashlib.sha256(f"{market}|{mode}|{hz}|{len(sub)}|{round(win_rate, 4)}|{round(avg_pnl, 3)}".encode("utf-8")).hexdigest()[:20]
            adjustments.append({
                "feedbackId": feedback_id,
                "market": market,
                "mode": mode,
                "horizon": hz,
                "n": len(sub),
                "winRate": round(win_rate, 4),
                "avgPnlPct": round(avg_pnl, 3),
                "multiplier": multiplier,
                "direction": direction,
                "suggestedOnly": True,
                "manualApprovalRequired": direction != "NEUTRAL",
            })

    calibration_items = calibration_suggestions(market, "all", "all", "all", "all").get("items", [])
    suggested = [item for item in calibration_items if _upper(item.get("status")) == "SUGGESTED"]
    approved = [item for item in calibration_items if _upper(item.get("approvalStatus")) == "APPROVED"]
    result: dict[str, Any] = {
        "status": "OK",
        "market": market,
        "sampleCount": len(evaluated),
        "excludedInconsistentOutcomeCount": len(inconsistent_outcomes),
        "excludedBySourcePolicyCount": len(replay_rows),
        # 이 승률이 어떤 표본에서 나왔는지 숫자로 남긴다. 예전엔 과거 리플레이가
        # 섞인 32%대가 근거 표시 없이 화면과 보정에 그대로 쓰였다.
        "calibrationBasis": "forward_only(SOURCE_CALIBRATION_WEIGHTS>0)",
        "sourceBreakdown": source_breakdown,
        "baseWinRate": round(base_win_rate, 4),
        "baseAvgPnlPct": round(base_avg_pnl, 3),
        "generatedAt": _now_iso(),
        "autoApplied": False,
        "manualApprovalRequired": True,
        "calibrationSummary": {
            "suggestedCount": len(suggested),
            "approvedCount": len(approved),
            "pendingReviewCount": sum(1 for item in calibration_items if _upper(item.get("approvalStatus")) == "PENDING_REVIEW"),
            "applyEndpoint": "/api/journal/calibration/apply-approved",
        },
        "adjustments": adjustments,
    }
    try:
        _FEEDBACK_JSON.parent.mkdir(parents=True, exist_ok=True)
        _FEEDBACK_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result
