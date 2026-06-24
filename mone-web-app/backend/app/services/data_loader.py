from __future__ import annotations

MONE_LEGACY_PRICE_FILTER_PATCH_VERSION = "v7_intraday_baseline_rebuild"

import json
import os
import re
import time
import threading as _threading
import urllib.request as _url_req
import requests
from datetime import datetime
from pathlib import Path
from typing import Any
from functools import lru_cache

import numpy as np
import pandas as pd
from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("MONE_REPO_ROOT", APP_DIR.parent)).resolve()
REPORT_DIR = REPO_ROOT / "reports"
DATA_DIR = REPO_ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
CACHE_DIR = APP_DIR / "backend" / "cache"
QUOTE_CACHE_FILE = CACHE_DIR / "quotes_cache.json"
SOURCE_HANDOFF_FILE = DATA_DIR / "source_handoff.json"

load_dotenv(REPO_ROOT / ".env")
load_dotenv(APP_DIR / "backend" / ".env")

DEFAULT_VERSION_PRIORITY = ("mone_v36", "stockapp", "v93", "v92", "v91", "v85")
FALLBACK_POLICY = ("mone_v36", "stockapp", "v93", "v92", "v91", "v85")

DEFAULT_SOURCE_HANDOFF = {
    "handoff_at_kst": "2026-05-28 16:00:00",
    "historical_source": "stockapp_local_snapshot",
    "future_source": "github_actions",
    "kr_handoff_date": "2026-05-28",
    "us_handoff_date": "2026-05-28",
}

SOURCE_TYPE_ALIASES = {
    "stockapp_local_snapshot": "stockapp_snapshot",
    "stockapp_snapshot": "stockapp_snapshot",
    "stockapp": "stockapp_snapshot",
    "github": "github_actions",
    "github_actions": "github_actions",
    "local": "local_fallback",
    "local_fallback": "local_fallback",
    "fallback": "local_fallback",
    "stale": "stale",
}

RUNNER_STATUS_FILES = {
    "kr": "runner_status_kr.json",
    "us": "runner_status_us.json",
}

REQUIRED_FILES = [
    "reports/mone_v36_symbol_snapshot_kr.csv",
    "reports/mone_v36_symbol_snapshot_us.csv",
    "reports/mone_v36_action_cards_kr.csv",
    "reports/mone_v36_action_cards_us.csv",
    "reports/mone_v36_today_summary_kr.csv",
    "reports/mone_v36_today_summary_us.csv",
    "reports/mone_v36_virtual_trade_plan_kr.csv",
    "reports/mone_v36_virtual_trade_plan_us.csv",
    "reports/v92_symbol_snapshot_kr.csv",
    "reports/v92_symbol_snapshot_us.csv",
    "reports/v92_position_cards_kr.csv",
    "reports/v92_position_cards_us.csv",
    "reports/v92_action_cards_kr.csv",
    "reports/v92_action_cards_us.csv",
    "reports/v92_pullback_cards_kr.csv",
    "reports/v92_pullback_cards_us.csv",
    "reports/v92_flow_cards_kr.csv",
    "reports/v92_flow_cards_us.csv",
    "reports/v92_risk_cards_kr.csv",
    "reports/v92_risk_cards_us.csv",
    "reports/v92_news_summary_kr.csv",
    "reports/v92_news_summary_us.csv",
    "reports/v92_company_integrated_kr.csv",
    "reports/v92_company_integrated_us.csv",
    "predictions.csv",
    "data/history/prediction_history.csv",
    "data/history/outcome_history.csv",
    "watchlist_kr_growth.csv",
    "watchlist_us_growth.csv",
    "watchlist_kr.csv",
    "watchlist_us.csv",
    "candidate_universe_kr.csv",
    "candidate_universe_us.csv",
    "holdings_kr.csv",
    "holdings_us.csv",
    "daily_watch_selection.json",
]

ENV_KEYS = [
    "GNEWS_API_KEY",
    "FINNHUB_API_KEY",
    "DART_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "KIS_ACCOUNT_NO",
    "KIS_ACCOUNT",
    "KIS_CANO",
    "KIS_ACNT_PRDT_CD",
    "SEC_USER_AGENT",
]


DEFAULT_STOCKAPP_ROOTS = [
    Path(r"C:\Users\minbo\OneDrive\바탕 화면\stock_ai_app_new"),
    Path(r"C:\Users\minbo\OneDrive\바탕 화면\stock_app\stock_app"),
    Path(r"C:\Users\minbo\OneDrive\바탕 화면\stock_app"),
]


def _split_env_paths(value: str) -> list[Path]:
    if not value:
        return []
    parts: list[str] = []
    for chunk in value.split(";"):
        parts.extend(chunk.split(os.pathsep))
    return [Path(part.strip()).expanduser() for part in parts if part.strip()]


EXCLUDED_SCAN_PARTS = {
    ".git", ".venv", "venv", "env", "node_modules", ".next", "__pycache__",
    "site-packages", "dist", "build", "cache", ".cache", "logs",
}

ALLOWED_STOCKAPP_FILE_KEYWORDS = (
    "prediction", "predictions", "outcome", "actual", "buy_priority", "scanner",
    "flow", "supply", "investor", "quote", "orderbook", "ohlcv", "daily", "chart",
    "disclosure", "filing", "dart", "sec", "financial", "fundamental", "company",
    "portfolio", "risk", "candidate", "watchlist", "history", "summary", "operation",
)


def _is_excluded_path(path: Path) -> bool:
    parts = {str(part).lower() for part in path.parts}
    return bool(parts & EXCLUDED_SCAN_PARTS)


def _unique_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = path.resolve().as_posix().lower()
        except Exception:
            key = path.as_posix().lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _canonical_source_type(value: Any) -> str:
    key = _safe_str(value).lower()
    allowed = {"stockapp_snapshot", "github_actions", "local_fallback", "stale"}
    return SOURCE_TYPE_ALIASES.get(key, key if key in allowed else "local_fallback")


def source_handoff() -> dict[str, Any]:
    payload = read_json(SOURCE_HANDOFF_FILE)
    merged = dict(DEFAULT_SOURCE_HANDOFF)
    if payload:
        merged.update({key: value for key, value in payload.items() if value not in (None, "")})
    merged["historical_source_type"] = _canonical_source_type(merged.get("historical_source"))
    merged["future_source_type"] = _canonical_source_type(merged.get("future_source"))
    return merged


def _date_key_text(value: Any) -> str:
    text = _safe_str(value)
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text[:10] if len(text) >= 10 else ""


def _datetime_key(value: Any) -> datetime | None:
    text = _safe_str(value)
    if not text:
        return None
    normalized = text.replace("T", " ").replace("/", "-")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized[:len(datetime.now().strftime(fmt))], fmt)
        except Exception:
            continue
    return None


def preferred_source_type(market: str, request_date: Any = "") -> str:
    mk = "us" if market == "us" else "kr"
    handoff = source_handoff()
    request_key = _date_key_text(request_date) or datetime.now().strftime("%Y-%m-%d")
    handoff_key = _date_key_text(handoff.get(f"{mk}_handoff_date") or handoff.get("handoff_at_kst"))
    historical = request_key <= handoff_key if mk == "kr" else request_key < handoff_key
    return handoff["historical_source_type"] if historical else handoff["future_source_type"]


def _source_type_for_label(label: str, market: str = "", request_date: Any = "") -> str:
    text = _safe_str(label).replace("\\", "/").lower()
    if not text:
        return preferred_source_type(market, request_date) if market else "local_fallback"
    if text.startswith("stockapp://") or "data/stockapp/" in text or "/data/stockapp/" in text or "reports/stockapp_" in text:
        return "stockapp_snapshot"
    if text == "predictions.csv" or text.startswith("reports/mone_v36_") or text in {"runner_status_kr.json", "runner_status_us.json"}:
        return "github_actions"
    return "local_fallback"


def _effective_source_type(source_type: str, preferred: str, fallback: bool = False) -> str:
    source_type = _canonical_source_type(source_type)
    preferred = _canonical_source_type(preferred)
    if source_type == preferred and not fallback:
        return source_type
    if preferred == "github_actions" and source_type == "stockapp_snapshot":
        return "stale"
    if fallback:
        return "local_fallback"
    return source_type


def _source_status(source_type: str, existing: str = "") -> str:
    if source_type == "stale":
        return "STALE: GitHub Actions result missing; using StockApp snapshot fallback"
    if source_type == "local_fallback":
        return "PARTIAL: preferred source missing; using local fallback"
    return existing


def _annotate_source_rows(
    rows: list[dict[str, Any]],
    market: str,
    source: str,
    request_date: Any = "",
    fallback: bool = False,
) -> list[dict[str, Any]]:
    if not rows:
        return rows
    preferred = preferred_source_type(market, request_date)
    source_type = _source_type_for_label(source, market, request_date)
    annotated: list[dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        row_date = _row_source_date(merged) or request_date
        row_preferred = preferred_source_type(market, row_date) if row_date else preferred
        effective = _effective_source_type(source_type, row_preferred, fallback)
        merged["sourceType"] = effective
        merged.setdefault("sourceFile", source)
        merged.setdefault("sourceDate", row_date)
        merged["isFallback"] = effective in {"local_fallback", "stale"}
        status = _source_status(effective, first_value(merged, DATA_STATUS_ALIASES, ""))
        if status:
            merged.setdefault("data_status", status)
            merged.setdefault("price_data_status", status)
        annotated.append(merged)
    return annotated


def stockapp_roots() -> list[Path]:
    """기존 StockApp 작업스케줄러 출력 폴더를 MONE의 보조 데이터 소스로 사용합니다.

    GitHub/KIS handoff 이후에는 OneDrive의 옛 StockApp 기본 폴더가
    stale quote snapshot을 다시 섞을 수 있으므로 기본값은 사용하지 않습니다.
    정말 필요할 때만 MONE_ENABLE_LEGACY_STOCKAPP_ROOTS=1 또는
    MONE_STOCKAPP_ROOTS로 명시한 경로를 사용합니다.
    """
    roots: list[Path] = []
    explicit_roots = _split_env_paths(os.environ.get("MONE_STOCKAPP_ROOTS", ""))
    legacy_defaults = DEFAULT_STOCKAPP_ROOTS if os.environ.get("MONE_ENABLE_LEGACY_STOCKAPP_ROOTS", "0").strip() == "1" else []
    for root in explicit_roots + legacy_defaults:
        try:
            resolved = root.resolve()
        except Exception:
            resolved = root
        if resolved not in roots and resolved.exists():
            roots.append(resolved)
    return roots


def _stockapp_data_bases(root: Path) -> list[Path]:
    candidates: list[Path] = []
    if root.name.lower() == "data":
        candidates.append(root)
    else:
        candidates.extend([root / "data", root / "data" / "history", root / "data" / "market", root / "data" / "market" / "ohlcv", root / "data" / "disclosures"])
    return [p for p in _unique_paths(candidates) if p.exists() and not _is_excluded_path(p)]


def _stockapp_report_bases(root: Path) -> list[Path]:
    candidates: list[Path] = []
    if root.name.lower() == "reports":
        candidates.append(root)
    else:
        candidates.append(root / "reports")
    return [p for p in _unique_paths(candidates) if p.exists() and not _is_excluded_path(p)]


def data_roots() -> list[Path]:
    roots = [DATA_DIR]
    for root in stockapp_roots():
        roots.extend(_stockapp_data_bases(root))
    return _unique_paths([p for p in roots if p.exists()])


def report_roots() -> list[Path]:
    roots = [REPORT_DIR]
    for root in stockapp_roots():
        roots.extend(_stockapp_report_bases(root))
    return _unique_paths([p for p in roots if p.exists()])


def source_label(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except Exception:
        for root in stockapp_roots():
            try:
                return "stockapp://" + path.relative_to(root).as_posix()
            except Exception:
                pass
        return path.as_posix()


def _runner_status_candidates(market: str) -> list[Path]:
    name = RUNNER_STATUS_FILES.get("us" if market == "us" else "kr", "runner_status_kr.json")
    github_candidates = [
        REPO_ROOT / name,
        REPORT_DIR / name,
    ]
    stockapp_candidates = [
        DATA_DIR / "stockapp" / name,
        REPORT_DIR / f"stockapp_{name}",
    ]
    for root in stockapp_roots():
        stockapp_candidates.extend([root / name, root / "data" / name, root / "reports" / name])
    preferred = preferred_source_type(market)
    candidates = stockapp_candidates + github_candidates if preferred == "stockapp_snapshot" else github_candidates + stockapp_candidates
    return _unique_paths([path for path in candidates if path.exists() and path.stat().st_size > 0])


@lru_cache(maxsize=16)
def runner_status(market: str) -> dict[str, Any]:
    for path in _runner_status_candidates(market):
        payload = read_json(path)
        if payload:
            payload = dict(payload)
            source = source_label(path)
            request_date = first_value(payload, ["target_date", "targetDate", "date"], "")
            preferred = preferred_source_type(market, request_date)
            source_type = _effective_source_type(_source_type_for_label(source, market, request_date), preferred)
            payload["_sourceFile"] = source
            payload["sourceType"] = source_type
            if source_type in {"local_fallback", "stale"}:
                payload["dataStatus"] = _source_status(source_type, _safe_str(payload.get("dataStatus", "")))
            return payload
    return {}


def runner_target_date(market: str) -> str:
    if preferred_source_type(market) == "stockapp_snapshot":
        dates: list[str] = []
        for file_name in ("operation_health_{market}.csv", "operational_readiness_{market}.csv", "prediction_integrity_status.csv"):
            rows, _ = stockapp_report_rows(market, file_name)
            for row in rows:
                target = first_value(row, ["target_date", "targetDate", "date"], "")
                if target:
                    dates.append(_normalize_date_text(target))
        if dates:
            return max(dates)
    return first_value(runner_status(market), ["target_date", "targetDate", "date"], "")


def _normalize_date_text(value: Any) -> str:
    text = _safe_str(value)
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text[:10] if len(text) >= 10 else text


def _row_source_date(row: dict[str, Any]) -> str:
    return _normalize_date_text(first_value(row, ["target_date", "targetDate", "actual_date", "data_date", "basis_ohlc_date", "created_at", "updated_at"], ""))


def _iter_relevant_csv_files(bases: list[Path], limit: int = 300) -> list[Path]:
    files: list[Path] = []
    for base in bases:
        if not base.exists() or _is_excluded_path(base):
            continue
        for path in base.rglob("*.csv"):
            if _is_excluded_path(path):
                continue
            low = path.name.lower()
            full = path.as_posix().lower()
            if not any(token in low or token in full for token in ALLOWED_STOCKAPP_FILE_KEYWORDS):
                continue
            files.append(path)
            if len(files) >= limit:
                return _unique_paths(files)
    return _unique_paths(files)


def stockapp_bridge_status() -> dict[str, Any]:
    roots = []
    for root in stockapp_roots():
        bases = _stockapp_data_bases(root) + _stockapp_report_bases(root)
        files = _iter_relevant_csv_files(bases, limit=300)
        latest = max((file_mtime(path) for path in files), default="")
        roots.append({
            "root": root.as_posix(),
            "status": "OK" if files else "NO_CSV",
            "csvFiles": len(files),
            "latestUpdatedAt": latest,
            "examples": [source_label(path) for path in sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[:8]],
            "scanBases": [base.as_posix() for base in bases[:8]],
            "scanMode": "light-index",
        })
    return {
        "status": "OK" if roots else "NOT_FOUND",
        "message": "StockApp 작업스케줄러 출력 폴더의 data/reports만 빠르게 스캔합니다." if roots else "StockApp 출력 폴더를 찾지 못했습니다. MONE_STOCKAPP_ROOTS 환경변수로 지정할 수 있습니다.",
        "roots": roots,
        "envKey": "MONE_STOCKAPP_ROOTS",
        "optimized": True,
    }

MISSING_TOKENS = {"", "-", "nan", "none", "nat", "null", "n/a", "na", "없음"}

SYMBOL_ALIASES = ["symbol", "ticker", "code", "종목코드", "종목", "stock_code"]
NAME_ALIASES = ["name", "종목명", "stock_name", "종목", "회사명"]
CURRENT_PRICE_ALIASES = ["current_price", "last_price", "현재가", "실시간현재가", "quote_fallback_price", "current_price_at_prediction", "basis_close", "prev_close"]
KR_OHLC_CLOSE_ALIASES = ["basis_close", "ohlcv_close", "close", "종가", "prev_close", "current_price_at_prediction"]
PRICE_TIME_ALIASES = ["가격기준시각", "updated_at", "last_time", "quote_time", "price_time", "갱신시각"]
PRICE_SOURCE_ALIASES = ["가격출처", "quote_source_label", "quote_source", "current_price_source", "source"]
STOCKAPP_PRICE_ALIASES = ["currentPrice", "current_price", "current", "last", "lastPrice", "last_price", "regularMarketPrice", "실시간현재가", "현재가", "current_price_at_prediction", "close", "actual_close", "basis_close", "prev_close", "last_close", "price", "final_price", "close_price", "종가"]
STOCKAPP_PRICE_DATE_ALIASES = ["priceSourceDate", "priceTime", "price_time", "quote_time", "updated_at", "created_at", "report_generated_at", "target_date", "targetDate", "예측대상일", "actual_date", "date", "날짜", "일자", "basis_ohlc_date", "prediction_date"]
ENTRY_ALIASES = ["기준가", "관찰 기준가", "active_scenario_pullback_price", "조건부 진입가", "매수가", "entry", "entry_price", "buy_price", "우선진입가", "보수대기선", "preferred_entry", "conservative_entry", "technical_entry"]
STOP_ALIASES = ["손절가", "stop", "stop_loss", "stop_loss_price"]
TARGET_ALIASES = ["목표가", "1차 목표가", "1차익절가", "tp1", "target_price", "take_profit1", "2차 목표가", "2차익절가", "tp2"]
TARGET2_ALIASES = ["2차 목표가", "tp2", "take_profit2"]
EXPECTED_PRICE_ALIASES = {
    "1d": ["1일예상가", "1일 예상가", "예상가_1일", "expected_price_1d", "pred_price_1d", "predicted_price_1d", "price_1d", "target_price_1d"],
    "3d": ["3일예상가", "3일 예상가", "예상가_3일", "expected_price_3d", "pred_price_3d", "predicted_price_3d", "price_3d", "target_price_3d"],
    "5d": ["5일예상가", "5일 예상가", "예상가_5일", "expected_price_5d", "pred_price_5d", "predicted_price_5d", "price_5d", "target_price_5d"],
    "20d": ["20일예상가", "20일 예상가", "예상가_20일", "expected_price_20d", "pred_price_20d", "predicted_price_20d", "price_20d", "target_price_20d", "midterm_expected_price"],
}
SUPPLY_SCORE_ALIASES = ["수급점수", "수급 점수", "supply_score", "flow_score", "수급", "supply_label", "supply_summary"]
EARNINGS_SCORE_ALIASES = ["실적점수", "실적 점수", "earnings_score", "fundamental_score", "재무", "fundamental_label"]
VALUATION_SCORE_ALIASES = ["밸류에이션점수", "밸류에이션 점수", "벨류에이션점수", "valuation_score", "fundamental_label"]
CHART_SCORE_ALIASES = ["차트점수", "차트 점수", "chart_score", "technical_score", "technical_verdict", "판정"]
DATA_STATUS_ALIASES = ["data_status", "price_data_status", "earnings_data_status", "valuation_data_status", "flow_data_status"]

MERGE_ALIAS_GROUPS = [
    SYMBOL_ALIASES,
    NAME_ALIASES,
    CURRENT_PRICE_ALIASES,
    PRICE_TIME_ALIASES,
    PRICE_SOURCE_ALIASES,
    ENTRY_ALIASES,
    STOP_ALIASES,
    TARGET_ALIASES,
    SUPPLY_SCORE_ALIASES,
    EARNINGS_SCORE_ALIASES,
    VALUATION_SCORE_ALIASES,
    CHART_SCORE_ALIASES,
    DATA_STATUS_ALIASES,
    ["다음행동", "nextAction", "suggested_action", "final_judgment"],
    ["예상시초가", "pred_open_mid", "pred_open", "expected_open", "premarket_price"],
    ["예상종가", "pred_close_mid", "pred_close", "expected_close"],
    ["손익비", "rr", "rr1", "risk_reward", "risk_reward_ratio"],
]


def _safe_str(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if text.lower() in MISSING_TOKENS:
        return fallback
    return text or fallback


def _is_missing(value: Any) -> bool:
    return _safe_str(value, "") == ""


def _safe_float(value: Any) -> float | None:
    try:
        text = _safe_str(value)
        if not text:
            return None
        text = text.replace(",", "").replace("%", "")
        text = re.sub(r"[^0-9.+-]", "", text)
        if not text or text in {".", "+", "-"}:
            return None
        out = float(text)
        if np.isnan(out) or np.isinf(out):
            return None
        return out
    except Exception:
        return None


def _market_label(market: str) -> str:
    return "한국주식" if market == "kr" else "미국주식"


def normalize_symbol(symbol: Any, market: str = "") -> str:
    text = _safe_str(symbol).upper().strip()
    text = text.replace(".KS", "").replace(".KQ", "")
    # CSVs often load Korean stock codes as "10120.0". Treat them as codes.
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if market == "kr":
        digits = re.sub(r"\D", "", text)
        if digits and len(digits) <= 6:
            return digits.zfill(6)
    return text


def read_csv(path: Path, usecols: list[str] | None = None, nrows: int | None = None) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding, low_memory=False, usecols=usecols, nrows=nrows).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        return {}
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            data = json.loads(path.read_text(encoding=encoding))
            return data if isinstance(data, dict) else {}
        except Exception:
            continue
    return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rows_for(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    if path.suffix.lower() == ".csv":
        # 상태표 계산에서 전체 CSV를 pandas로 모두 읽으면 StockApp fallback 연결 시 매우 느려집니다.
        # 행 수는 빠른 라인 카운트로 계산하고, 큰 파일은 10000행까지만 세어 UI 로딩을 보호합니다.
        try:
            count = 0
            with path.open("rb") as f:
                for _ in f:
                    count += 1
                    if count >= 10001:
                        return 10000
            return max(count - 1, 0)
        except Exception:
            return 0
    if path.suffix.lower() == ".json":
        data = read_json(path)
        return int(len(data)) if data else 0
    return 0


def file_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def first_value(row: dict[str, Any] | pd.Series, names: list[str], fallback: str = "") -> str:
    for name in names:
        if name in row:
            text = _safe_str(row.get(name), "")
            if text:
                return text
    return fallback


def first_number(row: dict[str, Any] | pd.Series, names: list[str]) -> float | None:
    for name in names:
        if name in row:
            num = _safe_float(row.get(name))
            if num is not None:
                return num
    return None


def report_path(kind: str, market: str, versions: tuple[str, ...] = DEFAULT_VERSION_PRIORITY) -> Path | None:
    # 1순위는 현재 MONE repo, 2순위는 기존 StockApp 작업스케줄러 출력 폴더입니다.
    for base in report_roots():
        for version in versions:
            path = base / f"{version}_{kind}_{market}.csv"
            if path.exists() and path.stat().st_size > 0 and rows_for(path) > 0:
                return path
    return None


def read_report(kind: str, market: str, versions: tuple[str, ...] = DEFAULT_VERSION_PRIORITY) -> tuple[pd.DataFrame, str]:
    path = report_path(kind, market, versions)
    if path is None:
        return pd.DataFrame(), ""
    return read_csv(path), source_label(path)


def dataframe_records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    work = df.head(limit).copy() if limit else df.copy()
    return work.replace({np.nan: ""}).to_dict(orient="records")


def quote_cache() -> dict[str, Any]:
    data = read_json(QUOTE_CACHE_FILE)
    if not data:
        return {"updatedAt": "", "markets": {"kr": {}, "us": {}}}
    data.setdefault("markets", {})
    data["markets"].setdefault("kr", {})
    data["markets"].setdefault("us", {})
    return data


def save_quote_cache(cache: dict[str, Any]) -> None:
    write_json(QUOTE_CACHE_FILE, cache)


def cached_quote_for(symbol: str, market: str) -> dict[str, Any]:
    cache = quote_cache()
    return dict((cache.get("markets", {}).get(market, {}) or {}).get(normalize_symbol(symbol, market), {}) or {})


def apply_quote_cache(row: dict[str, Any], market: str) -> dict[str, Any]:
    symbol = _row_symbol(row, market)
    cached = cached_quote_for(symbol, market) if symbol else {}
    if not cached or not cached.get("ok"):
        return row
    price = cached.get("currentPrice")
    if _safe_float(price) is None:
        return row

    # Do not let an old local quote cache overwrite a newer GitHub/StockApp
    # row. This was the main cause of today's reports showing 5/27 prices
    # even when 5/29 order-plan/report rows were already loaded.
    cache_time = cached.get("priceTime", "") or quote_cache().get("updatedAt", "")
    if cache_time and not _date_is_today(cache_time):
        # 주말·장외 시간대에는 최근 3일 이내 전일 종가 캐시를 현재가로 허용
        cache_key = _date_key(cache_time)
        if not (_is_market_closed_now() and _days_since(cache_key) <= 3):
            return row
    row_date = first_value(row, ["sourceDate", "report_generated_at", "created_at", "updated_at", "basis_ohlc_date", "date", "일자"], "")
    if row_date and cache_time and _date_is_older(cache_time, row_date):
        return row

    merged = dict(row)
    merged["current_price"] = str(price)
    merged["last_price"] = str(price)
    merged["quote_fallback_price"] = str(price)
    merged["가격기준시각"] = cache_time or "현재가 기준시각 없음"
    merged["가격출처"] = cached.get("priceSource", "") or "가격출처 없음"
    merged["quote_source_label"] = cached.get("priceSource", "") or "가격출처 없음"
    merged["quote_source"] = cached.get("source", "") or cached.get("priceSource", "") or "가격출처 없음"
    merged["current_price_source"] = cached.get("priceSource", "") or "가격출처 없음"
    merged["data_status"] = "현재가 캐시 반영"
    merged["priceSourceType"] = "kis"
    merged["priceSourceFile"] = source_label(QUOTE_CACHE_FILE)
    merged["priceSourceDate"] = cache_time
    merged["price_data_status"] = "cache_success"
    return merged


def _row_symbol(row: dict[str, Any] | pd.Series, market: str) -> str:
    # StockApp order-plan rows often use "종목" for the Korean company name and "stock_code" for the code.
    # Prefer explicit code/ticker columns so Korean names are not mistaken for symbols.
    preferred = ["symbol", "ticker", "code", "종목코드", "stock_code", "stockCode", "종목"]
    value = first_value(row, preferred)
    if market == "kr" and value and not re.fullmatch(r"\d{1,6}", str(value).strip().replace(".0", "")):
        value = first_value(row, ["stock_code", "종목코드", "code", "ticker", "symbol"])
    return normalize_symbol(value, market)


def _symbol_belongs_to_market(symbol: Any, market: str) -> bool:
    text = normalize_symbol(symbol, market)
    if not text:
        return False
    if market == "kr":
        return bool(re.fullmatch(r"\d{6}", text))
    return bool(re.fullmatch(r"[A-Z][A-Z0-9._-]{0,12}", text)) and not text.isdigit()


def _records_by_symbol(df: pd.DataFrame, market: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in dataframe_records(df):
        symbol = _row_symbol(row, market)
        if symbol and _symbol_belongs_to_market(symbol, market) and symbol not in out:
            out[symbol] = row
    return out


def _group_has_value(row: dict[str, Any], aliases: list[str]) -> bool:
    return any((name in row and not _is_missing(row.get(name))) for name in aliases)


def _merge_alias_values(base: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for aliases in MERGE_ALIAS_GROUPS:
        if _group_has_value(merged, aliases):
            continue
        for name in aliases:
            if name in fallback and not _is_missing(fallback.get(name)):
                merged[name] = fallback.get(name)
                break
    return merged


def enrich_records_with_version_fallback(kind: str, market: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows

    fallback_maps: list[dict[str, dict[str, Any]]] = []
    for version in FALLBACK_POLICY:
        path = REPORT_DIR / f"{version}_{kind}_{market}.csv"
        if path.exists() and path.stat().st_size > 0:
            fallback_maps.append(_records_by_symbol(read_csv(path), market))

    enriched: list[dict[str, Any]] = []
    for row in rows:
        symbol = _row_symbol(row, market)
        merged = dict(row)
        if symbol:
            for fallback_map in fallback_maps:
                fallback = fallback_map.get(symbol)
                if fallback:
                    merged = _merge_alias_values(merged, fallback)
        enriched.append(merged)
    return enriched


def enrich_records_from_file(rows: list[dict[str, Any]], path: Path, market: str) -> list[dict[str, Any]]:
    fallback_map = _records_by_symbol(read_csv(path), market)
    if not fallback_map:
        return rows
    enriched = []
    for row in rows:
        symbol = _row_symbol(row, market)
        enriched.append(_merge_alias_values(row, fallback_map.get(symbol, {})) if symbol else row)
    return enriched


def format_price(value: float | None, market: str) -> str:
    if value is None:
        return "현재가 없음"
    if market == "us":
        return f"${value:,.2f}"
    return f"{value:,.0f}원"


def format_signed_money(value: float | None, market: str, missing: str = "평가손익 없음") -> str:
    if value is None:
        return missing
    sign = "+" if value > 0 else ""
    if market == "us":
        return f"{sign}${value:,.2f}"
    return f"{sign}{value:,.0f}원"


def format_percent(value: float | None, missing: str = "수익률 없음") -> str:
    if value is None:
        return missing
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"



def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _format_probability(value: float | None) -> str:
    if value is None:
        return "확률 산출 필요"
    return f"{_clamp(value, 1, 99):.1f}%"


def _extract_percent(value: Any) -> float | None:
    num = _safe_float(value)
    if num is None:
        return None
    if 0 <= num <= 1:
        return num * 100
    return num


def _ohlcv_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    lower = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        key = alias.lower()
        if key in lower:
            return lower[key]
    return None


def _find_ohlcv_candidates(symbol: str, market: str) -> list[Path]:
    """Fast OHLCV lookup.

    Earlier versions recursively scanned data/ and reports/ for every symbol, which
    became very slow once StockApp/backtest folders were copied in. v3.5.11 only
    searches known chart/OHLCV folders and direct filename patterns.
    """
    symbol = normalize_symbol(symbol, market)
    names = [
        f"{market}_{symbol}_daily.csv",
        f"{market}_{symbol}_ohlcv.csv",
        f"{symbol}_daily.csv",
        f"{symbol}_ohlcv.csv",
        f"ohlcv_{market}_{symbol}.csv",
        f"chart_{market}_{symbol}.csv",
    ]
    roots = [
        DATA_DIR / "market" / "ohlcv",
        DATA_DIR / "market",
        DATA_DIR / "chart",
        DATA_DIR / "ohlcv",
    ]
    for root in stockapp_roots():
        roots.extend([
            root / "market" / "ohlcv",
            root / "market",
            root / "ohlcv",
            root / "chart",
            root / "data" / "market" / "ohlcv",
            root / "data" / "market",
            root / "data" / "ohlcv",
            root / "data" / "chart",
        ])
    roots = _unique_paths([r for r in roots if r.exists() and not _is_excluded_path(r)])
    found: list[Path] = []
    for base in roots:
        for name in names:
            p = base / name
            if p.exists() and p.is_file() and p.stat().st_size > 0:
                found.append(p)
        # Only scan shallow OHLCV/chart folders, never the whole data/reports tree.
        for p in base.glob("*.csv"):
            low = p.name.lower()
            if symbol.lower() in low and any(token in low for token in ("daily", "ohlcv", "chart")):
                found.append(p)
    seen: set[str] = set()
    out: list[Path] = []
    for p in found:
        key = p.resolve().as_posix()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _normalize_ohlcv_dataframe(df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    symbol_col = _ohlcv_column(work, ["symbol", "ticker", "code", "종목코드"])
    if symbol_col:
        # 빈 symbol 행은 파일명 기준 종목으로 간주 (DRAM/MRVL 혼재 케이스 대응)
        is_empty = work[symbol_col].astype(str).str.strip().isin(["", "nan", "NaN"])
        norm = work[symbol_col].map(lambda v: normalize_symbol(v, market) if str(v).strip() not in ("", "nan", "NaN") else "")
        target = normalize_symbol(symbol, market)
        filtered = work[is_empty | (norm == target)]
        if not filtered.empty:
            work = filtered
    date_col = _ohlcv_column(work, ["date", "날짜", "일자", "datetime", "time"])
    open_col = _ohlcv_column(work, ["open", "시가"])
    high_col = _ohlcv_column(work, ["high", "고가"])
    low_col = _ohlcv_column(work, ["low", "저가"])
    close_col = _ohlcv_column(work, ["close", "종가", "adj_close", "adj close"])
    volume_col = _ohlcv_column(work, ["volume", "거래량"])
    if not close_col:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["date"] = work[date_col].astype(str) if date_col else [str(i + 1) for i in range(len(work))]
    out["open"] = work[open_col].map(_safe_float) if open_col else work[close_col].map(_safe_float)
    out["high"] = work[high_col].map(_safe_float) if high_col else work[close_col].map(_safe_float)
    out["low"] = work[low_col].map(_safe_float) if low_col else work[close_col].map(_safe_float)
    out["close"] = work[close_col].map(_safe_float)
    out["volume"] = work[volume_col].map(_safe_float) if volume_col else 0
    out = out.dropna(subset=["close"]).copy()
    if out.empty:
        return out
    out["date_sort"] = pd.to_datetime(out["date"], errors="coerce")
    if out["date_sort"].notna().any():
        out = out.sort_values("date_sort")
    return out.drop(columns=["date_sort"], errors="ignore").tail(240).reset_index(drop=True)


def _actual_close_history_files(market: str) -> list[Path]:
    """Return StockApp/MONE files that can be used as a chart fallback.

    Some installations do not have per-symbol OHLCV CSVs yet, but they do have
    actual close validation files.  These are not a full candle feed, so the
    chart API labels them as a close-history fallback instead of pretending they
    are real OHLCV.
    """
    candidates = [
        DATA_DIR / "decision_system" / "actual_results.csv",
        DATA_DIR / "stockapp" / "actual_results.csv",
        DATA_DIR / "adjustment_performance_report.csv",
        DATA_DIR / "stockapp" / "adjustment_performance_report.csv",
        REPORT_DIR / f"mone_v36_final_prediction_validation_{market}.csv",
    ]
    try:
        candidates.extend(_find_data_files((r"actual_results", r"adjustment_performance_report", r"prediction_validation"), ("node_modules", "backtest")))
    except Exception:
        pass
    existing = [path for path in candidates if path.exists() and path.is_file() and path.suffix.lower() == ".csv" and path.stat().st_size > 0]
    return _unique_paths(existing)


def _load_actual_close_history(symbol: str, market: str) -> tuple[pd.DataFrame, str]:
    target = normalize_symbol(symbol, market)
    frames: list[tuple[pd.DataFrame, str]] = []
    for path in _actual_close_history_files(market):
        df = read_csv(path)
        if df.empty:
            continue
        symbol_col = _ohlcv_column(df, ["ticker", "symbol", "stock_code", "code", "종목코드"])
        close_col = _ohlcv_column(df, ["actual_close", "actualClose", "close", "종가", "실제종가", "final_price", "current_price", "currentPrice"])
        date_col = _ohlcv_column(df, ["target_date", "actual_result_date", "date", "날짜", "일자", "예측대상일", "prediction_date"])
        if not symbol_col or not close_col or not date_col:
            continue
        work = df.copy()
        work["_symbol"] = work[symbol_col].map(lambda value: normalize_symbol(value, market))
        work = work[work["_symbol"] == target]
        if work.empty:
            continue
        out = pd.DataFrame()
        out["date"] = work[date_col].astype(str).map(_date_key)
        out["close"] = work[close_col].map(_safe_float)
        open_col = _ohlcv_column(work, ["open", "actual_open", "시가"])
        high_col = _ohlcv_column(work, ["high", "actual_high", "고가"])
        low_col = _ohlcv_column(work, ["low", "actual_low", "저가"])
        volume_col = _ohlcv_column(work, ["volume", "거래량"])
        out["open"] = work[open_col].map(_safe_float) if open_col else out["close"]
        out["high"] = work[high_col].map(_safe_float) if high_col else out[["open", "close"]].max(axis=1)
        out["low"] = work[low_col].map(_safe_float) if low_col else out[["open", "close"]].min(axis=1)
        out["volume"] = work[volume_col].map(_safe_float) if volume_col else 0
        out = out.dropna(subset=["close"])
        out = out[out["date"].astype(str) != ""]
        if out.empty:
            continue
        frames.append((out, source_label(path)))
    if not frames:
        return pd.DataFrame(), ""
    combined = pd.concat([frame for frame, _source in frames], ignore_index=True)
    combined["date_sort"] = pd.to_datetime(combined["date"], errors="coerce")
    combined = combined.sort_values(["date_sort", "date"]).drop_duplicates(subset=["date"], keep="last")
    combined = combined.drop(columns=["date_sort"], errors="ignore").tail(240).reset_index(drop=True)
    sources = list(dict.fromkeys(source for _frame, source in frames))
    return combined, " · ".join(sources[:3]) + " · close-history fallback"


@lru_cache(maxsize=1024)
def _load_ohlcv(symbol: str, market: str) -> tuple[pd.DataFrame, str]:
    for path in _find_ohlcv_candidates(symbol, market):
        df = _normalize_ohlcv_dataframe(read_csv(path), symbol, market)
        if not df.empty and len(df) >= 5:
            return df, source_label(path)
    fallback_df, fallback_source = _load_actual_close_history(symbol, market)
    if not fallback_df.empty and len(fallback_df) >= 2:
        return fallback_df, fallback_source
    return pd.DataFrame(), ""


@lru_cache(maxsize=1024)
def _ohlcv_stats(symbol: str, market: str) -> dict[str, float | str | int]:
    df, source = _load_ohlcv(symbol, market)
    if df.empty:
        return {"source": source, "rows": 0, "avgReturn": 0.001, "volatility": 0.022, "gapAvg": 0.0, "lastClose": 0.0, "lastDate": ""}
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    last_date = str(df["date"].iloc[-1]) if "date" in df and len(df) else ""
    if len(close) < 2:
        return {"source": source, "rows": len(df), "avgReturn": 0.001, "volatility": 0.022, "gapAvg": 0.0, "lastClose": float(close.iloc[-1]) if len(close) else 0.0, "lastDate": last_date}
    returns = close.pct_change().dropna()
    avg_return = float(returns.tail(20).mean()) if len(returns) else 0.001
    volatility = float(returns.tail(60).std()) if len(returns) > 3 else 0.022
    if not np.isfinite(volatility) or volatility <= 0:
        volatility = 0.022
    gap_avg = 0.0
    if "open" in df and len(df) >= 2:
        prev_close = close.shift(1)
        open_values = pd.to_numeric(df["open"], errors="coerce")
        gaps = ((open_values - prev_close) / prev_close).replace([np.inf, -np.inf], np.nan).dropna()
        if len(gaps):
            gap_avg = float(gaps.tail(20).mean())
    return {
        "source": source,
        "rows": len(df),
        "avgReturn": avg_return if np.isfinite(avg_return) else 0.001,
        "volatility": _clamp(volatility, 0.004, 0.08),
        "gapAvg": _clamp(gap_avg, -0.04, 0.04),
        "lastClose": float(close.iloc[-1]),
        "lastDate": last_date,
    }


def _date_key(value: Any) -> str:
    text = _safe_str(value)
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return digits[:8]
    return digits


def _today_key() -> str:
    return _kst_now().strftime("%Y%m%d")


def _date_is_today(value: Any) -> bool:
    key = _date_key(value)
    return bool(key and key == _today_key())


def _is_legacy_quote_source(source: Any, market: str = "") -> bool:
    """Return True for old/unscoped StockApp quote snapshots that must not drive prices.

    After the GitHub/KIS handoff, market-specific files such as
    reports/kis_current_price_us.csv and reports/intraday_realtime_snapshot_us.csv
    are the only quote snapshot files that should win.  Old common files and
    external StockApp files can contain stale rows, e.g.
    stockapp://reports/intraday_realtime_snapshot-Kang.csv or
    data/mone_live_quote_cache.csv.
    """
    text = _safe_str(source).replace("\\", "/").lower()
    mk = (market or "").lower()
    if not text:
        return False

    allowed_names = []
    if mk in {"kr", "us"}:
        allowed_names = [
            f"kis_current_price_{mk}.csv",
            f"intraday_realtime_snapshot_{mk}.csv",
            f"intraday_quote_snapshot_{mk}.csv",
            f"current_price_{mk}.csv",
        ]
        if any(text.endswith(name) or f"/{name}" in text for name in allowed_names):
            return False

    legacy_tokens = (
        "intraday_realtime_snapshot-kang.csv",
        "intraday_quote_snapshot-kang.csv",
        "intraday_realtime_snapshot.csv",
        "intraday_quote_snapshot.csv",
        "quote_snapshot.csv",
        "mone_live_quote_cache.csv",
    )
    if any(token in text for token in legacy_tokens):
        return True
    if text.startswith("stockapp://") and any(token in text for token in ("snapshot", "quote", "current_price", "price")):
        return True
    return False


def _row_has_legacy_quote_source(row: dict[str, Any], market: str = "") -> bool:
    """Return True when a data row points back to an old StockApp quote source."""
    for key in (
        "priceSourceFile", "sourceFile", "source_file", "source",
        "price_source_file", "quote_source_file", "current_price_source_file",
    ):
        if _is_legacy_quote_source(row.get(key), market):
            return True
    return False


def _row_price_is_stale_legacy(row: dict[str, Any], market: str = "") -> bool:
    """Block stale KIS/StockApp quote rows before they appear in report APIs."""
    source_type = _safe_str(first_value(row, ["priceSourceType", "sourceType", "source_type", "quote_source"], "")).lower()
    status = _safe_str(first_value(row, ["priceDataStatus", "dataStatus", "status"], "")).upper()
    if _row_has_legacy_quote_source(row, market):
        return True
    if source_type in {"kis", "kis_snapshot", "quote_cache", "stockapp_snapshot"}:
        date_text = first_value(row, ["priceSourceDate", "priceTime", "updated_at", "sourceDate", "date", "일자"], "")
        if status == "STALE" or (date_text and not _date_is_today(date_text)):
            return True
    if source_type in {"local", "local_fallback"}:
        price = first_number(row, CURRENT_PRICE_ALIASES + ["currentPrice", "current_price", "last_price", "price"])
        # Keep real OHLC/local rows; remove only empty placeholders and stale explicit local quote rows.
        if status == "STALE" or price is None or price <= 0:
            return True
    return False


def _sanitize_legacy_quote_fields(row: dict[str, Any], market: str = "") -> dict[str, Any]:
    """Remove only stale quote fields while preserving the candidate/report row.

    v2 removed entire rows when they contained old KIS/local quote metadata.
    That fixed the STALE pollution, but it also removed useful KR candidates that
    can still be priced by OHLCV close.  This helper keeps the symbol, entry,
    stop/target, score and report context, while stripping the stale quote layer
    so normalize_security_row can fall back to today's valid KIS snapshot or
    OHLCV close.
    """
    if not isinstance(row, dict):
        return row
    if not _row_price_is_stale_legacy(row, market):
        return row
    clean = dict(row)
    quote_keys = {
        "currentPrice", "currentPriceText", "current_price", "last_price", "regularMarketPrice",
        "실시간현재가", "현재가", "quote_price", "quote_fallback_price",
        "priceSource", "current_price_source", "quote_source_label", "quote_source",
        "priceSourceType", "priceSourceFile", "priceSourceDate", "priceTime",
        "quote_source_file", "current_price_source_file", "intraday_updated_at",
        "flow_updated_at", "quote_time", "kis_quote_success", "quote_available",
        "quote_full_available", "intraday_data_available",
    }
    for key in list(clean.keys()):
        key_text = str(key)
        low = key_text.lower()
        if key_text in quote_keys or ("quote" in low and "score" not in low) or low.startswith("price"):
            clean.pop(key, None)
    clean["legacyQuoteIgnored"] = True
    clean["legacyQuoteIgnoredReason"] = "stale legacy/local quote fields removed; fallback to KIS/OHLCV"
    return clean




def _apply_price_candidate_to_normalized(normalized: dict[str, Any], candidate: dict[str, Any] | None, market: str) -> dict[str, Any]:
    """Apply a clean price candidate without dropping the report row.

    This is used when a row carried stale legacy quote metadata but the symbol
    can still be priced from the valid close/OHLCV source required for the
    current session.
    """
    if not candidate:
        return normalized
    price = _safe_float(candidate.get("price"))
    if price is None or price <= 0:
        return normalized
    patched = dict(normalized)
    patched["currentPrice"] = price
    patched["currentPriceText"] = format_price(price, market)
    patched["priceTime"] = first_value(candidate, ["priceTime", "priceSourceDate"], patched.get("priceTime", ""))
    patched["priceSource"] = first_value(candidate, ["priceSource"], patched.get("priceSource", ""))
    patched["priceSourceType"] = first_value(candidate, ["priceSourceType"], patched.get("priceSourceType", ""))
    patched["priceSourceFile"] = first_value(candidate, ["priceSourceFile"], patched.get("priceSourceFile", ""))
    patched["priceSourceDate"] = first_value(candidate, ["priceSourceDate", "priceTime"], patched.get("priceSourceDate", ""))
    patched["priceDataStatus"] = first_value(candidate, ["priceDataStatus"], patched.get("priceDataStatus", "NORMAL"))
    patched["priceBasis"] = first_value(candidate, ["priceBasis"], patched.get("priceBasis", "가격 기준 확인"))
    patched["priceSession"] = first_value(candidate, ["priceSession"], patched.get("priceSession", "unknown"))
    statuses = patched.get("statuses")
    if isinstance(statuses, dict):
        statuses = dict(statuses)
        statuses["price"] = patched["priceDataStatus"]
        patched["statuses"] = statuses
    return patched

def _max_date_key_from_rows(rows: list[dict[str, Any]]) -> str:
    keys: list[str] = []
    for row in rows:
        for field in ("sourceDate", "priceSourceDate", "priceTime", "updated_at", "created_at", "target_date", "date"):
            key = _date_key(row.get(field))
            if key:
                keys.append(key)
                break
    return max(keys) if keys else ""


def _intraday_item_is_fresh(item: dict[str, Any]) -> bool:
    status = str(item.get("priceDataStatus", "")).upper()
    if status != "INTRADAY":
        return False
    date_text = item.get("priceSourceDate") or item.get("priceTime") or item.get("sourceDate")
    return _date_is_today(date_text)


def _has_time_component(value: Any) -> bool:
    text = _safe_str(value)
    return bool(re.search(r"\d{1,2}:\d{2}", text))


def _date_is_older(candidate_date: Any, reference_date: Any) -> bool:
    candidate_key = _date_key(candidate_date)
    reference_key = _date_key(reference_date)
    if candidate_key and reference_key and candidate_key != reference_key:
        return candidate_key < reference_key
    if candidate_key and reference_key and candidate_key == reference_key:
        if _has_time_component(candidate_date) and _has_time_component(reference_date):
            candidate_dt = _datetime_key(candidate_date)
            reference_dt = _datetime_key(reference_date)
            return bool(candidate_dt and reference_dt and candidate_dt < reference_dt)
        return False
    candidate_dt = _datetime_key(candidate_date)
    reference_dt = _datetime_key(reference_date)
    return bool(candidate_dt and reference_dt and candidate_dt < reference_dt)


@lru_cache(maxsize=8)
def _latest_actual_close_map(market: str) -> dict[str, dict[str, Any]]:
    if market != "kr":
        return {}
    candidates = [
        DATA_DIR / "decision_system" / "actual_results.csv",
        DATA_DIR / "stockapp" / "actual_results.csv",
        DATA_DIR / "adjustment_performance_report.csv",
        REPORT_DIR / "mone_v36_final_prediction_validation_kr.csv",
    ]
    by_symbol: dict[str, dict[str, Any]] = {}
    for path in candidates:
        df = read_csv(path)
        if df.empty:
            continue
        symbol_col = _ohlcv_column(df, ["ticker", "symbol", "stock_code", "종목코드"])
        close_col = _ohlcv_column(df, ["actual_close", "actualClose", "실제종가", "actual close"])
        date_col = _ohlcv_column(df, ["target_date", "actual_result_date", "date", "예측대상일"])
        if not symbol_col or not close_col or not date_col:
            continue
        work = df.copy()
        work["_symbol"] = work[symbol_col].map(lambda v: normalize_symbol(v, market))
        work["_close"] = work[close_col].map(_safe_float)
        work["_date_key"] = work[date_col].map(_date_key)
        work = work.dropna(subset=["_close"])
        work = work[(work["_symbol"].astype(str) != "") & (work["_date_key"].astype(str) != "")]
        if work.empty:
            continue
        for _, row in work.sort_values("_date_key").iterrows():
            symbol = str(row["_symbol"])
            candidate = {
                "close": float(row["_close"]),
                "date": str(row["_date_key"]),
                "source": source_label(path),
            }
            prev = by_symbol.get(symbol)
            if not prev or str(candidate["date"]) > str(prev.get("date", "")):
                by_symbol[symbol] = candidate
    return by_symbol


@lru_cache(maxsize=1024)
def _latest_actual_close(symbol: str, market: str) -> dict[str, Any]:
    """Latest verified actual close from daily validation reports."""
    if market != "kr" or not symbol:
        return {}
    return dict(_latest_actual_close_map(market).get(normalize_symbol(symbol, market), {}))


def _price_status(source_date: str, price_date: str, runner_date: str, is_fallback: bool) -> str:
    if is_fallback:
        return "FALLBACK"
    if runner_date and source_date and _normalize_date_text(source_date) != _normalize_date_text(runner_date):
        return "STALE"
    if not price_date:
        return "PARTIAL"
    return "NORMAL"


def _confidence_value(row: dict[str, Any] | pd.Series) -> float:
    raw = first_number(row, ["신뢰도점수", "confidence_score", "confidence", "score", "risk_confidence_score"])
    if raw is None:
        return 55.0
    return _clamp(raw, 0, 100)


def _derive_price_levels(row: dict[str, Any] | pd.Series, market: str, current: float | None, entry: float | None, stop: float | None, target: float | None, symbol: str) -> tuple[float | None, float | None, float | None]:
    if current is None or current <= 0:
        return entry, stop, target
    stats = _ohlcv_stats(symbol, market) if symbol else {"volatility": 0.022}
    daily_vol = float(stats.get("volatility", 0.022) or 0.022)
    risk_pct = _clamp(daily_vol * 2.8, 0.045, 0.095)
    reward_pct = _clamp(risk_pct * 1.75, 0.075, 0.18)
    if entry is None:
        entry = current * (0.992 if market == "kr" else 0.995)
    if stop is None and entry:
        stop = entry * (1 - risk_pct)
    if target is None and entry:
        target = entry * (1 + reward_pct)
    return entry, stop, target


def _derived_probability_and_price(row: dict[str, Any] | pd.Series, market: str, symbol: str, current: float | None, entry: float | None) -> dict[str, Any]:
    if current is None or current <= 0:
        return {}
    stats = _ohlcv_stats(symbol, market) if symbol else {"avgReturn": 0.001, "volatility": 0.022, "rows": 0, "source": ""}
    avg_ret = float(stats.get("avgReturn", 0.001) or 0.001)
    vol = float(stats.get("volatility", 0.022) or 0.022)
    confidence = _confidence_value(row)
    confidence_edge = (confidence - 50) / 1000
    gap_penalty = 0.0
    if entry:
        gap = (current - entry) / entry
        gap_penalty = -max(0.0, gap - 0.02) * 0.10
    out: dict[str, Any] = {}
    for key, days in (("1d", 1), ("3d", 3), ("5d", 5), ("20d", 20)):
        existing_prob = first_value(row, [f"{days}일상승확률", f"prob_up_{days}d", f"prob{days}d", f"{days}d_probability", f"probability_{days}d"], "")
        existing_price = first_number(row, EXPECTED_PRICE_ALIASES.get(key, []))
        horizon_edge = avg_ret * days + confidence_edge * np.sqrt(days) + gap_penalty
        horizon_edge = _clamp(float(horizon_edge), -0.12, 0.28 if days >= 20 else 0.16)
        sigma = max(0.01, vol * np.sqrt(days))
        prob = _clamp(50 + (horizon_edge / sigma) * 10, 38, 74)
        expected = existing_price if existing_price is not None else current * (1 + horizon_edge)
        out[f"prob_{key}"] = existing_prob or _format_probability(prob)
        out[f"expected_{key}"] = expected
        out[f"expected_{key}_text"] = format_price(expected, market)
    out["predictionModelNote"] = "OHLCV·신뢰도·기준가거리 기반 추정" if stats.get("rows", 0) else "현재가·신뢰도 기반 임시 추정"
    return out


def _derive_open_close(row: dict[str, Any] | pd.Series, market: str, symbol: str, current: float | None) -> tuple[float | None, float | None]:
    explicit_open = first_number(row, ["예상시초가", "pred_open_mid", "pred_open", "expected_open", "premarket_price"])
    explicit_close = first_number(row, ["예상종가", "pred_close_mid", "pred_close", "expected_close"])
    if current is None or current <= 0:
        return explicit_open, explicit_close
    stats = _ohlcv_stats(symbol, market) if symbol else {"avgReturn": 0.001, "gapAvg": 0.0, "volatility": 0.022}
    gap_avg = float(stats.get("gapAvg", 0.0) or 0.0)
    avg_ret = float(stats.get("avgReturn", 0.001) or 0.001)
    confidence_edge = (_confidence_value(row) - 50) / 1800
    expected_open = explicit_open if explicit_open is not None else current * (1 + _clamp(gap_avg + confidence_edge, -0.04, 0.04))
    intraday_edge = _clamp(avg_ret * 0.75 + confidence_edge, -0.05, 0.06)
    expected_close = explicit_close if explicit_close is not None else expected_open * (1 + intraday_edge)
    return expected_open, expected_close




TRADE_MODE_SETTINGS: dict[str, dict[str, Any]] = {
    "conservative": {
        "label": "보수",
        "capital_kr": 1_000_000,
        "capital_us": 1_000,
        "buy_rule": "기준가 이하 또는 기준가 근처에서만 체결",
        "entry_tolerance_pct": 0.0,
        "hold_days": 5,
        "target_first": False,
        "slippage_pct": 0.003,
    },
    "balanced": {
        "label": "균형",
        "capital_kr": 1_000_000,
        "capital_us": 1_000,
        "buy_rule": "기준가 ±1% 이내면 체결",
        "entry_tolerance_pct": 0.01,
        "hold_days": 5,
        "target_first": False,
        "slippage_pct": 0.002,
    },
    "aggressive": {
        "label": "공격",
        "capital_kr": 1_000_000,
        "capital_us": 1_000,
        "buy_rule": "현재가 또는 예상 시초가 기준 체결",
        "entry_tolerance_pct": 0.025,
        "hold_days": 1,
        "target_first": False,
        "slippage_pct": 0.001,
    },
}


def _risk_reward_values(entry: float | None, stop: float | None, target: float | None) -> tuple[float | None, float | None, float | None]:
    if entry is None or stop is None or target is None or entry <= 0:
        return None, None, None
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0 or reward <= 0:
        return None, None, None
    return risk, reward, reward / risk


def _swing_grade(row: dict[str, Any] | pd.Series, current: float | None, entry: float | None, stop: float | None, target: float | None) -> str:
    risk, reward, rr = _risk_reward_values(entry, stop, target)
    if entry is None or current is None or rr is None:
        return "C"
    confidence = _confidence_value(row)
    gap = abs((current - entry) / entry) if entry else 1.0
    risk_pct = (risk / entry) if risk else 1.0
    if rr >= 1.55 and gap <= 0.035 and risk_pct <= 0.09 and confidence >= 54:
        return "A"
    if rr >= 1.20 and gap <= 0.08 and risk_pct <= 0.13 and confidence >= 48:
        return "B"
    return "C"


def _recommendation_modes(grade: str, current: float | None, entry: float | None, stop: float | None, target: float | None) -> list[str]:
    risk, reward, rr = _risk_reward_values(entry, stop, target)
    if entry is None or current is None or stop is None or target is None or rr is None:
        return []
    gap = (current - entry) / entry if entry else 0
    risk_pct = (risk / entry) if risk else 1.0
    modes: list[str] = []
    if grade == "A" and gap <= 0.035 and risk_pct <= 0.09 and rr >= 1.45:
        modes.append("conservative")
    if grade in {"A", "B"} and gap <= 0.08 and risk_pct <= 0.13 and rr >= 1.15:
        modes.append("balanced")
    if grade in {"A", "B", "C"} and gap <= 0.14 and risk_pct <= 0.18:
        modes.append("aggressive")
    return modes


def _trade_plan_for_mode(market: str, mode: str, current: float | None, entry: float | None, stop: float | None, target: float | None, expected_open: float | None = None) -> dict[str, Any]:
    settings = TRADE_MODE_SETTINGS.get(mode, TRADE_MODE_SETTINGS["balanced"])
    capital = float(settings["capital_us"] if market == "us" else settings["capital_kr"])
    if mode == "aggressive" and current:
        planned_entry = current
    else:
        planned_entry = entry or current
    if mode == "aggressive" and expected_open:
        planned_entry = min(planned_entry or expected_open, expected_open)
    if planned_entry is None or planned_entry <= 0 or stop is None or target is None:
        return {
            "mode": mode,
            "modeLabel": settings["label"],
            "status": "PRICE_LEVEL_SHORT",
            "summary": "기준가·손절가·목표가 산출 필요",
            "buyRule": settings["buy_rule"],
            "holdDays": settings["hold_days"],
        }
    shares = int(capital // planned_entry)
    if shares < 1:
        shares = 1
    invested = planned_entry * shares
    cash = max(0.0, capital - invested)
    loss_per_share = stop - planned_entry
    profit_per_share = target - planned_entry
    loss_total = loss_per_share * shares
    profit_total = profit_per_share * shares
    loss_pct = (loss_per_share / planned_entry) * 100
    profit_pct = (profit_per_share / planned_entry) * 100
    account_loss_pct = (loss_total / capital) * 100 if capital else 0
    account_profit_pct = (profit_total / capital) * 100 if capital else 0
    return {
        "mode": mode,
        "modeLabel": settings["label"],
        "status": "OK",
        "capital": capital,
        "capitalText": format_price(capital, market),
        "entry": planned_entry,
        "entryText": format_price(planned_entry, market),
        "shares": shares,
        "sharesText": f"{shares:,}주",
        "invested": invested,
        "investedText": format_price(invested, market),
        "cash": cash,
        "cashText": format_price(cash, market),
        "lossPct": loss_pct,
        "lossPctText": format_percent(loss_pct),
        "profitPct": profit_pct,
        "profitPctText": format_percent(profit_pct),
        "lossTotal": loss_total,
        "lossTotalText": format_signed_money(loss_total, market, "손실 산출 필요"),
        "profitTotal": profit_total,
        "profitTotalText": format_signed_money(profit_total, market, "이익 산출 필요"),
        "accountLossPct": account_loss_pct,
        "accountLossPctText": format_percent(account_loss_pct),
        "accountProfitPct": account_profit_pct,
        "accountProfitPctText": format_percent(account_profit_pct),
        "buyRule": settings["buy_rule"],
        "holdDays": settings["hold_days"],
        "slippagePct": settings["slippage_pct"],
        "sellRule": "목표가·손절가·보유기간 종료 중 먼저 발생한 조건으로 청산",
        "summary": f"{settings['label']} {format_price(capital, market)} 기준 {shares:,}주 · 손실 {format_signed_money(loss_total, market)} · 이익 {format_signed_money(profit_total, market)}",
    }


def _virtual_trade_plans(market: str, current: float | None, entry: float | None, stop: float | None, target: float | None, expected_open: float | None = None) -> dict[str, dict[str, Any]]:
    return {mode: _trade_plan_for_mode(market, mode, current, entry, stop, target, expected_open) for mode in ("conservative", "balanced", "aggressive")}

def _market_matches(row: dict[str, Any], market: str) -> bool:
    value = first_value(row, ["market", "시장"], "")
    lowered = value.lower()
    if value:
        if market == "kr":
            return lowered in {"kr", "korea", "한국주식", "국장", "kospi", "kosdaq"} or "한국" in value
        return lowered in {"us", "usa", "미국주식", "미장", "nas", "nys", "amex"} or "미국" in value

    symbol = first_value(row, SYMBOL_ALIASES + ["ticker", "종목코드"], "")
    symbol = str(symbol).strip().replace(".0", "")
    symbol = re.sub(r"[^A-Za-z0-9._-]", "", symbol)
    if re.fullmatch(r"\d{1,6}", symbol):
        return market == "kr"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,12}", symbol):
        return market == "us"
    return False


def _prediction_file_candidates(preferred: str) -> list[Path]:
    github_candidates = [REPO_ROOT / "predictions.csv"]
    stockapp_candidates = [DATA_DIR / "stockapp" / "predictions.csv"]
    for root in stockapp_roots():
        stockapp_candidates.extend([root / "predictions.csv", root / "data" / "predictions.csv"])
    candidates = stockapp_candidates + github_candidates if preferred == "stockapp_snapshot" else github_candidates + stockapp_candidates
    return _unique_paths([path for path in candidates if path.exists() and path.stat().st_size > 0])


def _read_predictions_from_path(path: Path, market: str | None = None) -> list[dict[str, Any]]:
    df = read_csv(path)
    rows = dataframe_records(df)
    if market is None:
        return rows
    return [row for row in rows if _market_matches(row, market)]


def read_predictions_csv(market: str | None = None) -> list[dict[str, Any]]:
    preferred = preferred_source_type(market or "kr")
    for path in _prediction_file_candidates(preferred):
        rows = _read_predictions_from_path(path, market)
        if rows:
            return rows
    return []


def read_primary_predictions(market: str) -> tuple[list[dict[str, Any]], str, str]:
    target_date = runner_target_date(market)
    preferred = preferred_source_type(market, target_date)
    for path in _prediction_file_candidates(preferred):
        source = source_label(path)
        rows = _read_predictions_from_path(path, market)
        if target_date:
            target_key = _normalize_date_text(target_date)
            matched = [row for row in rows if _normalize_date_text(first_value(row, ["target_date", "targetDate", "actual_date", "data_date"], "")) == target_key]
            rows = matched
        if not rows:
            continue
        fallback = _source_type_for_label(source, market, target_date) != preferred
        rows = _annotate_source_rows(rows, market, source, target_date, fallback=fallback)
        return rows, source, target_date
    return [], "", target_date


def _latest_records_by_symbol(rows: list[dict[str, Any]], market: str) -> dict[str, dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> str:
        return first_value(row, ["created_at", "target_date", "data_date", "updated_at"], "")

    out: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=sort_key, reverse=True):
        symbol = _row_symbol(row, market)
        if symbol and symbol not in out:
            out[symbol] = row
    return out


def _combine_symbol_maps(market: str) -> dict[str, dict[str, Any]]:
    maps: list[dict[str, dict[str, Any]]] = []
    for kind in ("symbol_snapshot", "position_cards", "action_cards", "pullback_cards", "risk_cards", "future_probability"):
        df, _ = read_report(kind, market)
        maps.append(_records_by_symbol(df, market))
    combined: dict[str, dict[str, Any]] = {}
    for symbol_map in maps:
        for symbol, row in symbol_map.items():
            combined[symbol] = _merge_alias_values(combined.get(symbol, {}), row) if symbol in combined else dict(row)
    return combined


def _format_optional_price(row: dict[str, Any], aliases: list[str], market: str, missing: str) -> str:
    value = first_number(row, aliases)
    return format_price(value, market) if value is not None else missing


def _display_value(row: dict[str, Any], aliases: list[str], missing: str) -> str:
    return first_value(row, aliases, missing)


def _metric_has_value(value: Any) -> bool:
    """True only for values that look usable in company/financial screens."""
    text = _safe_str(value).strip()
    if not text:
        return False
    missing_markers = ("데이터 없음", "연결 대기", "없음", "대기", "N/A", "nan", "None")
    return not any(marker.lower() in text.lower() for marker in missing_markers)


def _company_financial_quality(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"status": "MISSING", "filledRows": 0, "densityPct": 0, "note": "기업분석 행 없음"}
    metric_keys = ["eps", "per", "pbr", "roe", "revenue", "operatingIncome", "netIncome", "annualPerformance", "quarterlyPerformance"]
    filled_rows = 0
    total_slots = len(items) * len(metric_keys)
    filled_slots = 0
    for item in items:
        row_filled = 0
        for key in metric_keys:
            if _metric_has_value(item.get(key)):
                filled_slots += 1
                row_filled += 1
        if row_filled:
            filled_rows += 1
    density = round((filled_slots / total_slots) * 100, 1) if total_slots else 0
    if filled_rows == 0:
        status = "PARTIAL"
        note = "기업 행은 있으나 EPS/PER/PBR/매출 등 핵심 재무값 부족"
    elif density < 25:
        status = "PARTIAL"
        note = f"핵심 재무값 일부만 연결됨: {filled_rows}/{len(items)}행"
    else:
        status = "OK"
        note = f"핵심 재무값 연결: {filled_rows}/{len(items)}행"
    return {"status": status, "filledRows": filled_rows, "densityPct": density, "note": note}


def _clean_disclosure_title(title: Any, market: str) -> str:
    text = _safe_str(title).strip()
    upper = text.upper().replace("FORM ", "").strip()
    if market == "us":
        form_like = {"4", "144", "8-K", "10-K", "10-Q", "6-K", "S-1", "SD", "IRANNOTICE", "IRAN NOTICE"}
        if not text:
            return "SEC filing"
        if upper in form_like or re.fullmatch(r"\d{1,4}", upper):
            return f"SEC Form {upper}"
    if market == "kr" and (not text or re.fullmatch(r"\d+", text)):
        return "공시 제목 확인 필요"
    return text


def _direction_label(value: Any) -> str:
    text = _safe_str(value, "")
    if not text:
        return "검증 데이터 부족"
    if text.lower() in {"1", "true", "hit", "success", "성공"}:
        return "적중"
    if text.lower() in {"0", "false", "miss", "fail", "failure", "실패"}:
        return "불일치"
    return text


def _rate(rows: list[dict[str, Any]], aliases: list[str]) -> str:
    total = 0
    hits = 0
    for row in rows:
        value = first_value(row, aliases, "")
        if not value:
            continue
        normalized = value.lower()
        if normalized in {"대기", "pending"}:
            continue
        total += 1
        if normalized in {"1", "true", "hit", "success", "성공", "yes"}:
            hits += 1
    if not total:
        return "검증 데이터 부족"
    return f"{hits / total * 100:.1f}%"


def _report_group(path: Path) -> str:
    name = path.name.lower()
    if "latest" in name:
        return "latest"
    if name.startswith("mone_v36"):
        return "mone_v36"
    if name.startswith("v93"):
        return "v93"
    if name.startswith("v92"):
        return "v92"
    if name.startswith("v91"):
        return "v91"
    if "operational" in name:
        return "operational"
    if "portfolio" in name or "position" in name:
        return "portfolio"
    if "backtest" in name:
        return "backtest"
    return "other"


def _fallback_status_for_file(path: Path) -> str:
    match = re.match(r"(?:mone_v36|v\d+)_(.+)_(kr|us)\.csv$", path.name)
    if not match:
        return "fallback 대상 아님"
    suffix = f"{match.group(1)}_{match.group(2)}.csv"
    for version in ("mone_v36", "v93", "v92", "v91"):
        candidate = REPORT_DIR / f"{version}_{suffix}"
        if candidate.exists() and candidate.stat().st_size > 0 and rows_for(candidate) > 0:
            return f"{version} 사용 가능" if candidate == path else f"{version} fallback 가능"
    return "fallback 없음"


def _kst_now() -> datetime:
    """Return current time in Korea. Falls back safely if zoneinfo is unavailable."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _is_market_closed_now() -> bool:
    """주말이거나 국장·미장 모두 장외 시간인지 판단한다."""
    now = _kst_now()
    if now.weekday() >= 5:  # 토(5)/일(6)
        return True
    hhmm = now.hour * 100 + now.minute
    kr_open = 900 <= hhmm < 1530
    us_open = hhmm >= 2230 or hhmm < 500
    return not (kr_open or us_open)


def _days_since(date_key: str) -> int:
    """YYYYMMDD 형식 date_key로부터 오늘(KST)까지 경과 일수를 반환한다."""
    if len(date_key) < 8:
        return 9999
    try:
        d = datetime.strptime(date_key[:8], "%Y%m%d")
        return (_kst_now() - d).days
    except Exception:
        return 9999


def _has_kr_premarket_update_for_date(date_text: str) -> bool:
    """Return True only when next-day KR premarket data exists.

    Before the next KR premarket run is produced, the app should keep using the
    latest close-update price instead of treating the clock-only morning window
    as a new premarket basis.
    """
    ymd = re.sub(r"\D", "", str(date_text or ""))[:8]
    if not ymd:
        return False
    candidates: list[Path] = []
    for base in [REPORT_DIR, DATA_DIR / "stockapp", DATA_DIR / "decision_system"] + [root / "reports" for root in stockapp_roots()]:
        if not base.exists():
            continue
        patterns = [
            f"*premarket*kr*{ymd}*.csv",
            f"*kr*premarket*{ymd}*.csv",
            f"order_plan_kr_{ymd}_*.csv",
            f"*recommendations_kr*{ymd}*.csv",
        ]
        for pattern in patterns:
            candidates.extend(base.glob(pattern))
    for path in candidates:
        try:
            if path.exists() and path.stat().st_size > 0 and rows_for(path) > 0:
                return True
        except Exception:
            continue
    return False

def _market_price_phase(market: str, now: datetime | None = None) -> dict[str, Any]:
    """Business rule for the one price all screens should share.

    KR:
      - before regular session: previous OHLC close
      - during regular session: current/quote price
      - after close: today's OHLC/close update
    US (KST):
      - before regular session: morning/update snapshot
      - during regular session: current/quote price
      - after close: post-close update snapshot
    """
    now = now or _kst_now()
    minutes = now.hour * 60 + now.minute
    weekday = now.weekday()  # Mon=0
    if market == "kr":
        if weekday >= 5:
            phase = "kr_after_close"
        elif minutes < 9 * 60:
            # Clock time alone is not enough.  If the next-day KR premarket
            # prediction has not been generated yet, keep using the latest
            # after-close update from the previous trading day.
            phase = "kr_premarket" if _has_kr_premarket_update_for_date(now.strftime("%Y%m%d")) else "kr_after_close"
        elif minutes < 15 * 60 + 30:
            phase = "kr_intraday"
        else:
            phase = "kr_after_close"
        labels = {
            "kr_premarket": "국장 전 · 전일 OHLC 기준",
            "kr_intraday": "국장 장중 · 현재가 기준",
            "kr_after_close": "국장 마감 후 · 당일 마감 업데이트 기준",
        }
        return {"market": market, "phase": phase, "label": labels[phase], "isIntraday": phase.endswith("intraday")}

    # US regular session in Korea time. Use a broad DST-aware practical window.
    # March-November: 22:30-05:00 KST, otherwise 23:30-06:00 KST.
    is_dst_season = 3 <= now.month <= 11
    open_min = (22 * 60 + 30) if is_dst_season else (23 * 60 + 30)
    close_min = (5 * 60) if is_dst_season else (6 * 60)
    in_intraday = minutes >= open_min or minutes < close_min
    if in_intraday:
        phase = "us_intraday"
    else:
        # In KST daytime the US regular session has already closed.  Keep the
        # app on the post-close update until the evening pre-market/preview
        # job is expected to refresh the next-session plan.
        premarket_start_min = 21 * 60 + 50
        phase = "us_after_close" if minutes < premarket_start_min else "us_premarket"
    labels = {
        "us_premarket": "미장 전 · 오전 업데이트 기준",
        "us_intraday": "미장 장중 · 현재가 기준",
        "us_after_close": "미장 마감 후 · 업데이트 기준",
    }
    return {"market": market, "phase": phase, "label": labels[phase], "isIntraday": phase.endswith("intraday")}


def _price_candidate(
    price: float | None,
    time_text: Any,
    source: str,
    source_file: str,
    source_type: str,
    status: str,
    phase: dict[str, Any],
    priority: int,
) -> dict[str, Any] | None:
    if price is None or price <= 0:
        return None
    return {
        "price": float(price),
        "priceTime": _safe_str(time_text) or _safe_str(_kst_now().strftime("%Y-%m-%d %H:%M:%S")),
        "priceSource": source,
        "priceSourceFile": source_file,
        "priceSourceDate": _safe_str(time_text) or _safe_str(_kst_now().strftime("%Y-%m-%d %H:%M:%S")),
        "priceSourceType": source_type,
        "priceDataStatus": status,
        "priceBasis": phase.get("label", "가격 기준 확인"),
        "priceSession": phase.get("phase", "unknown"),
        "priority": priority,
    }


def _row_price_candidate(row: dict[str, Any], market: str, phase: dict[str, Any], source_file: str = "") -> dict[str, Any] | None:
    phase_key = str(phase.get("phase", ""))
    if market == "kr":
        if phase_key == "kr_premarket":
            aliases = ["prev_close", "basis_close", "ohlcv_close", "close", "종가", "current_price_at_prediction"]
            status = "PREVIOUS_CLOSE"
            source = "전일 OHLC close"
        elif phase_key == "kr_intraday":
            aliases = ["currentPrice", "current_price", "last_price", "regularMarketPrice", "실시간현재가", "현재가", "quote_fallback_price"]
            source_hint = str(source_file or first_value(row, ["priceSourceFile", "sourceFile", "source_file", "source"], "")).lower()
            current_like_source = any(token in source_hint for token in ("quote", "current", "intraday", "orderbook", "kis"))
            status = "INTRADAY" if current_like_source else "STALE"
            source = "장중 현재가" if current_like_source else "장중 현재가 미확인 · 참고가"
        else:
            aliases = ["actual_close", "close", "basis_close", "ohlcv_close", "종가", "final_price", "current_price_at_prediction"]
            status = "AFTER_CLOSE"
            source = "당일 OHLC close"
    else:
        if phase_key == "us_intraday":
            aliases = ["currentPrice", "current_price", "last_price", "regularMarketPrice", "실시간현재가", "현재가"]
            source_hint = str(source_file or first_value(row, ["priceSourceFile", "sourceFile", "source_file", "source"], "")).lower()
            current_like_source = any(token in source_hint for token in ("quote", "current", "intraday", "yfinance", "finnhub", "kis"))
            status = "INTRADAY" if current_like_source else "STALE"
            source = "미장 장중 현재가" if current_like_source else "미장 장중 현재가 미확인 · 참고가"
        elif phase_key == "us_after_close":
            aliases = ["actual_close", "close", "final_price", "current_price", "current_price_at_prediction", "basis_close", "last_price", "price"]
            status = "AFTER_CLOSE"
            source = "미장 마감 후 업데이트"
        else:
            aliases = ["current_price", "currentPrice", "current_price_at_prediction", "basis_close", "prev_close", "last_price", "price", "close"]
            status = "PREMARKET_SNAPSHOT"
            source = "미장 전 오전 업데이트"
    price = first_number(row, aliases)
    if price is None:
        return None
    time_text = first_value(row, STOCKAPP_PRICE_DATE_ALIASES + PRICE_TIME_ALIASES, "")
    if phase_key.endswith("intraday") and status == "INTRADAY" and not _date_is_today(time_text):
        status = "STALE"
        source = f"{source} · 오래된 캐시/스냅샷 참고가"
    source_text = first_value(row, ["priceSource", "current_price_source", "quote_source", "basis_source", "source"], source)
    return _price_candidate(price, time_text, source_text or source, source_file or first_value(row, ["priceSourceFile", "sourceFile", "source_file", "source"], ""), "row", status, phase, 30)


def _quote_price_candidate(symbol: str, market: str, phase: dict[str, Any]) -> dict[str, Any] | None:
    # Only use quote cache during regular trading session. Outside the session it may be stale.
    if not phase.get("isIntraday"):
        return None
    cached = cached_quote_for(symbol, market) if symbol else {}
    price = _safe_float(cached.get("currentPrice"))
    if not cached or not cached.get("ok") or price is None:
        return None
    time_text = cached.get("priceTime") or quote_cache().get("updatedAt", "")
    is_fresh = _date_is_today(time_text)
    return _price_candidate(
        price,
        time_text,
        cached.get("priceSource") or ("quote cache current price" if is_fresh else "stale quote cache reference"),
        source_label(QUOTE_CACHE_FILE),
        "quote_cache",
        "INTRADAY" if is_fresh else "STALE",
        phase,
        100 if is_fresh else 2,
    )



def _realtime_snapshot_price_candidate(symbol: str, market: str, phase: dict[str, Any]) -> dict[str, Any] | None:
    """Read KIS/current quote snapshot CSVs.

    KIS quote files are generated by GitHub Actions after/around market hours as
    well as during the session.  They should therefore be considered whenever
    they are from today, not only when the local clock is inside regular
    intraday hours.  Older snapshots remain STALE and lose to OHLCV/close data.
    """
    if not symbol:
        return None
    norm_symbol = normalize_symbol(symbol, market)
    paths: list[Path] = []
    # Only market-scoped KIS/current-price snapshots are valid quote sources.
    # Do not scan external StockApp roots or old common files here; those caused
    # stale rows such as stockapp://reports/intraday_realtime_snapshot-Kang.csv
    # to re-enter the app.
    base_paths = [REPORT_DIR, DATA_DIR]
    names = [
        f"kis_current_price_{market}.csv",
        f"intraday_realtime_snapshot_{market}.csv",
        f"intraday_quote_snapshot_{market}.csv",
        f"current_price_{market}.csv",
    ]
    for base in base_paths:
        for name in names:
            paths.append(base / name)
    best: dict[str, Any] | None = None
    for path in paths:
        if not path.exists() or path.stat().st_size <= 0:
            continue
        if _is_legacy_quote_source(source_label(path), market):
            continue
        df = read_csv(path)
        if df.empty:
            continue
        for raw in dataframe_records(df):
            row_symbol = normalize_symbol(first_value(raw, SYMBOL_ALIASES + ["symbol", "ticker", "code", "stock_code"]), market)
            if row_symbol != norm_symbol:
                continue
            price = first_number(raw, [
                "currentPrice", "current_price", "last_price", "regularMarketPrice", "실시간현재가", "현재가",
                "quote_price", "quote_fallback_price", "price", "last",
            ])
            if price is None or price <= 0:
                continue
            source_text = str(first_value(raw, [
                "priceSource", "current_price_source", "quote_source_label", "quote_source", "intraday_data_source",
                "flow_source", "source",
            ], "")).lower()
            success_text = " ".join(str(first_value(raw, [k], "")) for k in [
                "kis_quote_success", "quote_available", "quote_full_available", "intraday_data_available", "flow_available",
            ]).lower()
            file_hint = source_label(path).lower()
            row_source_hint = str(first_value(raw, ["priceSourceFile", "sourceFile", "source_file", "source"], "")).lower()
            if _is_legacy_quote_source(file_hint, market) or _is_legacy_quote_source(row_source_hint, market):
                continue
            is_current_like = any(token in (source_text + " " + success_text + " " + file_hint) for token in (
                "kis", "quote", "current", "intraday", "realtime", "yfinance", "finnhub"
            ))
            if not is_current_like:
                continue
            time_text = first_value(raw, [
                "priceSourceDate", "priceTime", "intraday_updated_at", "flow_updated_at", "updated_at", "quote_time", "date", "일자",
            ], _safe_str(path.stat().st_mtime))
            is_fresh = _date_is_today(time_text)
            if not is_fresh:
                continue
            phase_key = str(phase.get("phase", ""))
            raw_source_type = str(first_value(raw, ["priceSourceType", "source_type"], "")).lower()
            if "finnhub" in raw_source_type:
                source_type = "finnhub_fallback"
            elif "yfinance" in raw_source_type:
                source_type = "yfinance_fallback"
            elif "fallback" in raw_source_type:
                source_type = "quote_fallback"
            else:
                source_type = "kis_snapshot"

            if is_fresh and phase.get("isIntraday"):
                status = "INTRADAY"
                priority = 110
            elif is_fresh and phase_key.endswith("after_close"):
                status = "AFTER_CLOSE"
                priority = 108
            elif is_fresh and phase_key.endswith("premarket"):
                status = "PREMARKET_SNAPSHOT"
                priority = 106
            else:
                status = "STALE"
                priority = 3

            cand = _price_candidate(
                price,
                time_text,
                first_value(raw, ["priceSource", "current_price_source", "quote_source_label", "quote_source", "intraday_data_source"], "KIS/current quote snapshot" if is_fresh else "stale KIS/current snapshot reference"),
                source_label(path),
                source_type,
                status,
                phase,
                priority,
            )
            if cand and (best is None or _date_key(cand.get("priceSourceDate")) >= _date_key(best.get("priceSourceDate"))):
                best = cand
    return best

def _ohlcv_price_candidate(symbol: str, market: str, phase: dict[str, Any]) -> dict[str, Any] | None:
    stats = _ohlcv_stats(symbol, market) if symbol else {}
    close = _safe_float(stats.get("lastClose"))
    if close is None or close <= 0:
        return None
    phase_key = str(phase.get("phase", ""))
    if market == "kr":
        if phase_key == "kr_premarket":
            status = "PREVIOUS_CLOSE"
            priority = 90
        elif phase_key == "kr_after_close":
            status = "AFTER_CLOSE"
            priority = 90
        else:
            status = "STALE"
            priority = 5
    else:
        if phase_key == "us_after_close":
            status = "AFTER_CLOSE"
            priority = 85
        elif phase_key == "us_premarket":
            status = "PREMARKET_SNAPSHOT"
            priority = 20
        else:
            status = "STALE"
            priority = 5
    return _price_candidate(
        close,
        stats.get("lastDate") or "",
        f"OHLCV close · {stats.get('source', '')}".strip(" ·"),
        _safe_str(stats.get("source", "")),
        "ohlcv",
        status,
        phase,
        priority,
    )


def _allowed_price_statuses_for_phase(phase: dict[str, Any] | None) -> set[str]:
    phase_key = str((phase or {}).get("phase", ""))
    if phase_key == "kr_premarket":
        return {"PREVIOUS_CLOSE"}
    if phase_key == "kr_intraday":
        return {"INTRADAY"}
    if phase_key == "kr_after_close":
        return {"AFTER_CLOSE"}
    if phase_key == "us_premarket":
        return {"PREMARKET_SNAPSHOT", "PREVIOUS_CLOSE"}
    if phase_key == "us_intraday":
        return {"INTRADAY"}
    if phase_key == "us_after_close":
        return {"AFTER_CLOSE"}
    return {"NORMAL", "INTRADAY", "AFTER_CLOSE", "PREVIOUS_CLOSE", "PREMARKET_SNAPSHOT"}


def _mark_price_stale_for_phase(candidate: dict[str, Any], phase: dict[str, Any] | None) -> dict[str, Any]:
    marked = dict(candidate)
    phase_label = str((phase or {}).get("label", "가격 기준 확인"))
    phase_key = str((phase or {}).get("phase", "unknown"))
    if phase_key.endswith("intraday"):
        marked["priceDataStatus"] = "STALE"
        marked["priceBasis"] = f"{phase_label} · 현재가 미확인, 참고가"
    else:
        marked["priceDataStatus"] = "STALE"
        marked["priceBasis"] = f"{phase_label} · 기준 가격 미확인, 참고가"
    marked["priceSession"] = phase_key
    return marked


def _select_price_candidate(candidates: list[dict[str, Any] | None], reference_date: str = "", phase: dict[str, Any] | None = None) -> dict[str, Any] | None:
    valid = [c for c in candidates if c and _safe_float(c.get("price")) is not None]
    if not valid:
        return None
    if reference_date:
        fresh = [c for c in valid if not _date_is_older(c.get("priceSourceDate"), reference_date)]
        if fresh:
            valid = fresh
    allowed = _allowed_price_statuses_for_phase(phase)
    compatible = [c for c in valid if str(c.get("priceDataStatus", "")).upper() in allowed]
    if compatible:
        valid = compatible
        return sorted(valid, key=lambda c: (int(c.get("priority", 0)), _date_key(c.get("priceSourceDate", ""))), reverse=True)[0]
    best = sorted(valid, key=lambda c: (int(c.get("priority", 0)), _date_key(c.get("priceSourceDate", ""))), reverse=True)[0]
    return _mark_price_stale_for_phase(best, phase)


def _unified_price_for_row(
    row: dict[str, Any],
    market: str,
    symbol: str,
    source_date: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    phase = _market_price_phase(market)
    source_file = first_value(row, ["sourceFile", "source_file"], "")
    candidates: list[dict[str, Any] | None] = []
    existing = existing or {}
    candidates.append(_price_candidate(
        _safe_float(existing.get("price")),
        existing.get("priceTime") or existing.get("priceSourceDate"),
        existing.get("priceSource") or "기존 계산 가격",
        existing.get("priceSourceFile") or "",
        existing.get("priceSourceType") or "existing",
        existing.get("priceDataStatus") or "NORMAL",
        phase,
        20,
    ))
    candidates.append(_row_price_candidate(row, market, phase, source_file))
    candidates.append(_quote_price_candidate(symbol, market, phase))
    candidates.append(_realtime_snapshot_price_candidate(symbol, market, phase))
    candidates.append(_ohlcv_price_candidate(symbol, market, phase))
    stockapp_price = _stockapp_price_overlay(row, market, source_date)
    if stockapp_price:
        phase_key = str(phase.get("phase", ""))
        stockapp_source_file = first_value(stockapp_price, ["priceSourceFile"], "")
        source_hint = str(stockapp_source_file).lower()
        if phase.get("isIntraday"):
            is_realtime_like = any(token in source_hint for token in ("quote", "current", "intraday", "orderbook", "yfinance", "finnhub", "kis"))
            status = "INTRADAY" if is_realtime_like else "STALE"
            priority = 95 if is_realtime_like else 1
        elif market == "kr" and phase_key == "kr_premarket":
            status = "PREVIOUS_CLOSE"
            priority = 15 if "prediction" in source_hint else 65
        elif phase_key.endswith("after_close"):
            status = "AFTER_CLOSE"
            priority = 95 if any(token in source_hint for token in ("actual", "adjustment", "performance", "ohlcv", "close")) else 60
        else:
            status = "PREMARKET_SNAPSHOT"
            priority = 80
        candidates.append(_price_candidate(
            _safe_float(stockapp_price.get("price")),
            first_value(stockapp_price, ["priceTime", "priceSourceDate"], ""),
            first_value(stockapp_price, ["priceSource"], "StockApp price/update"),
            stockapp_source_file,
            "stockapp_snapshot",
            status,
            phase,
            priority,
        ))
    return _select_price_candidate(candidates, source_date, phase)


def normalize_security_row(row: dict[str, Any] | pd.Series, market: str) -> dict[str, Any]:
    row_dict = dict(row)
    symbol = normalize_symbol(first_value(row_dict, SYMBOL_ALIASES), market)
    name = first_value(row_dict, NAME_ALIASES, symbol or "이름 없음")
    ohlc_close = first_number(row_dict, KR_OHLC_CLOSE_ALIASES) if market == "kr" else None
    ohlc_stats = _ohlcv_stats(symbol, market) if market == "kr" and symbol else {}
    actual_close = _latest_actual_close(symbol, market) if market == "kr" and symbol else {}
    if actual_close:
        actual_date = str(actual_close.get("date") or "")
        ohlc_date = _date_key(ohlc_stats.get("lastDate") or first_value(row_dict, ["basis_ohlc_date", "ohlcv_date", "date", "일자"], ""))
        if actual_date and (not ohlc_date or actual_date >= ohlc_date):
            close_value = _safe_float(actual_close.get("close"))
            if close_value is not None and close_value > 0:
                ohlc_close = close_value
                ohlc_stats = {
                    **ohlc_stats,
                    "lastClose": close_value,
                    "lastDate": actual_date,
                    "source": actual_close.get("source", "") or ohlc_stats.get("source", ""),
                }
    if ohlc_close is None and int(ohlc_stats.get("rows", 0) or 0) > 0:
        stats_close = _safe_float(ohlc_stats.get("lastClose"))
        if stats_close is not None and stats_close > 0:
            ohlc_close = stats_close
    current_price = ohlc_close if ohlc_close is not None else first_number(row_dict, CURRENT_PRICE_ALIASES)
    ohlc_source = str(ohlc_stats.get("source") or "")
    price_time = (str(ohlc_stats.get("lastDate") or "") or first_value(row_dict, ["updated_at", "가격기준시각", "ohlcv_date", "date", "일자"], "OHLCV 최신 종가")) if ohlc_close is not None else first_value(row_dict, PRICE_TIME_ALIASES, "현재가 기준시각 없음")
    price_source = f"OHLCV 종가{f' · {ohlc_source}' if ohlc_source else ''}" if ohlc_close is not None else first_value(row_dict, PRICE_SOURCE_ALIASES, "가격출처 없음")
    data_status = "OHLCV 종가 반영" if ohlc_close is not None else first_value(row_dict, DATA_STATUS_ALIASES, "상태 없음")
    runner_date = runner_target_date(market)
    source_file = first_value(row_dict, ["sourceFile", "source_file"], "")
    source_date = first_value(row_dict, ["sourceDate"], _row_source_date(row_dict))
    source_type = _canonical_source_type(first_value(row_dict, ["sourceType"], _source_type_for_label(source_file, market, source_date)))
    source_type = _effective_source_type(source_type, preferred_source_type(market, source_date or runner_date), bool(row_dict.get("isFallback")))
    is_fallback = bool(row_dict.get("isFallback")) or source_type in {"local_fallback", "stale"}
    source_text = first_value(row_dict, ["priceSourceType", "quote_source", "current_price_source", "priceSource"], "").lower()
    kis_price = first_number(row_dict, ["current_price", "last_price"]) if "kis" in source_text else None
    price_source_type = "local"
    price_source_file = first_value(row_dict, ["priceSourceFile", "source_file", "source"], "")
    price_source_date = price_time
    if kis_price is not None:
        current_price = kis_price
        price_time = first_value(row_dict, ["priceSourceDate", "updated_at", "quote_time", "price_time"], price_time)
        price_source = first_value(row_dict, ["current_price_source", "quote_source", "quote_source_label"], "KIS current price")
        price_source_type = "kis"
        price_source_file = first_value(row_dict, ["priceSourceFile"], source_label(QUOTE_CACHE_FILE))
        price_source_date = price_time
    elif ohlc_close is not None:
        price_source_type = "github" if ohlc_source else "local"
        price_source_file = ohlc_source
        price_source_date = price_time
        price_source = f"OHLCV close{f' · {ohlc_source}' if ohlc_source else ''}"
    unified_price = _unified_price_for_row(row_dict, market, symbol, source_date, {
        "price": current_price,
        "priceTime": price_time,
        "priceSource": price_source,
        "priceSourceFile": price_source_file,
        "priceSourceDate": price_source_date,
        "priceSourceType": price_source_type,
        "priceDataStatus": "NORMAL",
    })
    price_basis = "가격 기준 확인"
    price_session = "unknown"
    if unified_price:
        current_price = _safe_float(unified_price.get("price"))
        price_time = first_value(unified_price, ["priceTime", "priceSourceDate"], price_time)
        price_source = first_value(unified_price, ["priceSource"], price_source)
        price_source_type = first_value(unified_price, ["priceSourceType"], price_source_type)
        price_source_file = first_value(unified_price, ["priceSourceFile"], price_source_file)
        price_source_date = first_value(unified_price, ["priceSourceDate", "priceTime"], price_source_date)
        price_basis = first_value(unified_price, ["priceBasis"], price_basis)
        price_session = first_value(unified_price, ["priceSession"], price_session)
        price_data_status = first_value(unified_price, ["priceDataStatus"], "NORMAL")
    else:
        price_data_status = _price_status(source_date, price_source_date, runner_date, is_fallback)
    if current_price is None:
        price_data_status = "NO_PRICE"
    if source_date and price_source_date and _date_is_older(price_source_date, source_date):
        # A row can be generated today while its valid price basis is the most
        # recent OHLCV close from the previous/closed session.  v3 treated that
        # as STALE and removed useful KR report rows after legacy quote fields
        # were stripped.  Keep OHLCV/close references for premarket and
        # after-close phases; still mark quote/current-price rows stale when old.
        phase_key_for_staleness = str(_market_price_phase(market).get("phase", ""))
        price_type_for_staleness = _safe_str(price_source_type).lower()
        price_hint_for_staleness = " ".join([
            _safe_str(price_source),
            _safe_str(price_source_file),
            _safe_str(price_basis),
        ]).lower()
        close_like_reference = (
            price_type_for_staleness in {"ohlcv", "github"}
            or "ohlcv" in price_hint_for_staleness
            or "close" in price_hint_for_staleness
            or "종가" in price_hint_for_staleness
        )
        close_phase = phase_key_for_staleness in {
            "kr_premarket", "kr_after_close", "us_premarket", "us_after_close"
        }
        if not (close_like_reference and close_phase):
            price_data_status = "STALE"
    raw_data_status = first_value(row_dict, DATA_STATUS_ALIASES, "")
    if source_type in {"stockapp_snapshot", "github_actions"} and raw_data_status.upper() not in {"STALE", "PARTIAL", "NO_DATA", "MISSING", "FALLBACK"}:
        base_data_status = "NORMAL"
    else:
        base_data_status = raw_data_status or ("NORMAL" if source_type in {"stockapp_snapshot", "github_actions"} else "")
    data_status = _source_status(source_type, base_data_status or price_data_status)
    entry = first_number(row_dict, ENTRY_ALIASES)
    stop = first_number(row_dict, STOP_ALIASES)
    target = first_number(row_dict, TARGET_ALIASES)
    entry, stop, target = _derive_price_levels(row_dict, market, current_price, entry, stop, target, symbol)
    prediction_fields = _derived_probability_and_price(row_dict, market, symbol, current_price, entry)
    expected_open, expected_close = _derive_open_close(row_dict, market, symbol, current_price)
    swing_grade = _swing_grade(row_dict, current_price, entry, stop, target)
    recommendation_modes = _recommendation_modes(swing_grade, current_price, entry, stop, target)
    virtual_plans = _virtual_trade_plans(market, current_price, entry, stop, target, expected_open)
    scores = {
        "supply": first_value(row_dict, SUPPLY_SCORE_ALIASES, "수급 데이터 없음"),
        "earnings": first_value(row_dict, EARNINGS_SCORE_ALIASES, "재무 데이터 없음"),
        "valuation": first_value(row_dict, VALUATION_SCORE_ALIASES, "재무 데이터 없음"),
        "chart": first_value(row_dict, CHART_SCORE_ALIASES, "차트 데이터 부족"),
    }
    statuses = {
        "data": first_value(row_dict, ["data_status"], "상태 없음"),
        "price": price_data_status,
        "earnings": first_value(row_dict, ["earnings_data_status", "실적상태"], "재무 데이터 없음"),
        "valuation": first_value(row_dict, ["valuation_data_status", "밸류상태"], "재무 데이터 없음"),
        "flow": first_value(row_dict, ["flow_data_status", "수급상태"], "수급 데이터 없음"),
    }
    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "marketLabel": _market_label(market),
        "currentPrice": current_price,
        "currentPriceText": format_price(current_price, market) if current_price is not None else "현재가 없음",
        "priceTime": price_time,
        "priceSource": price_source,
        "sourceType": source_type,
        "sourceFile": source_file,
        "sourceDate": source_date,
        "priceSourceType": price_source_type,
        "priceSourceFile": price_source_file,
        "priceSourceDate": price_source_date,
        "priceDataStatus": price_data_status,
        "priceBasis": price_basis,
        "priceSession": price_session,
        "dataStatus": data_status,
        "isFallback": is_fallback,
        "entry": entry,
        "entryText": format_price(entry, market) if entry is not None else "기준가 산출 필요",
        "stop": stop,
        "stopText": format_price(stop, market) if stop is not None else "손절가 산출 필요",
        "target": target,
        "targetText": format_price(target, market) if target is not None else "목표가 산출 필요",
        "prob1d": prediction_fields.get("prob_1d", "확률 산출 필요"),
        "prob3d": prediction_fields.get("prob_3d", "확률 산출 필요"),
        "prob5d": prediction_fields.get("prob_5d", "확률 산출 필요"),
        "prob20d": prediction_fields.get("prob_20d", "확률 산출 필요"),
        "probShort": prediction_fields.get("prob_1d", "확률 산출 필요"),
        "probSwing": prediction_fields.get("prob_5d", "확률 산출 필요"),
        "probMid": prediction_fields.get("prob_20d", "확률 산출 필요"),
        "expectedPrice1dText": prediction_fields.get("expected_1d_text", "예상가 산출 필요"),
        "expectedPrice3dText": prediction_fields.get("expected_3d_text", "예상가 산출 필요"),
        "expectedPrice5dText": prediction_fields.get("expected_5d_text", "예상가 산출 필요"),
        "expectedPrice20dText": prediction_fields.get("expected_20d_text", "예상가 산출 필요"),
        "expectedPriceShortText": prediction_fields.get("expected_1d_text", "예상가 산출 필요"),
        "expectedPriceSwingText": prediction_fields.get("expected_5d_text", "예상가 산출 필요"),
        "expectedPriceMidText": prediction_fields.get("expected_20d_text", "예상가 산출 필요"),
        "expectedOpenText": format_price(expected_open, market) if expected_open is not None else "예상 시초가 산출 필요",
        "expectedCloseText": format_price(expected_close, market) if expected_close is not None else "예상 종가 산출 필요",
        "swingGrade": f"스윙 {swing_grade}군",
        "swingGradeCode": swing_grade,
        "recommendationModes": recommendation_modes,
        "recommendationModeText": " / ".join(TRADE_MODE_SETTINGS[m]["label"] for m in recommendation_modes) if recommendation_modes else "추천 모드 산출 필요",
        "virtualPlans": virtual_plans,
        "predictionModelNote": prediction_fields.get("predictionModelNote", "예측 산출 대기"),
        "scores": scores,
        "statuses": statuses,
        "raw": row_dict,
    }




# -----------------------------------------------------------------------------
# v3.5.11: StockApp raw-data ingestion + MONE-owned classification
# -----------------------------------------------------------------------------
# StockApp is treated as a DATA FEED only. We intentionally do not copy its
# final labels such as "관망 우위", "매수금지", or "관망/제외" into MONE's
# recommendation buckets. Those labels are kept as risk context, while MONE
# recalculates opportunity score, entry score, and timing bucket with its own
# rules: today entry / wait for pullback / next entry / caution.

STOCKAPP_RAW_DATA_NOTE = "StockApp 원본 데이터 수신 후 MONE 성향·진입타이밍 기준으로 재분류"


def _latest_existing_path(paths: list[Path]) -> Path | None:
    candidates = [p for p in paths if p.exists() and p.is_file() and p.stat().st_size > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _stockapp_order_plan_path(market: str) -> Path | None:
    mk = "kr" if market == "kr" else "us"
    paths: list[Path] = [
        REPORT_DIR / f"latest_{mk}_order_plan.csv",
        DATA_DIR / "stockapp" / f"latest_{mk}_order_plan.csv",
        DATA_DIR / "decision_system" / f"latest_{mk}_order_plan.csv",
    ]
    for root in stockapp_roots():
        paths.extend([
            root / "reports" / f"latest_{mk}_order_plan.csv",
            root / "data" / f"latest_{mk}_order_plan.csv",
            root / f"latest_{mk}_order_plan.csv",
        ])
    # If a dated file is newer than latest_*.csv, use the newest dated one.
    for base in [REPORT_DIR, DATA_DIR / "stockapp"] + [root / "reports" for root in stockapp_roots()]:
        if base.exists():
            paths.extend(sorted(base.glob(f"order_plan_{mk}_*.csv")))
    return _latest_existing_path(paths)


def _stockapp_result_path(market: str) -> Path | None:
    mk = "kr" if market == "kr" else "us"
    paths: list[Path] = [
        REPORT_DIR / f"latest_{mk}_result.json",
        DATA_DIR / "stockapp" / f"latest_{mk}_result.json",
    ]
    for root in stockapp_roots():
        paths.extend([root / "reports" / f"latest_{mk}_result.json", root / "data" / f"latest_{mk}_result.json"])
    return _latest_existing_path(paths)


def _stockapp_report_path(market: str, file_name: str) -> Path | None:
    mk = "kr" if market == "kr" else "us"
    names = [file_name.format(market=mk)]
    paths: list[Path] = []
    for name in names:
        paths.extend([REPORT_DIR / name, DATA_DIR / "stockapp" / name])
        for root in stockapp_roots():
            paths.extend([root / name, root / "reports" / name, root / "data" / name])
    return _latest_existing_path(paths)


def stockapp_report_rows(market: str, file_name: str) -> tuple[list[dict[str, Any]], str]:
    path = _stockapp_report_path(market, file_name)
    if path is None:
        return [], ""
    rows = dataframe_records(read_csv(path))
    source = source_label(path)
    source_date = file_mtime(path)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        row = _sanitize_legacy_quote_fields(dict(row), market)
        if not _market_matches(row, market):
            market_text = first_value(row, ["market", "시장"], "")
            if market_text:
                continue
        merged = dict(row)
        merged.setdefault("sourceType", _source_type_for_label(source, market, source_date))
        merged.setdefault("sourceFile", source)
        merged.setdefault("sourceDate", source_date)
        filtered.append(merged)
    return filtered, source


def _stockapp_order_plan_rows(market: str) -> tuple[list[dict[str, Any]], str]:
    path = _stockapp_order_plan_path(market)
    if path is None:
        return [], ""
    rows = dataframe_records(read_csv(path))
    source = source_label(path)
    source_date = file_mtime(path)
    for row in rows:
        row["sourceType"] = "stockapp_snapshot"
        row["sourceFile"] = source
        row["sourceDate"] = source_date
        row["isFallback"] = False
    return rows, source


def _stockapp_price_file_candidates(market: str) -> list[Path]:
    paths: list[Path] = []
    if market == "kr":
        names = (
            "actual_results.csv",
            "stockapp_close_update_kr.csv",
            "latest_kr_performance_summary.csv",
            "adjustment_performance_report.csv",
            "operation_health_kr.csv",
        )
        glob_patterns = ("order_plan_kr_*.csv", "*kr*price*.csv", "*kr*quote*.csv")
    else:
        names = (
            "actual_results.csv",
            "latest_us_performance_summary.csv",
            "adjustment_performance_report.csv",
            "operation_health_us.csv",
            "v93_confidence_cards_us.csv",
            "v93_symbol_snapshot_us.csv",
            "v93_position_cards_us.csv",
            "v92_confidence_cards_us.csv",
            "v92_symbol_snapshot_us.csv",
            "v92_position_cards_us.csv",
            "stockapp_company_integrated_us.csv",
            "mone_v36_company_integrated_us.csv",
        )
        glob_patterns = ("order_plan_us_*.csv", "*us*price*.csv", "*us*quote*.csv", "*symbol_snapshot_us.csv", "*confidence_cards_us.csv")
    for name in names:
        path = _stockapp_report_path(market, name)
        if path is not None:
            paths.append(path)
        # GitHub reports may not live in StockApp folders.
        direct_report = REPORT_DIR / name
        direct_data = DATA_DIR / name
        for direct in (direct_report, direct_data, DATA_DIR / "stockapp" / name, DATA_DIR / "decision_system" / name):
            if direct.exists():
                paths.append(direct)
    order_path = _stockapp_order_plan_path(market)
    if order_path is not None:
        paths.append(order_path)
    for base in (REPORT_DIR, DATA_DIR, DATA_DIR / "stockapp", DATA_DIR / "decision_system"):
        if base.exists():
            for pattern in glob_patterns:
                paths.extend(sorted(base.glob(pattern)))
    for root in stockapp_roots():
        for base in (root / "reports", root / "data", root):
            if base.exists():
                for pattern in glob_patterns:
                    paths.extend(sorted(base.glob(pattern)))
                for name in names:
                    for direct in (base / name, base / "reports" / name, base / "data" / name):
                        if direct.exists():
                            paths.append(direct)
    return _unique_paths([p for p in paths if p.exists() and p.suffix.lower() == ".csv"])


def _stockapp_price_candidate_from_row(
    row: dict[str, Any],
    market: str,
    source: str,
    file_time: str,
    reference_date: Any = "",
) -> dict[str, Any] | None:
    symbol = _row_symbol(row, market)
    if not _symbol_belongs_to_market(symbol, market):
        return None
    if _is_legacy_quote_source(source, market) or _is_legacy_quote_source(first_value(row, ["priceSourceFile", "sourceFile", "source_file", "source"], ""), market):
        return None
    price = first_number(row, STOCKAPP_PRICE_ALIASES)
    if price is None or price <= 0:
        return None
    row_date = first_value(row, STOCKAPP_PRICE_DATE_ALIASES, "") or file_time
    price_date = first_value(row, ["created_at", "report_generated_at", "updated_at"], "") or row_date or file_time
    if reference_date and price_date and _date_is_older(price_date, reference_date):
        return None
    return {
        "symbol": symbol,
        "price": price,
        "priceTime": price_date or row_date or file_time,
        "priceSource": "StockApp close/update",
        "priceSourceFile": source,
        "priceSourceDate": price_date or row_date or file_time,
        "fileTime": file_time,
    }


@lru_cache(maxsize=16)
def _stockapp_latest_price_map(market: str, reference_date_key: str = "") -> dict[str, dict[str, Any]]:
    if market != "kr":
        return {}
    candidates: dict[str, dict[str, Any]] = {}
    for path in sorted(_stockapp_price_file_candidates(market), key=lambda p: file_mtime(p), reverse=True):
        source = source_label(path)
        file_time = file_mtime(path)
        df = read_csv(path)
        if df.empty:
            continue
        for row in dataframe_records(df):
            if not _market_matches(row, market):
                market_text = first_value(row, ["market", "시장"], "")
                if market_text:
                    continue
            candidate = _stockapp_price_candidate_from_row(row, market, source, file_time, reference_date_key)
            if not candidate:
                continue
            symbol = str(candidate["symbol"])
            prev = candidates.get(symbol)
            prev_time = first_value(prev or {}, ["priceSourceDate", "fileTime"], "")
            candidate_time = first_value(candidate, ["priceSourceDate", "fileTime"], "")
            if not prev or _date_is_older(prev_time, candidate_time):
                candidates[symbol] = candidate
    return candidates


def _stockapp_price_overlay(row: dict[str, Any], market: str, source_date: str) -> dict[str, Any] | None:
    source_file = first_value(row, ["sourceFile", "source_file"], "")
    if _row_price_is_stale_legacy(row, market) or _is_legacy_quote_source(source_file, market):
        return None
    source_type = _canonical_source_type(first_value(row, ["sourceType"], _source_type_for_label(source_file, market, source_date)))
    # KR handoff snapshots should stay strict. US v93/v92 GitHub outputs are also valid price snapshots.
    if market == "kr" and source_type != "stockapp_snapshot" and not source_file.startswith("stockapp://"):
        return None
    row_candidate = _stockapp_price_candidate_from_row(row, market, source_file, source_date, source_date)
    symbol = _row_symbol(row, market)
    fallback = _stockapp_latest_price_map(market, _normalize_date_text(source_date)).get(symbol, {})
    if row_candidate and not _date_is_older(row_candidate.get("priceSourceDate"), source_date):
        return row_candidate
    return dict(fallback) if fallback else None


def _text_has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _risk_context_text(row: dict[str, Any]) -> str:
    parts = [
        first_value(row, ["주의사유", "risk_reason", "risk_warning_flags", "invalidation_condition"], ""),
        first_value(row, ["금지사유", "no_buy_reasons", "no_buy_market_reason"], ""),
        first_value(row, ["실전판정이유", "행동이유", "risk_decision_reasons"], ""),
        first_value(row, ["event_label", "event_learning_bucket", "earnings_event_timing"], ""),
    ]
    return " | ".join(p for p in parts if p)


def _score_from_label(text: str, positive_tokens: tuple[str, ...], negative_tokens: tuple[str, ...]) -> float:
    if not text:
        return 0.0
    score = 0.0
    for token in positive_tokens:
        if token in text:
            score += 7.0
    for token in negative_tokens:
        if token in text:
            score -= 7.0
    return score


def _mone_classifier_scores(row: dict[str, Any], market: str) -> dict[str, Any]:
    symbol = _row_symbol(row, market)
    current = first_number(row, CURRENT_PRICE_ALIASES)
    entry = first_number(row, ENTRY_ALIASES)
    stop = first_number(row, STOP_ALIASES)
    target = first_number(row, TARGET_ALIASES)
    current = current or first_number(row, ["basis_close", "prev_close", "current_price_at_prediction"])
    entry, stop, target = _derive_price_levels(row, market, current, entry, stop, target, symbol)
    risk, reward, rr_derived = _risk_reward_values(entry, stop, target)
    rr = first_number(row, ["손익비", "risk_reward_ratio", "rr", "rr1"]) or rr_derived or 0.0
    trade_fit = first_number(row, ["매매적합도", "trade_fit_score"]) or 0.0
    ensemble = first_number(row, ["앙상블추정점수", "ensemble_score", "purpose_score_after_disclosure"]) or 0.0
    quality = first_number(row, ["품질점수", "quality_score", "prediction_quality_score"]) or 0.0
    confidence = first_number(row, ["보정신뢰도", "confidence_score", "risk_confidence_score"]) or 50.0
    supply_text = first_value(row, ["수급", "supply_label", "supply_summary", "foreign_institution_score"], "")
    fundamental_text = first_value(row, ["재무", "fundamental_label", "fundamental_summary"], "")
    risk_text = _risk_context_text(row)
    no_buy_raw = first_value(row, ["매수금지", "no_buy_filter_applied"], "").lower()

    supply_bonus = _score_from_label(supply_text, ("우호", "순매수", "동시 순매수", "강함", "양호"), ("약함", "순매도", "중립/확인"))
    fundamental_bonus = _score_from_label(fundamental_text, ("우호", "개선", "저평가", "양호", "성장"), ("제한", "부족", "악화", "위험"))
    event_penalty = 0.0
    if _text_has_any(risk_text, ("대형 이벤트", "매크로 고변동", "이벤트·매크로", "FOMC", "CPI", "실적발표", "상장", "재료 소멸")):
        event_penalty += 12.0
    if _text_has_any(risk_text, ("주봉 강한 하락", "강한 하락", "방향 적중률 낮음", "가상매매 평균 -")):
        event_penalty += 10.0
    if no_buy_raw in {"true", "1", "y", "yes"}:
        # StockApp's no-buy flag is treated as a risk input only, not as a bucket override.
        event_penalty += 8.0
    if _text_has_any(risk_text, ("앙상블 약함", "신규매수 금지", "주의사유 존재")):
        event_penalty += 8.0

    rr_component = _clamp(rr, 0, 3.5) * 9.0
    opportunity = 38.0 + rr_component + _clamp(trade_fit, -20, 60) * 0.35 + _clamp(ensemble, -50, 100) * 0.22 + _clamp(confidence - 50, -50, 50) * 0.18 + supply_bonus + fundamental_bonus - event_penalty * 0.45

    gap = None
    if current and entry:
        gap = (current - entry) / entry
    risk_pct = None
    if entry and stop:
        risk_pct = abs(entry - stop) / entry
    entry_score = 50.0
    if gap is not None:
        abs_gap = abs(gap)
        if abs_gap <= 0.015:
            entry_score += 24.0
        elif abs_gap <= 0.035:
            entry_score += 16.0
        elif gap > 0.035:
            entry_score -= min(30.0, gap * 250)
        elif gap < -0.035:
            entry_score += 7.0
    else:
        entry_score -= 10.0
    if rr >= 1.8:
        entry_score += 12.0
    elif rr >= 1.2:
        entry_score += 6.0
    else:
        entry_score -= 10.0
    if risk_pct is not None:
        if risk_pct <= 0.07:
            entry_score += 8.0
        elif risk_pct >= 0.14:
            entry_score -= 12.0
    entry_score -= event_penalty * 0.45

    opportunity = round(_clamp(opportunity, 0, 100), 1)
    entry_score = round(_clamp(entry_score, 0, 100), 1)
    risk_score = round(_clamp(event_penalty + max(0.0, 45.0 - opportunity) * 0.45 + (15.0 if rr and rr < 1.0 else 0.0), 0, 100), 1)

    # ── Extended sub-scores (V2 7-factor) ────────────────────────────────────
    # rrScore: RR ratio → 0-100 (RR 1.5=33, 2.0=44, 3.0=67, 4.5=100)
    rr_score = round(_clamp(rr * 22.2, 0, 100), 1)

    # momentumScore: trade_fit + ensemble as momentum proxy
    momentum_raw = 50.0 + _clamp(trade_fit, -30, 60) * 0.40 + _clamp(ensemble, -50, 100) * 0.20
    momentum_score = round(_clamp(momentum_raw, 0, 100), 1)

    # qualityScore: quality field + fundamental + supply/demand
    quality_raw = 50.0 + _clamp(quality, -50, 100) * 0.30 + fundamental_bonus * 2.5 + supply_bonus * 2.0
    quality_score = round(_clamp(quality_raw, 0, 100), 1)

    # newsRiskPenalty: event_penalty severity → 0-100 (higher = more dangerous)
    news_risk_penalty = round(_clamp(event_penalty * 1.8, 0, 100), 1)

    return {
        "symbol": symbol,
        "current": current,
        "entry": entry,
        "stop": stop,
        "target": target,
        "rr": rr,
        "gap": gap,
        "riskPct": risk_pct,
        "opportunityScore": opportunity,
        "upsideScore": opportunity,       # alias: same value, explicit name
        "entryScore": entry_score,
        "riskScore": risk_score,
        "rrScore": rr_score,
        "momentumScore": momentum_score,
        "qualityScore": quality_score,
        "newsRiskPenalty": news_risk_penalty,
        "riskText": risk_text,
        "supplyText": supply_text,
        "fundamentalText": fundamental_text,
    }


def _mone_timing_bucket(row: dict[str, Any], market: str) -> str:
    s = _mone_classifier_scores(row, market)
    opportunity = float(s["opportunityScore"])
    entry_score = float(s["entryScore"])
    risk_score = float(s["riskScore"])
    gap = s.get("gap")
    rr = float(s.get("rr") or 0)
    supply_text = str(s.get("supplyText") or "")

    missing_levels = s.get("entry") is None or s.get("stop") is None or s.get("target") is None
    if missing_levels:
        return "risk"
    if risk_score >= 55 and opportunity < 62:
        return "risk"
    if opportunity >= 68 and entry_score >= 68 and risk_score < 45 and (gap is None or gap <= 0.025) and rr >= 1.25:
        return "action"
    if opportunity >= 56 and rr >= 1.15 and (gap is None or gap > 0.015 or risk_score >= 35):
        return "pullback"
    if ("우호" in supply_text or "순매수" in supply_text) and opportunity >= 48 and risk_score < 65:
        return "flow"
    if opportunity >= 52 and entry_score >= 50 and risk_score < 60:
        return "pullback"
    return "risk"


def _stockapp_raw_to_candidate_rows(market: str, kind: str) -> tuple[list[dict[str, Any]], str]:
    raw_rows, source = _stockapp_order_plan_rows(market)
    if not raw_rows:
        return [], ""
    out: list[dict[str, Any]] = []
    for row in raw_rows:
        if not _market_matches(row, market):
            continue
        bucket = _mone_timing_bucket(row, market)
        if bucket != kind:
            continue
        merged = _sanitize_legacy_quote_fields(dict(row), market)
        # Add alias columns so normalize_security_row can read StockApp raw consistently.
        merged.setdefault("symbol", _row_symbol(row, market))
        merged.setdefault("name", first_value(row, ["stock_name", "종목", "name", "ticker"], _row_symbol(row, market)))
        merged.setdefault("current_price", first_value(row, ["실시간현재가", "current_price_at_prediction", "basis_close", "prev_close"], ""))
        merged.setdefault("entry", first_value(row, ["우선진입가", "보수대기선", "preferred_entry", "technical_entry"], ""))
        merged.setdefault("stop_loss", first_value(row, ["손절가", "stop_loss"], ""))
        merged.setdefault("target_price", first_value(row, ["1차익절가", "take_profit1", "target_price"], ""))
        scores = _mone_classifier_scores(merged, market)
        normalized = normalize_security_row(merged, market)
        normalized.update({
            "category": kind,
            "sourceCategory": "stockapp_raw_mone_reclassified",
            "dataOrigin": "StockApp raw feed",
            "classificationPolicy": STOCKAPP_RAW_DATA_NOTE,
            "moneTimingBucket": kind,
            "opportunityScore": scores["opportunityScore"],
            "entryScore": scores["entryScore"],
            "riskScore": scores["riskScore"],
            "riskReward": f"1:{scores['rr']:.2f}" if scores.get("rr") else "손익비 없음",
            "confidence": scores["opportunityScore"],
            "reason": f"MONE 재분류: 기회 {scores['opportunityScore']} / 진입 {scores['entryScore']} / 위험 {scores['riskScore']}",
            "warning": scores.get("riskText") or "주의사항 없음",
            "nextAction": {
                "action": "오늘 진입 가능: 기준가·손절가·목표가 확인 후 조건부 진입",
                "pullback": "기다릴 후보: 좋은 후보이나 기준가/눌림 도달 시 재검토",
                "flow": "수급 포착: 수급은 우호적이나 가격·리스크 확인 필요",
                "risk": "매수금지/주의: 위험·이벤트·데이터 부족 요인 확인",
            }.get(kind, "재검토"),
            "rawStockAppFinalJudgment": first_value(row, ["실전최종판정", "final_judgment"], ""),
            "rawStockAppBuyAction": first_value(row, ["매수행동", "suggested_action"], ""),
            "rawStockAppNoBuy": first_value(row, ["매수금지", "no_buy_filter_applied"], ""),
            "raw": merged,
        })
        out.append(normalized)
    # Ranking: MONE scores first, not StockApp final labels.
    out.sort(key=lambda item: (float(item.get("opportunityScore") or 0), float(item.get("entryScore") or 0), -float(item.get("riskScore") or 0)), reverse=True)
    return out, source


def _locate_required_file(rel: str) -> Path:
    repo_path = REPO_ROOT / rel
    if repo_path.exists():
        return repo_path
    for root in stockapp_roots():
        for candidate in (root / rel, root / Path(rel).name, root / "reports" / Path(rel).name, root / "data" / Path(rel).name):
            if candidate.exists():
                return candidate
    return repo_path


def _history_source_file(file_name: str) -> Path:
    repo_path = HISTORY_DIR / file_name
    if repo_path.exists() and repo_path.stat().st_size > 0:
        return repo_path
    rel = Path("data") / "history" / file_name
    for root in stockapp_roots():
        for candidate in (root / rel, root / "history" / file_name, root / file_name):
            if candidate.exists() and candidate.stat().st_size > 0:
                return candidate
    return repo_path


def status_files() -> dict[str, Any]:
    items = []
    for rel in REQUIRED_FILES:
        path = _locate_required_file(rel)
        exists = path.exists()
        items.append({
            "path": rel,
            "resolvedPath": source_label(path) if exists else rel,
            "exists": exists,
            "status": "OK" if exists and path.stat().st_size > 0 else "MISSING",
            "bytes": path.stat().st_size if exists else 0,
            "rows": rows_for(path) if exists else 0,
            "updatedAt": file_mtime(path) if exists else "",
        })
    return {
        "repoRoot": str(REPO_ROOT),
        "sourceHandoff": source_handoff(),
        "stockAppBridge": stockapp_bridge_status(),
        "fallbackPolicy": list(FALLBACK_POLICY),
        "defaultVersionPriority": list(DEFAULT_VERSION_PRIORITY),
        "items": items,
    }


def status_env() -> dict[str, Any]:
    items = []
    for key in ENV_KEYS:
        value = os.environ.get(key, "")
        items.append({"key": key, "status": "OK" if value else "MISSING"})
    return {"items": items}


def _home_card_count(row: dict[str, Any]) -> int:
    value = first_value(row, ["건수", "count", "rows", "후보수", "개수"], "")
    num = _safe_float(value)
    return int(num) if num is not None else 0


def _home_top_text(items: list[dict[str, Any]]) -> str:
    if not items:
        return "-"
    item = items[0]
    name = item.get("name") or item.get("종목명") or item.get("company") or item.get("symbol") or "-"
    symbol = item.get("symbol") or item.get("종목코드") or item.get("ticker") or ""
    return f"{name} ({symbol})" if symbol and str(symbol) not in str(name) else str(name)


def _market_home_cards_from_live_data(market: str, existing_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the market-home top cards from the latest actionable datasets.

    v3.5.2 fix:
    - Do NOT keep an old today_summary just because one card has a non-zero count.
    - v93_action/pullback/flow/risk/company data must override stale summary cards.
    - If the live files are unexpectedly empty, fall back to existing_rows.
    """
    action_payload = candidate_rows(market, "action")
    pullback_payload = candidate_rows(market, "pullback")
    flow_payload = candidate_rows(market, "flow")
    risk_payload = candidate_rows(market, "risk")

    action = action_payload.get("items", [])
    pullback = pullback_payload.get("items", [])
    flow = flow_payload.get("items", [])
    risk = risk_payload.get("items", [])
    company_df, company_source = read_report("company_integrated", market)
    value_rows = dataframe_records(company_df)

    live_total = len(action) + len(pullback) + len(flow) + len(risk) + len(value_rows)
    if live_total <= 0 and existing_rows:
        return existing_rows

    cards = [
        {
            "아이콘": "🎯",
            "카드": "오늘 진입 가능",
            "설명": "진입가·기준가·손절가·목표가를 먼저 확인할 후보",
            "건수": str(len(action)),
            "TOP": _home_top_text(action),
            "구분": "action",
            "source": action_payload.get("source", ""),
        },
        {
            "아이콘": "⏳",
            "카드": "기다릴 후보",
            "설명": "좋은 종목이지만 기준가 또는 눌림을 기다릴 후보",
            "건수": str(len(pullback)),
            "TOP": _home_top_text(pullback),
            "구분": "pullback",
            "source": pullback_payload.get("source", ""),
        },
        {
            "아이콘": "💧",
            "카드": "수급 포착 후보",
            "설명": "수급·거래대금 흐름이 먼저 감지된 후보",
            "건수": str(len(flow)),
            "TOP": _home_top_text(flow),
            "구분": "flow",
            "source": flow_payload.get("source", ""),
        },
        {
            "아이콘": "📊",
            "카드": "저평가·기업분석",
            "설명": "실적·밸류·성장성을 함께 확인할 후보",
            "건수": str(len(value_rows)),
            "TOP": _home_top_text(value_rows),
            "구분": "value",
            "source": company_source,
        },
        {
            "아이콘": "⚠️",
            "카드": "매수금지 / 주의",
            "설명": "추격·과열·데이터 부족 등으로 신규 진입 제한",
            "건수": str(len(risk)),
            "TOP": _home_top_text(risk),
            "구분": "risk",
            "source": risk_payload.get("source", ""),
        },
    ]
    return cards

def market_summary(market: str) -> dict[str, Any]:
    summary, source = read_report("today_summary", market)
    data_status, data_source = read_report("data_status", market)
    dashboard, dash_source = read_report("operational_dashboard", market)
    status_path = REPORT_DIR / "mone_v36_github_actions_status.json"
    if not status_path.exists():
        status_path = REPORT_DIR / "v93_github_actions_status.json"
    status = read_json(status_path)
    summary_rows = dataframe_records(summary)
    summary_rows = _market_home_cards_from_live_data(market, summary_rows)
    sources = [source, data_source, dash_source]
    return {
        "market": market,
        "marketLabel": _market_label(market),
        "cards": summary_rows,
        "dataStatus": dataframe_records(data_status),
        "dashboard": dataframe_records(dashboard),
        "automation": status,
        "sources": [s for s in sources if s],
        "updatedAt": latest_updated_at(),
    }


def latest_updated_at() -> str:
    candidates = [
        report_path("symbol_snapshot", "kr"),
        report_path("symbol_snapshot", "us"),
        report_path("news_summary", "kr"),
        REPORT_DIR / "mone_v36_github_actions_status.json",
        REPORT_DIR / "v93_github_actions_status.json",
        REPORT_DIR / "stockapp_runner_status_kr.json",
        REPORT_DIR / "stockapp_runner_status_us.json",
        DATA_DIR / "stockapp" / "runner_status_kr.json",
        DATA_DIR / "stockapp" / "runner_status_us.json",
    ]
    for root in stockapp_roots():
        candidates.append(root / "reports" / "mone_v36_github_actions_status.json")
        candidates.append(root / "reports" / "v93_github_actions_status.json")
    times = [file_mtime(path) for path in candidates if path and path.exists()]
    cache_updated = quote_cache().get("updatedAt", "")
    if cache_updated:
        times.append(str(cache_updated))
    return max(times) if times else "기준시각 없음"


def symbols(market: str) -> dict[str, Any]:
    df, source = read_report("symbol_snapshot", market)
    rows = dataframe_records(df)
    if rows:
        rows = enrich_records_with_version_fallback("symbol_snapshot", market, rows)
        rows = _annotate_source_rows(rows, market, source, runner_target_date(market), fallback=_source_type_for_label(source, market, runner_target_date(market)) != preferred_source_type(market, runner_target_date(market)))
    else:
        df = read_csv(REPO_ROOT / f"watchlist_{market}_growth.csv")
        source = f"watchlist_{market}_growth.csv" if not df.empty else ""
        rows = dataframe_records(df)
        rows = _annotate_source_rows(rows, market, source, runner_target_date(market), fallback=True)
    normalized = [normalize_security_row(apply_quote_cache(row, market), market) for row in rows]
    return {"market": market, "count": len(normalized), "source": source, "items": normalized}


def symbol_detail(symbol: str, market: str) -> dict[str, Any]:
    target = normalize_symbol(symbol, market)
    all_symbols = symbols(market)
    item = next((row for row in all_symbols["items"] if normalize_symbol(row["symbol"], market) == target), None)
    candidates = {}
    for kind in ("action", "pullback", "flow", "risk"):
        cand = candidate_rows(market, kind)
        candidates[kind] = [row for row in cand["items"] if normalize_symbol(row["symbol"], market) == target]
    company_df, company_source = read_report("company_integrated", market)
    company = []
    if not company_df.empty:
        for row in dataframe_records(company_df):
            if normalize_symbol(first_value(row, SYMBOL_ALIASES), market) == target:
                company.append(row)
    news = [row for row in news_rows(market)["items"] if normalize_symbol(row.get("symbol"), market) == target]
    return {
        "market": market,
        "symbol": target,
        "item": item,
        "candidates": candidates,
        "company": company,
        "companySource": company_source,
        "news": news,
    }


def candidate_rows(market: str, kind: str) -> dict[str, Any]:
    allowed = {"action", "pullback", "flow", "risk"}
    if kind not in allowed:
        kind = "action"
    target_date = runner_target_date(market)
    preferred = preferred_source_type(market, target_date)

    # v3.5.11: If today's StockApp raw order plan exists, treat it as raw data
    # and classify it with MONE's own rules. Do not trust StockApp's final
    # "관망/제외/매수금지" labels as the MONE timing bucket.
    raw_rows: list[dict[str, Any]] = []
    raw_source = ""
    if preferred == "stockapp_snapshot":
        raw_rows, raw_source = _stockapp_raw_to_candidate_rows(market, kind)
    if raw_source:
        raw_rows = _annotate_source_rows(raw_rows, market, raw_source, target_date)
        return {
            "market": market,
            "type": kind,
            "count": len(raw_rows),
            "source": raw_source,
            "policy": STOCKAPP_RAW_DATA_NOTE,
            "items": raw_rows,
        }

    # Fallback: existing MONE reports/v93/v92 files.
    df, source = read_report(f"{kind}_cards", market)
    rows = enrich_records_with_version_fallback(f"{kind}_cards", market, dataframe_records(df))
    fallback = _source_type_for_label(source, market, target_date) != preferred
    rows = _annotate_source_rows(rows, market, source, target_date, fallback=fallback)
    normalized_rows = []
    for row in rows:
        row = apply_quote_cache(row, market)
        normalized = normalize_security_row(row, market)
        normalized.update({
            "category": first_value(row, ["분류", "category"], kind),
            "confidence": first_number(row, ["신뢰도점수", "confidence_score", "score"]),
            "reason": first_value(row, ["핵심근거", "근거1", "설명"], "근거 없음"),
            "warning": first_value(row, ["주의점", "주의", "risk_warning_flags"], "주의사항 없음"),
            "nextAction": first_value(row, ["다음행동", "suggested_action", "final_judgment"], "다음 행동 없음"),
            "policy": "MONE reports fallback",
        })
        normalized_rows.append(normalized)
    if not normalized_rows and preferred == "github_actions":
        raw_rows, raw_source = _stockapp_raw_to_candidate_rows(market, kind)
        if raw_source:
            raw_rows = _annotate_source_rows(raw_rows, market, raw_source, target_date, fallback=True)
            return {
                "market": market,
                "type": kind,
                "count": len(raw_rows),
                "source": raw_source,
                "policy": "GitHub Actions missing; stale StockApp snapshot fallback",
                "items": raw_rows,
            }
    return {"market": market, "type": kind, "count": len(normalized_rows), "source": source, "items": normalized_rows}


def positions(market: str) -> dict[str, Any]:
    df, source = read_report("position_cards", market)
    rows = dataframe_records(df)
    target_date = runner_target_date(market)
    if rows:
        rows = enrich_records_with_version_fallback("position_cards", market, rows)
        rows = enrich_records_from_file(rows, REPO_ROOT / f"holdings_{market}.csv", market)
        rows = _annotate_source_rows(rows, market, source, target_date, fallback=_source_type_for_label(source, market, target_date) != preferred_source_type(market, target_date))
    else:
        fallback = REPO_ROOT / f"holdings_{market}.csv"
        df = read_csv(fallback)
        source = fallback.relative_to(REPO_ROOT).as_posix() if not df.empty else ""
        rows = dataframe_records(df)
        rows = _annotate_source_rows(rows, market, source, target_date, fallback=True)

    # Include direct holdings rows that may not yet have a generated position_card report.
    direct_holdings = dataframe_records(read_csv(REPO_ROOT / f"holdings_{market}.csv"))
    existing_symbols = {_row_symbol(row, market) for row in rows}
    for holding_row in direct_holdings:
        symbol = _row_symbol(holding_row, market)
        if symbol and symbol not in existing_symbols:
            rows.extend(_annotate_source_rows([holding_row], market, f"holdings_{market}.csv", target_date, fallback=True))
            existing_symbols.add(symbol)

    normalized_rows = []
    for row in rows:
        row = apply_quote_cache(row, market)
        normalized = normalize_security_row(row, market)
        quantity = first_number(row, ["quantity", "보유수량", "shares"])
        avg_price = first_number(row, ["avg_price", "평균단가", "평단가"])
        current_price = normalized.get("currentPrice")
        pnl_value = None
        return_pct_value = None
        market_value = None
        cost_basis = None
        if quantity is not None and avg_price is not None and current_price is not None and avg_price:
            market_value = current_price * quantity
            cost_basis = avg_price * quantity
            pnl_value = market_value - cost_basis
            return_pct_value = ((current_price - avg_price) / avg_price) * 100

        normalized.update({
            "quantity": quantity,
            "quantityText": f"{quantity:,.0f}주" if quantity is not None else "보유수량 없음",
            "avgPrice": avg_price,
            "avgPriceText": format_price(avg_price, market) if avg_price is not None else "평균단가 없음",
            "marketValue": market_value,
            "marketValueText": format_price(market_value, market) if market_value is not None else "평가금액 없음",
            "costBasis": cost_basis,
            "costBasisText": format_price(cost_basis, market) if cost_basis is not None else "매입금액 없음",
            "returnPct": return_pct_value,
            "returnPctText": format_percent(return_pct_value),
            "pnl": pnl_value,
            "pnlText": format_signed_money(pnl_value, market),
            "nextAction": first_value(row, ["다음행동", "조치", "memo"], "다음 행동 없음"),
        })
        normalized_rows.append(normalized)
    return {"market": market, "count": len(normalized_rows), "source": source, "items": normalized_rows}


@lru_cache(maxsize=4)
def _news_company_aliases(market: str) -> tuple[tuple[str, str], ...]:
    candidates = [
        DATA_DIR / f"stock_master_{market}.csv",
        DATA_DIR / f"candidate_universe_{market}.csv",
    ]
    aliases: dict[str, str] = {}
    for path in candidates:
        if not path.exists() or path.stat().st_size <= 0:
            continue
        try:
            for row in dataframe_records(read_csv(path)):
                symbol = normalize_symbol(first_value(row, ["code", "symbol", "ticker"], ""), market)
                if not symbol:
                    continue
                for key in ("name_kr", "name", "company"):
                    name = str(row.get(key) or "").strip()
                    if len(name) >= 3 and name not in {"종목", "회사명", "이름 없음"}:
                        aliases.setdefault(name, symbol)
        except Exception:
            continue
    return tuple(sorted(((name, symbol) for name, symbol in aliases.items()), key=lambda pair: len(pair[0]), reverse=True))


def news_rows(market: str) -> dict[str, Any]:
    # 실시간 수집기는 버전 접두사가 없는 파일에 기록한다. 오래된 v93 스냅샷보다
    # 이 파일을 먼저 읽어야 현재 수집 결과가 종목 화면에 연결된다.
    live_path = REPORT_DIR / f"news_summary_{market}.csv"
    if live_path.exists() and live_path.stat().st_size > 0 and rows_for(live_path) > 0:
        df, source = read_csv(live_path), source_label(live_path)
    else:
        df, source = read_report("news_summary", market)
    rows = []
    for row in dataframe_records(df):
        title = first_value(row, ["제목", "title", "headline"], "뉴스 없음")
        summary = first_value(row, ["3줄요약", "summary", "핵심요약"], "요약 없음")
        symbol = normalize_symbol(first_value(row, SYMBOL_ALIASES, ""), market)
        name = first_value(row, NAME_ALIASES, "")
        if not symbol:
            haystack = f"{title} {summary}"
            for alias, alias_symbol in _news_company_aliases(market):
                if alias in haystack:
                    symbol, name = alias_symbol, alias
                    break
        rows.append({
            "market": market,
            "title": title,
            "summary": summary,
            "sourceName": first_value(row, ["출처", "source"], "출처 없음"),
            "url": first_value(row, ["URL", "url"], ""),
            "publishedAt": first_value(row, ["게시시간", "published_at", "time"], "게시시간 없음"),
            "symbol": symbol,
            "name": name,
            "nextAction": first_value(row, ["다음행동"], "다음 행동 없음"),
            "raw": row,
        })
    return {"market": market, "count": len(rows), "source": source, "items": rows}


# ── GNews 실시간 수집 ──────────────────────────────────────────────────

def _gnews_output_file(market: str) -> Path:
    return REPORT_DIR / f"news_summary_{market}.csv"


def _existing_gnews_result(market: str, status: str, error: str) -> dict[str, Any]:
    out_file = _gnews_output_file(market)
    result: dict[str, Any] = {
        "status": status,
        "market": market,
        "error": error[:200],
        "count": 0,
        "keptExisting": False,
    }
    if out_file.exists() and out_file.stat().st_size > 0:
        try:
            result["count"] = rows_for(out_file)
            result["file"] = out_file.relative_to(REPO_ROOT).as_posix()
            result["keptExisting"] = True
        except Exception:
            pass
    return result


def collect_gnews(market: str = "all") -> dict[str, Any]:
    """GNews API로 주식 뉴스를 수집해 news_summary_{kr|us}.csv로 저장한다."""
    api_key = os.environ.get("GNEWS_API_KEY", "").strip()
    if not api_key:
        return {"status": "MISSING_KEY", "message": "GNEWS_API_KEY가 없습니다.", "count": 0}

    results: list[dict[str, Any]] = []
    markets = ["kr", "us"] if market == "all" else [market]

    for mk in markets:
        if mk == "kr":
            params = {"token": api_key, "lang": "ko", "country": "kr", "topic": "business", "max": 10}
        else:
            params = {"token": api_key, "lang": "en", "country": "us", "topic": "business", "q": "stock market investing", "max": 10}

        try:
            resp = requests.get("https://gnews.io/api/v4/top-headlines", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.HTTPError as exc:
            status_code = getattr(exc.response, "status_code", None)
            if status_code == 429:
                results.append(_existing_gnews_result(mk, "RATE_LIMITED", "GNews 일일 요청 한도 초과"))
            else:
                results.append(_existing_gnews_result(mk, "ERROR", str(exc)))
            continue
        except Exception as exc:
            results.append(_existing_gnews_result(mk, "ERROR", str(exc)))
            continue

        articles = data.get("articles", [])
        rows = []
        for art in articles:
            rows.append({
                "시장": "한국주식" if mk == "kr" else "미국주식",
                "제목": art.get("title", ""),
                "3줄요약": art.get("description", art.get("title", "")),
                "출처": art.get("source", {}).get("name", "GNews"),
                "URL": art.get("url", ""),
                "게시시간": art.get("publishedAt", ""),
                "다음행동": "뉴스만으로 매수하지 말고 가격·수급·재무를 함께 확인",
                "종목코드": "",
                "종목명": "종목",
            })

        out_file = _gnews_output_file(mk)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        _write_csv_records(out_file, rows)
        results.append({"status": "OK", "market": mk, "count": len(rows), "file": out_file.relative_to(REPO_ROOT).as_posix()})

    ok_count = sum(1 for r in results if r.get("status") == "OK")
    kept_count = sum(1 for r in results if r.get("keptExisting"))
    rate_limited = any(r.get("status") == "RATE_LIMITED" for r in results)
    if ok_count == len(results):
        overall_status = "OK"
    elif ok_count or kept_count:
        overall_status = "PARTIAL"
    elif rate_limited:
        overall_status = "RATE_LIMITED"
    else:
        overall_status = "ERROR"
    return {
        "status": overall_status,
        "results": results,
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def predictions(market: str) -> dict[str, Any]:
    rows, source, target_date = read_primary_predictions(market)
    if not rows:
        df, source = read_report("future_probability", market)
        rows = enrich_records_with_version_fallback("future_probability", market, dataframe_records(df))
        rows = _annotate_source_rows(rows, market, source, target_date, fallback=True)
    if not rows:
        rows = [dict(item.get("raw", item)) for item in symbols(market)["items"][:30]]
        source = source or "symbols fallback + derived prediction"
        rows = _annotate_source_rows(rows, market, source, target_date, fallback=True)
    base_map = _combine_symbol_maps(market)
    normalized_rows = []
    for row in rows:
        row = dict(row.get("raw", row)) if isinstance(row, dict) else dict(row)
        row.setdefault("sourceFile", source)
        row.setdefault("sourceDate", _row_source_date(row) or target_date)
        row.setdefault("sourceType", _effective_source_type(_source_type_for_label(source, market, row.get("sourceDate")), preferred_source_type(market, row.get("sourceDate")), bool(row.get("isFallback"))))
        row.setdefault("isFallback", row.get("sourceType") in {"local_fallback", "stale"})
        symbol = _row_symbol(row, market)
        row = {**base_map.get(symbol, {}), **row} if symbol else row
        row = apply_quote_cache(row, market)
        normalized = normalize_security_row(row, market)
        normalized.update({
            "confidence": first_value(row, ["신뢰도점수", "confidence_score", "confidence", "score"], str(_confidence_value(row))),
            "nextAction": first_value(row, ["다음행동", "suggested_action", "final_judgment"], "확률과 예상가를 보조지표로 확인"),
        })
        normalized_rows.append(normalized)
    return {"market": market, "count": len(normalized_rows), "source": source, "items": normalized_rows}


def premarket_report(market: str) -> dict[str, Any]:
    # v3.5.11: Prefer MONE-classified StockApp raw buckets for the user-facing premarket view.
    bucket_payloads = [("오늘 진입", candidate_rows(market, "action")), ("기다림", candidate_rows(market, "pullback")), ("수급", candidate_rows(market, "flow")), ("주의", candidate_rows(market, "risk"))]
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    sources: list[str] = []
    required_files = [
        f"operational_readiness_{market}.csv",
        f"operation_health_{market}.csv",
        f"latest_{market}_performance_summary.csv",
        "prediction_integrity_status.csv",
        f"order_plan_{market}_*.csv",
        f"reports/mone_v36_final_recommendations_{market}_balanced_swing.csv",
        f"reports/mone_v36_final_data_center_{market}.csv",
    ]
    report_summary: list[dict[str, Any]] = []
    for file_name, label in (
        ("operational_readiness_{market}.csv", "operational_readiness"),
        ("operation_health_{market}.csv", "operation_health"),
        ("latest_{market}_performance_summary.csv", "performance_summary"),
        ("prediction_integrity_status.csv", "prediction_integrity"),
    ):
        rows, src = stockapp_report_rows(market, file_name)
        if src:
            sources.append(src)
            report_summary.extend({"report": label, **row} for row in rows[:8])
    for label, payload in bucket_payloads:
        if payload.get("source"):
            sources.append(payload.get("source"))
        for normalized in payload.get("items", [])[:30]:
            symbol = normalize_symbol(normalized.get("symbol"), market)
            key = f"{label}:{symbol}"
            if key in seen:
                continue
            seen.add(key)
            raw = normalized.get("raw", {}) if isinstance(normalized.get("raw"), dict) else {}
            items.append({
                **normalized,
                "sourceGroup": label,
                "expectedOpen": normalized.get("expectedOpenText", _format_optional_price(raw, ["예상시초가", "pred_open_mid", "pred_open", "premarket_price"], market, "예상 시초가 산출 필요")),
                "expectedClose": normalized.get("expectedCloseText", _format_optional_price(raw, ["예상종가", "pred_close_mid", "pred_close"], market, "예상 종가 산출 필요")),
                "target2Text": _format_optional_price(raw, TARGET2_ALIASES, market, "2차 목표가 없음"),
                "riskReward": normalized.get("riskReward", _display_value(raw, ["손익비", "rr", "rr1", "risk_reward", "risk_reward_ratio"], "손익비 없음")),
                "nextAction": normalized.get("nextAction") or "다음 행동 없음",
                "riskStatus": normalized.get("warning") or "리스크 상태 없음",
                "dataStatus": f"{normalized.get('classificationPolicy', 'MONE 재분류')} / 원본판정: {normalized.get('rawStockAppFinalJudgment', '-')}",
            })
    if items:
        summary = [
            {"구분": "오늘 진입", "건수": str(candidate_rows(market, "action").get("count", 0)), "설명": "MONE 진입점수·기회점수 기준"},
            {"구분": "기다림", "건수": str(candidate_rows(market, "pullback").get("count", 0)), "설명": "좋은 후보이나 가격/이벤트 대기"},
            {"구분": "수급", "건수": str(candidate_rows(market, "flow").get("count", 0)), "설명": "수급 포착 후보"},
            {"구분": "주의", "건수": str(candidate_rows(market, "risk").get("count", 0)), "설명": "위험/데이터 부족/과열 주의"},
        ]
        return {
            "status": "OK",
            "market": market,
            "count": len(items),
            "sourceDate": _max_date_key_from_rows(items),
            "sources": sorted(set(sources)),
            "summary": summary,
            "reportSummary": report_summary,
            "requiredFiles": required_files,
            "missingReason": "",
            "items": items,
        }

    # Existing reports fallback.
    summary_df, summary_source = read_report("today_summary", market)
    source_rows: list[tuple[str, str, dict[str, Any]]] = []
    sources = [summary_source]
    for kind, label in (("action_cards", "오늘 확인"), ("pullback_cards", "눌림목"), ("risk_cards", "주의"), ("future_probability", "확률")):
        df, source = read_report(kind, market)
        if source:
            sources.append(source)
        for row in enrich_records_with_version_fallback(kind, market, dataframe_records(df)):
            source_rows.append((kind, label, row))

    prediction_map = _latest_records_by_symbol(read_predictions_csv(market), market)
    base_map = _combine_symbol_maps(market)
    items = []
    seen: set[str] = set()
    for kind, label, row in source_rows:
        symbol = _row_symbol(row, market)
        if not symbol:
            continue
        merged = _merge_alias_values(base_map.get(symbol, {}), row)
        prediction = prediction_map.get(symbol, {})
        merged = _merge_alias_values(merged, prediction)
        merged = apply_quote_cache(merged, market)
        normalized = normalize_security_row(merged, market)
        key = f"{label}:{symbol}"
        if key in seen:
            continue
        seen.add(key)
        items.append({
            **normalized,
            "sourceGroup": label,
            "expectedOpen": normalized.get("expectedOpenText", _format_optional_price(merged, ["예상시초가", "pred_open_mid", "pred_open", "premarket_price"], market, "예상 시초가 산출 필요")),
            "expectedClose": normalized.get("expectedCloseText", _format_optional_price(merged, ["예상종가", "pred_close_mid", "pred_close"], market, "예상 종가 산출 필요")),
            "target2Text": _format_optional_price(merged, TARGET2_ALIASES, market, "2차 목표가 없음"),
            "riskReward": _display_value(merged, ["손익비", "rr", "rr1", "risk_reward", "risk_reward_ratio"], "손익비 없음"),
            "nextAction": first_value(merged, ["다음행동", "primary_action", "suggested_action", "final_judgment", "memo"], "다음 행동 없음"),
            "riskStatus": first_value(merged, ["주의점", "no_buy_flags", "risk_warning_flags", "risk_final_decision", "분류"], "리스크 상태 없음"),
            "dataStatus": first_value(merged, DATA_STATUS_ALIASES + ["prediction_quality_grade"], "데이터 상태 없음"),
        })

    return {
        "status": "OK" if items else "MISSING",
        "market": market,
        "count": len(items),
        "sourceDate": _max_date_key_from_rows(items),
        "sources": [source for source in sources if source],
        "summary": dataframe_records(summary_df),
        "reportSummary": report_summary,
        "requiredFiles": required_files,
        "missingReason": "" if items else "장전 리포트 후보/운영 리포트 파일에서 표시할 행을 찾지 못했습니다.",
        "items": items,
    }


def _latest_plan_baseline_map(market: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Latest order-plan/candidate rows used as the baseline for reports.

    These rows come from the GitHub/StockApp automation and should beat stale
    local position/risk snapshots.  They are not always live intraday quotes,
    but they are the freshest app-facing values and prevent empty/old rows from
    dominating the report screens.
    """
    baseline: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    for kind in ("action", "pullback", "flow", "risk"):
        try:
            payload = candidate_rows(market, kind)
        except Exception:
            continue
        src = _safe_str(payload.get("source", ""))
        if src and src not in sources:
            sources.append(src)
        for item in payload.get("items", []) or []:
            raw = item.get("raw", {}) if isinstance(item, dict) and isinstance(item.get("raw"), dict) else {}
            merged = _sanitize_legacy_quote_fields({**raw, **item}, market)
            symbol = normalize_symbol(first_value(merged, SYMBOL_ALIASES + ["stock_code", "종목코드", "ticker", "code", "symbol"]), market)
            if not _symbol_belongs_to_market(symbol, market):
                continue
            merged.setdefault("sourceFile", item.get("sourceFile") or src)
            merged.setdefault("sourceDate", item.get("sourceDate") or _row_source_date(merged) or file_mtime(REPO_ROOT / str(src)) if src else "")
            # Prefer the newest app-facing row for each symbol.
            old = baseline.get(symbol)
            if old is None or _date_key(merged.get("sourceDate")) >= _date_key(old.get("sourceDate")):
                baseline[symbol] = merged
    return baseline, sources


def _has_today_baseline_price(item: dict[str, Any]) -> bool:
    date_text = item.get("sourceDate") or item.get("priceSourceDate") or item.get("priceTime")
    price = _safe_float(item.get("currentPrice"))
    return bool(price is not None and price > 0 and _date_is_today(date_text))




def _intraday_baseline_report_paths(market: str) -> list[Path]:
    """Candidate/report CSVs that can rebuild intraday rows after quote cleanup.

    Quote-only snapshots are intentionally excluded.  They are handled by the
    current-price overlay and must not decide the universe.  These report files
    carry the actual app-facing candidates, entries, stops, targets and
    OHLCV/basis-close values that should remain visible after stale KIS/local
    quote fields are stripped.
    """
    mk = "kr" if market == "kr" else "us"
    patterns = (
        f"*action_cards_{mk}.csv",
        f"*pullback_cards_{mk}.csv",
        f"*risk_cards_{mk}.csv",
        f"*flow_cards_{mk}.csv",
        f"*position_cards_{mk}.csv",
        f"*symbol_snapshot_{mk}.csv",
        f"*confidence_cards_{mk}.csv",
        f"*final_recommendations_{mk}_*.csv",
        f"*company_integrated_{mk}.csv",
    )
    bases = [REPORT_DIR, DATA_DIR / "stockapp", DATA_DIR / "decision_system"]
    paths: list[Path] = []
    excluded_tokens = (
        "intraday_realtime_snapshot",
        "intraday_quote_snapshot",
        "kis_current_price",
        "mone_live_quote_cache",
        "quotes_cache",
        "orderbook",
    )
    for base in bases:
        if not base.exists():
            continue
        for pattern in patterns:
            for candidate in sorted(base.glob(pattern)):
                name = candidate.name.lower()
                if any(token in name for token in excluded_tokens):
                    continue
                if candidate.exists() and candidate.suffix.lower() == ".csv" and candidate.stat().st_size > 0 and rows_for(candidate) > 0:
                    paths.append(candidate)
    return sorted(_unique_paths(paths), key=lambda p: file_mtime(p), reverse=True)


def _basis_close_price_candidate_from_row(row: dict[str, Any], market: str, phase: dict[str, Any], source: str) -> dict[str, Any] | None:
    aliases = list(dict.fromkeys(KR_OHLC_CLOSE_ALIASES + CURRENT_PRICE_ALIASES + [
        "basis_close", "prev_close", "ohlcv_close", "close", "actual_close", "current_price_at_prediction"
    ]))
    price = first_number(row, aliases)
    if price is None or price <= 0:
        return None
    phase_key = str(phase.get("phase", ""))
    if market == "kr":
        status = "PREVIOUS_CLOSE" if phase_key == "kr_premarket" else "AFTER_CLOSE" if phase_key == "kr_after_close" else "STALE"
    else:
        status = "PREMARKET_SNAPSHOT" if phase_key == "us_premarket" else "AFTER_CLOSE" if phase_key == "us_after_close" else "STALE"
    date_text = first_value(row, ["basis_ohlc_date", "ohlcv_date", "actual_date", "date", "날짜", "일자", "sourceDate", "updated_at", "created_at"], "")
    return _price_candidate(
        price,
        date_text,
        f"report OHLCV/basis close · {source}".strip(" ·"),
        source,
        "ohlcv",
        status,
        phase,
        70,
    )


def _intraday_normalized_from_baseline_row(row: dict[str, Any], market: str, source: str, source_date: str) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    if not _market_matches(row, market):
        market_text = first_value(row, ["market", "시장"], "")
        if market_text:
            return None
    symbol = _row_symbol(row, market)
    if not _symbol_belongs_to_market(symbol, market):
        return None

    merged = _sanitize_legacy_quote_fields(dict(row), market)
    merged.setdefault("symbol", symbol)
    merged.setdefault("sourceFile", source)
    merged.setdefault("sourceDate", _row_source_date(merged) or source_date)
    merged.setdefault("sourceType", _source_type_for_label(source, market, merged.get("sourceDate", source_date)))
    merged = apply_quote_cache(merged, market)

    normalized = normalize_security_row(merged, market)
    phase = _market_price_phase(market)

    def _bad_price(item: dict[str, Any]) -> bool:
        current = item.get("currentPrice")
        status = str(item.get("priceDataStatus", "")).upper()
        source_type = str(item.get("priceSourceType", "")).lower()
        source_file = item.get("priceSourceFile", "")
        if current is None:
            return True
        if _is_legacy_quote_source(source_file, market):
            return True
        if status in {"STALE", "NO_PRICE"}:
            return True
        if source_type in {"local", "local_fallback", "row", "existing"}:
            return True
        return False

    if _bad_price(normalized):
        price_candidates = [
            _realtime_snapshot_price_candidate(symbol, market, phase),
            _ohlcv_price_candidate(symbol, market, phase),
            _basis_close_price_candidate_from_row(merged, market, phase, source),
        ]
        selected = _select_price_candidate(price_candidates, "", phase)
        if selected and str(selected.get("priceDataStatus", "")).upper() not in {"STALE", "NO_PRICE"}:
            normalized = _apply_price_candidate_to_normalized(normalized, selected, market)

    if _bad_price(normalized):
        return None
    return normalized


def _append_intraday_baseline_fallback_items(market: str, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Append report candidates that were lost while removing stale quote rows.

    This guardrail prevents the KR report from collapsing to only live KIS rows.
    It restores the candidate universe from report CSVs and reprices each row
    with current KIS snapshots or OHLCV/basis-close values.
    """
    existing = {normalize_symbol(item.get("symbol"), market) for item in items if item.get("symbol")}
    added_sources: list[str] = []
    out = list(items)
    for path in _intraday_baseline_report_paths(market):
        source = source_label(path)
        source_date = file_mtime(path)
        rows = dataframe_records(read_csv(path))
        for row in rows:
            normalized = _intraday_normalized_from_baseline_row(row, market, source, source_date)
            if not normalized:
                continue
            symbol = normalize_symbol(normalized.get("symbol"), market)
            if not symbol or symbol in existing:
                continue
            normalized.setdefault("sourceGroup", "baseline_fallback")
            normalized.setdefault("fallbackRepair", True)
            out.append(normalized)
            existing.add(symbol)
            if source and source not in added_sources:
                added_sources.append(source)
    return out, added_sources

def intraday_report(market: str) -> dict[str, Any]:
    symbol_map = _combine_symbol_maps(market)
    plan_map, plan_sources = _latest_plan_baseline_map(market)
    flow_map, flow_sources = _latest_data_maps(
        (r"kr_investor_flow_kis", r"flow_cards", r"master_investors", r"flow", r"supply", r"investor", r"수급"),
        market,
        ("sector", "node_modules"),
    )
    orderbook_map, orderbook_sources = _latest_data_maps(
        (r"intraday_orderbook_snapshot", r"orderbook", r"quote", r"bid", r"ask", r"호가", r"체결"),
        market,
        ("quotes_cache", "node_modules"),
    )
    position_items = positions(market)["items"]
    risk_items = candidate_rows(market, "risk")["items"]
    news = news_rows(market)["items"]
    news_count_by_symbol: dict[str, int] = {}
    for row in news:
        symbol = normalize_symbol(row.get("symbol"), market)
        if symbol:
            news_count_by_symbol[symbol] = news_count_by_symbol.get(symbol, 0) + 1

    symbols_order = []
    # Latest automation/order-plan rows first.  Position/risk/symbol fallbacks
    # should never decide which rows appear when current GitHub data exists.
    for symbol in list(plan_map.keys()):
        if _symbol_belongs_to_market(symbol, market) and symbol not in symbols_order:
            symbols_order.append(symbol)
    for symbol in list(flow_map.keys()) + list(orderbook_map.keys()):
        if _symbol_belongs_to_market(symbol, market) and symbol not in symbols_order:
            symbols_order.append(symbol)
    for collection in (position_items, risk_items, symbols(market)["items"][:30]):
        for item in collection:
            symbol = normalize_symbol(item.get("symbol"), market)
            if symbol and symbol not in symbols_order:
                symbols_order.append(symbol)

    risk_map = {normalize_symbol(item.get("symbol"), market): item for item in risk_items}
    position_map = {normalize_symbol(item.get("symbol"), market): item for item in position_items}
    items = []
    for symbol in symbols_order:
        if not _symbol_belongs_to_market(symbol, market):
            continue
        merged = dict(symbol_map.get(symbol, {}))
        merged = _merge_alias_values(merged, plan_map.get(symbol, {}))
        merged = _merge_alias_values(merged, flow_map.get(symbol, {}))
        merged = _merge_alias_values(merged, orderbook_map.get(symbol, {}))
        position = position_map.get(symbol)
        if position:
            merged = _merge_alias_values(merged, position.get("raw", {}))
        if risk_map.get(symbol):
            merged = _merge_alias_values(merged, risk_map[symbol].get("raw", {}))
        merged = apply_quote_cache(merged, market)
        normalized = normalize_security_row(merged, market)
        current = normalized.get("currentPrice")
        price_status = str(normalized.get("priceDataStatus", "")).upper()
        price_source_type = str(normalized.get("priceSourceType", "")).lower()
        price_source_file = normalized.get("priceSourceFile", "")
        # Report screens should not show stale legacy quote rows, but keep the
        # underlying candidate when it can be repriced by valid KIS/OHLCV data.
        needs_reprice = (
            _is_legacy_quote_source(price_source_file, market)
            or _row_price_is_stale_legacy(normalized, market)
            or price_source_type in {"local", "local_fallback", "row", "existing"}
            or (price_source_type in {"kis", "kis_snapshot", "quote_cache", "stockapp_snapshot"} and price_status == "STALE")
        )
        if needs_reprice:
            clean_merged = _sanitize_legacy_quote_fields(dict(merged), market)
            normalized = normalize_security_row(clean_merged, market)
            current = normalized.get("currentPrice")
            price_status = str(normalized.get("priceDataStatus", "")).upper()
            price_source_type = str(normalized.get("priceSourceType", "")).lower()
            price_source_file = normalized.get("priceSourceFile", "")
            if (
                _is_legacy_quote_source(price_source_file, market)
                or current is None
                or price_status == "STALE"
                or price_source_type in {"local", "local_fallback", "row", "existing"}
            ):
                # Last safe fallback: keep the report/candidate row and reprice it
                # from the current-session close/OHLCV source.  This restores KR
                # after-close/premarket rows that v2/v3/v4 over-filtered, while
                # still blocking old KIS/StockApp snapshot fields.
                close_candidate = _ohlcv_price_candidate(symbol, market, _market_price_phase(market))
                if close_candidate and str(close_candidate.get("priceDataStatus", "")).upper() in {"AFTER_CLOSE", "PREVIOUS_CLOSE", "PREMARKET_SNAPSHOT"}:
                    normalized = _apply_price_candidate_to_normalized(normalized, close_candidate, market)
                    current = normalized.get("currentPrice")
                    price_status = str(normalized.get("priceDataStatus", "")).upper()
                    price_source_type = str(normalized.get("priceSourceType", "")).lower()
                    price_source_file = normalized.get("priceSourceFile", "")
                if (
                    _is_legacy_quote_source(price_source_file, market)
                    or current is None
                    or price_status == "STALE"
                    or price_source_type in {"local", "local_fallback", "row", "existing"}
                ):
                    continue
        entry = normalized.get("entry")
        stop = normalized.get("stop")
        target = normalized.get("target")
        divergence = ((current - entry) / entry * 100) if current is not None and entry else None
        stop_break = bool(current is not None and stop is not None and current <= stop)
        target_hit = bool(current is not None and target is not None and current >= target)
        if stop_break:
            decision = "손절 주의"
        elif target_hit:
            decision = "익절 검토"
        elif divergence is not None and -2.0 <= divergence <= 1.0:
            decision = "진입 가능"
        elif entry is None:
            decision = "관망"
        else:
            decision = "대기"

        items.append({
            **normalized,
            "divergencePct": divergence,
            "divergenceText": format_percent(divergence, "기준가 없음"),
            "stopBreak": stop_break,
            "stopBreakText": "손절가 이탈" if stop_break else ("손절가 이상" if stop is not None else "손절가 없음"),
            "targetHit": target_hit,
            "targetHitText": "목표가 도달" if target_hit else ("목표가 미도달" if target is not None else "목표가 없음"),
            "holdingRisk": position.get("returnPctText", "보유종목 아님") if position else "보유종목 아님",
            "newsRiskStatus": f"뉴스 {news_count_by_symbol.get(symbol, 0)}건 / {risk_map[symbol].get('warning', '리스크 상태 있음')}" if symbol in risk_map else f"뉴스 {news_count_by_symbol.get(symbol, 0)}건",
            "intradayDecision": decision,
            "flowStatus": first_value(merged, ["supply_label", "supply_summary", "flow_data_status"], normalized.get("statuses", {}).get("flow", "")),
            "orderbookStatus": first_value(merged, ["orderbook_fetch_status", "orderbook_source_label", "orderbook_warning"], ""),
        })

    repaired_items, repaired_sources = _append_intraday_baseline_fallback_items(market, items)
    if repaired_sources:
        for repaired_source in repaired_sources:
            if repaired_source not in plan_sources:
                plan_sources.append(repaired_source)
    items = repaired_items

    sources = list(dict.fromkeys(plan_sources + flow_sources + orderbook_sources + [
        f"reports/v92_symbol_snapshot_{market}.csv",
        f"reports/v92_position_cards_{market}.csv",
        f"reports/v92_risk_cards_{market}.csv",
        f"reports/v92_news_summary_{market}.csv",
    ]))
    required_files = (
        [
            "intraday_orderbook_snapshot.csv",
            "intraday_orderbook_snapshot-Kang.csv",
            "kr_investor_flow_kis.csv",
            "reports/v92_flow_cards_kr.csv",
            "reports/v92_master_investors_kr.csv",
        ]
        if market == "kr"
        else ["intraday_orderbook_snapshot.csv", "reports/v92_flow_cards_us.csv"]
    )
    phase = _market_price_phase(market)
    fresh_intraday_count = sum(1 for item in items if _intraday_item_is_fresh(item))
    today_baseline_count = sum(1 for item in items if _has_today_baseline_price(item))
    source_date = _max_date_key_from_rows(items)
    if not items:
        status = "MISSING"
        missing_reason = "장중 수급/호가/위험 카드에서 표시할 행을 찾지 못했습니다."
    elif not phase.get("isIntraday"):
        # Outside the regular session this screen is a reference view.  If the
        # automation produced today's order-plan/performance rows, treat it as
        # PARTIAL instead of pretending there is no data.
        status = "PARTIAL" if today_baseline_count > 0 else "STALE"
        missing_reason = f"현재 {phase.get('label', '장중 아님')} 구간입니다. 최신 자동화 기준값을 참고용으로 표시합니다."
    elif fresh_intraday_count <= 0:
        status = "PARTIAL" if today_baseline_count > 0 else "STALE"
        missing_reason = "오늘 장중 KIS 현재가/호가/수급의 실시간 행은 확인되지 않았고, 최신 자동화 기준값을 참고용으로 표시합니다."
    else:
        status = "OK"
        missing_reason = ""
    return {
        "status": status,
        "market": market,
        "count": len(items),
        "freshIntradayCount": fresh_intraday_count,
        "todayBaselineCount": today_baseline_count,
        "sourceDate": source_date,
        "sources": sources,
        "requiredFiles": required_files,
        "missingReason": missing_reason,
        "items": items,
    }


def closing_report(market: str) -> dict[str, Any]:
    prediction_rows = read_predictions_csv(market)
    prediction_history_rows = prediction_history(market)["items"]
    outcome_rows = outcome_history(market)["items"]
    recent_predictions = sorted(prediction_rows, key=lambda row: first_value(row, ["created_at", "target_date"], ""), reverse=True)[:120]
    recent_history = sorted(prediction_history_rows, key=lambda row: first_value(row, ["created_at", "target_date"], ""), reverse=True)[:80]
    report_sources: list[str] = []
    report_summary: list[dict[str, Any]] = []
    for file_name, label in (
        ("operation_health_{market}.csv", "operation_health"),
        ("operational_readiness_{market}.csv", "operational_readiness"),
        ("latest_{market}_performance_summary.csv", "performance_summary"),
        ("prediction_integrity_status.csv", "prediction_integrity"),
    ):
        rows, src = stockapp_report_rows(market, file_name)
        if src:
            report_sources.append(src)
            for row in rows[:8]:
                report_summary.append({"report": label, **row})

    items = []
    stockapp_rows, stockapp_order_source = _stockapp_order_plan_rows(market) if preferred_source_type(market) == "stockapp_snapshot" else ([], "")
    if stockapp_order_source:
        report_sources.insert(0, stockapp_order_source)
    closing_source_rows = stockapp_rows[:80] if stockapp_rows else recent_predictions[:80]
    for row in closing_source_rows:
        symbol = _row_symbol(row, market)
        if not _symbol_belongs_to_market(symbol, market):
            continue
        name = first_value(row, NAME_ALIASES + ["stock_name"], symbol or "이름 없음")
        direction = _direction_label(first_value(row, ["direction_hit", "decision_success", "prediction_result"], ""))
        open_range = _direction_label(first_value(row, ["open_in_range"], ""))
        close_range = _direction_label(first_value(row, ["close_in_range"], ""))
        entry_touched = _direction_label(first_value(row, ["entry_touched", "virtual_entry_filled"], ""))
        stop_touched = _direction_label(first_value(row, ["stop_touched"], ""))
        tp_touched = _direction_label(first_value(row, ["tp1_touched", "tp2_touched"], ""))
        failed = direction == "불일치" or open_range == "불일치" or close_range == "불일치"
        items.append({
            "symbol": symbol or "코드 없음",
            "name": name,
            "predictionBaseDate": first_value(row, ["created_at", "data_date", "target_date"], "예측 기준일 없음"),
            "actualResultDate": first_value(row, ["actual_date", "target_date"], "실제 결과일 없음"),
            "directionHit": direction,
            "rangeHit": f"시초 {open_range} / 종가 {close_range}",
            "entryTouched": entry_touched,
            "stopTakeProfit": f"손절 {stop_touched} / 익절 {tp_touched}",
            "failedSymbol": name if failed else "해당 없음",
            "failureReason": first_value(row, ["prediction_error_reason", "failure_reason", "prediction_cause_summary"], "실패 사유 또는 데이터 부족 사유 없음"),
            "sourceType": first_value(row, ["sourceType"], _source_type_for_label(stockapp_order_source, market, first_value(row, ["sourceDate"], ""))),
            "sourceFile": first_value(row, ["sourceFile"], stockapp_order_source or "predictions.csv"),
            "sourceDate": first_value(row, ["sourceDate"], first_value(row, ["created_at", "target_date"], "")),
        })

    if not items:
        for row in recent_history[:80]:
            items.append({
                "symbol": normalize_symbol(first_value(row, SYMBOL_ALIASES + ["ticker"], ""), market) or "코드 없음",
                "name": first_value(row, NAME_ALIASES + ["stock_name"], "이름 없음"),
                "predictionBaseDate": first_value(row, ["created_at", "target_date"], "예측 기준일 없음"),
                "actualResultDate": first_value(row, ["target_date"], "실제 결과일 없음"),
                "directionHit": _direction_label(first_value(row, ["prediction_result"], "")),
                "rangeHit": "범위 검증 데이터 부족",
                "entryTouched": "주문 기준가 검증 데이터 부족",
                "stopTakeProfit": "손절/익절 검증 데이터 부족",
                "failedSymbol": "검증 대기",
                "failureReason": "predictions.csv 상세 검증 컬럼 없음",
            })

    return {
        "market": market,
        "count": len(items),
        "directionHitRate": _rate(prediction_rows, ["direction_hit", "decision_success"]),
        "rangeHitRate": _rate(prediction_rows, ["close_in_range", "open_in_range"]),
        "predictionHistoryCount": prediction_history(market)["count"],
        "outcomeHistoryCount": outcome_history(market)["count"],
        "sources": list(dict.fromkeys(report_sources + ["predictions.csv", "data/history/prediction_history.csv", "data/history/outcome_history.csv"])),
        "reportSummary": report_summary,
        "items": items,
        "outcomes": outcome_rows[:80],
    }


def report_files() -> dict[str, Any]:
    keywords = ("latest", "v92", "v93", "operational", "portfolio", "backtest")
    items = []
    for path in sorted(REPORT_DIR.glob("*")):
        if not path.is_file() or not any(keyword in path.name.lower() for keyword in keywords):
            continue
        df = read_csv(path) if path.suffix.lower() == ".csv" else pd.DataFrame()
        rows = int(len(df)) if path.suffix.lower() == ".csv" else rows_for(path)
        column_count = int(len(df.columns)) if path.suffix.lower() == ".csv" and not df.empty else 0
        status = "EMPTY" if path.stat().st_size == 0 or rows == 0 else "OK"
        items.append({
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "fileName": path.name,
            "group": _report_group(path),
            "rows": rows,
            "columns": column_count,
            "updatedAt": file_mtime(path),
            "bytes": path.stat().st_size,
            "status": status,
            "fallbackStatus": _fallback_status_for_file(path),
            "preview": dataframe_records(df, 3) if path.suffix.lower() == ".csv" else [],
        })
    return {"count": len(items), "fallbackPolicy": list(FALLBACK_POLICY), "items": items}


def report_preview(path: str) -> dict[str, Any]:
    rel = Path(path.replace("\\", "/"))
    target = (REPO_ROOT / rel).resolve()
    try:
        target.relative_to(REPORT_DIR.resolve())
    except ValueError:
        return {"path": path, "status": "BLOCKED", "items": [], "message": "reports 폴더 안의 파일만 미리보기할 수 있습니다."}
    if not target.exists() or not target.is_file():
        return {"path": path, "status": "MISSING", "items": [], "message": "파일 없음"}
    if target.suffix.lower() != ".csv":
        return {"path": path, "status": "UNSUPPORTED", "items": [], "message": "CSV 미리보기만 지원합니다."}
    df = read_csv(target)
    return {
        "path": target.relative_to(REPO_ROOT).as_posix(),
        "status": "OK" if not df.empty else "EMPTY",
        "rows": int(len(df)),
        "columns": list(df.columns),
        "items": dataframe_records(df, 20),
    }


def prediction_history(market: str | None = None) -> dict[str, Any]:
    path = _history_source_file("prediction_history.csv")
    df = read_csv(path)
    rows = dataframe_records(df)
    if market:
        rows = [row for row in rows if _market_matches(row, market)]
    return {
        "count": int(len(rows)),
        "source": source_label(path),
        "items": rows[:250],
    }


def outcome_history(market: str | None = None) -> dict[str, Any]:
    path = _history_source_file("outcome_history.csv")
    df = read_csv(path)
    rows = dataframe_records(df)
    if market:
        rows = [row for row in rows if _market_matches(row, market)]
    return {
        "count": int(len(rows)),
        "source": source_label(path),
        "items": rows[:250],
    }


def _find_data_files(patterns: tuple[str, ...], exclude: tuple[str, ...] = ()) -> list[Path]:
    roots = _unique_paths(data_roots() + report_roots())
    found: list[Path] = []
    exclude_all = tuple(set(exclude + tuple(EXCLUDED_SCAN_PARTS)))
    for base in roots:
        if not base.exists() or _is_excluded_path(base):
            continue
        for path in base.rglob("*.csv"):
            if _is_excluded_path(path):
                continue
            name = path.name.lower()
            full = path.as_posix().lower()
            if exclude_all and any(term in name or term in full for term in exclude_all):
                continue
            if any(re.search(pattern, name) or re.search(pattern, full) for pattern in patterns):
                found.append(path)
                if len(found) >= 500:
                    break
        if len(found) >= 500:
            break
    # de-duplicate while preserving deterministic order
    seen: set[str] = set()
    unique: list[Path] = []
    for path in sorted(found, key=lambda p: (p.stat().st_mtime if p.exists() else 0), reverse=True):
        key = path.resolve().as_posix()
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique





def _write_csv_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_csv(path, index=False, encoding="utf-8-sig")


def _recent_date_window(days: int = 30) -> tuple[str, str]:
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=max(1, days))
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _disclosure_output_file(market: str) -> Path:
    return DATA_DIR / "disclosures" / f"disclosures_{market}.csv"


def _collect_dart_disclosures(days: int = 30) -> dict[str, Any]:
    api_key = os.environ.get("DART_API_KEY", "").strip()
    out_file = _disclosure_output_file("kr")
    if not api_key:
        return {"status": "MISSING_KEY", "market": "kr", "message": "DART_API_KEY가 없어 공시를 수집하지 못했습니다.", "count": 0, "file": out_file.relative_to(REPO_ROOT).as_posix()}
    bgn_de, end_de = _recent_date_window(days)
    params = {
        "crtfc_key": api_key,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "page_no": 1,
        "page_count": 100,
        "sort": "date",
        "sort_mth": "desc",
    }
    try:
        res = requests.get("https://opendart.fss.or.kr/api/list.json", params=params, timeout=12)
        res.raise_for_status()
        payload = res.json()
    except Exception as exc:
        return {"status": "ERROR", "market": "kr", "message": f"DART 공시 수집 실패: {exc}", "count": 0, "file": out_file.relative_to(REPO_ROOT).as_posix()}
    rows = []
    for item in payload.get("list", []) or []:
        rows.append({
            "market": "kr",
            "symbol": normalize_symbol(item.get("stock_code", ""), "kr"),
            "name": item.get("corp_name", ""),
            "corp_code": item.get("corp_code", ""),
            "title": item.get("report_nm", ""),
            "date": item.get("rcept_dt", ""),
            "rcept_no": item.get("rcept_no", ""),
            "source": "DART",
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}" if item.get("rcept_no") else "",
            "collection_status": payload.get("status", ""),
            "collection_message": payload.get("message", ""),
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    _write_csv_records(out_file, rows)
    return {"status": "OK", "market": "kr", "message": "DART 공시 수집 완료", "count": len(rows), "file": out_file.relative_to(REPO_ROOT).as_posix()}


def _collect_us_filings(days: int = 60, max_symbols: int = 35) -> dict[str, Any]:
    token = os.environ.get("FINNHUB_API_KEY", "").strip()
    out_file = _disclosure_output_file("us")
    if not token:
        return {"status": "MISSING_KEY", "market": "us", "message": "FINNHUB_API_KEY가 없어 SEC filing을 수집하지 못했습니다.", "count": 0, "file": out_file.relative_to(REPO_ROOT).as_posix()}
    universe = symbols("us").get("items", [])
    tickers: list[str] = []
    for item in universe:
        sym = normalize_symbol(item.get("symbol"), "us")
        if sym and sym not in tickers and re.fullmatch(r"[A-Z][A-Z0-9._-]{0,12}", sym):
            tickers.append(sym)
        if len(tickers) >= max_symbols:
            break
    if not tickers:
        return {"status": "NO_SYMBOLS", "market": "us", "message": "SEC filing을 조회할 미장 티커가 없습니다.", "count": 0, "file": out_file.relative_to(REPO_ROOT).as_posix()}
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=max(1, days))
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for sym in tickers:
        try:
            res = requests.get(
                "https://finnhub.io/api/v1/stock/filings",
                params={"symbol": sym, "from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d"), "token": token},
                timeout=8,
            )
            if res.status_code >= 400:
                errors.append(f"{sym}: HTTP {res.status_code}")
                continue
            data = res.json()
            if not isinstance(data, list):
                continue
            for item in data[:20]:
                rows.append({
                    "market": "us",
                    "symbol": sym,
                    "name": sym,
                    "title": item.get("form") or item.get("type") or "SEC filing",
                    "date": item.get("filedDate") or item.get("acceptedDate") or "",
                    "source": "SEC/Finnhub",
                    "url": item.get("reportUrl") or item.get("filingUrl") or "",
                    "accessionNumber": item.get("accessionNumber", ""),
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
        except Exception as exc:
            errors.append(f"{sym}: {exc}")
    _write_csv_records(out_file, rows)
    status = "OK" if rows else "NO_DATA"
    return {"status": status, "market": "us", "message": "SEC/Finnhub filing 수집 완료" if rows else "SEC/Finnhub filing 결과가 없습니다.", "count": len(rows), "file": out_file.relative_to(REPO_ROOT).as_posix(), "errors": errors[:10]}


def _collect_us_company_news(days: int = 45, max_symbols: int = 60) -> dict[str, Any]:
    """Finnhub /company-news로 종목별 뉴스를 수집해 news_summary_us.csv에 추가한다."""
    token = os.environ.get("FINNHUB_API_KEY", "").strip()
    out_file = _gnews_output_file("us")
    if not token:
        return {"status": "MISSING_KEY", "market": "us", "message": "FINNHUB_API_KEY 없음", "count": 0}

    # OHLCV 파일 목록에서 US 티커 수집 (symbol master보다 더 넓은 커버리지)
    ohlcv_dir = DATA_DIR / "market" / "ohlcv"
    tickers: list[str] = []
    if ohlcv_dir.is_dir():
        for path in sorted(ohlcv_dir.glob("us_*_daily.csv")):
            sym = path.name.replace("us_", "").replace("_daily.csv", "")
            if sym and sym not in tickers and re.fullmatch(r"[A-Z][A-Z0-9._-]{0,12}", sym):
                tickers.append(sym)
            if len(tickers) >= max_symbols:
                break
    # 폴백: symbol master
    if not tickers:
        for item in symbols("us").get("items", []):
            sym = normalize_symbol(item.get("symbol"), "us")
            if sym and sym not in tickers and re.fullmatch(r"[A-Z][A-Z0-9._-]{0,12}", sym):
                tickers.append(sym)
            if len(tickers) >= max_symbols:
                break
    if not tickers:
        return {"status": "NO_SYMBOLS", "market": "us", "count": 0}

    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=max(1, days))
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for sym in tickers:
        try:
            res = requests.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": sym, "from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d"), "token": token},
                timeout=8,
            )
            if res.status_code >= 400:
                errors.append(f"{sym}: HTTP {res.status_code}")
                continue
            articles = res.json()
            if not isinstance(articles, list):
                continue
            # 날짜순 오름차순: 가장 오래된 기사부터 저장 (신호 발생 시점 근처 기사 보존)
            articles_sorted = sorted(articles, key=lambda x: x.get("datetime", 0))
            for art in articles_sorted[:20]:
                rows.append({
                    "시장": "미국주식",
                    "제목": art.get("headline", ""),
                    "3줄요약": art.get("summary", art.get("headline", ""))[:200],
                    "출처": art.get("source", "Finnhub"),
                    "URL": art.get("url", ""),
                    "게시시간": art.get("datetime", ""),
                    "다음행동": "",
                    "종목코드": sym,
                    "종목명": sym,
                })
        except Exception as exc:
            errors.append(f"{sym}: {exc}")

    if rows:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        # 기존 파일과 병합 (덮어쓰지 않고 추가)
        existing: list[dict[str, Any]] = []
        if out_file.exists():
            try:
                import csv as _csv
                for enc in ("utf-8-sig", "utf-8", "cp949"):
                    try:
                        with out_file.open("r", encoding=enc, newline="") as f:
                            existing = [dict(r) for r in _csv.DictReader(f)]
                        break
                    except Exception:
                        continue
            except Exception:
                pass
        # 종목코드가 없는 기존 행(GNews 일반 뉴스)은 유지, Finnhub 행은 교체
        keep = [r for r in existing if not (r.get("종목코드") or r.get("symbol", "")).strip()]
        merged = keep + rows
        _write_csv_records(out_file, merged)
    return {"status": "OK" if rows else "NO_DATA", "market": "us", "count": len(rows), "errors": errors[:5]}


def refresh_disclosures(market: str = "all", days: int = 30) -> dict[str, Any]:
    market = market if market in {"kr", "us", "all"} else "all"
    results: list[dict[str, Any]] = []
    if market in {"kr", "all"}:
        results.append(_collect_dart_disclosures(days=days))
    if market in {"us", "all"}:
        results.append(_collect_us_filings(days=max(days, 60)))
        results.append(_collect_us_company_news(days=45))
    return {
        "status": "OK" if any(r.get("status") == "OK" for r in results) else "NO_DATA",
        "results": results,
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _latest_data_maps(patterns: tuple[str, ...], market: str, exclude: tuple[str, ...] = ()) -> tuple[dict[str, dict[str, Any]], list[str]]:
    files = sorted(_find_data_files(patterns, exclude + ("node_modules",)), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    merged: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    for path in files[:12]:
        if path.suffix.lower() != ".csv":
            continue
        low_name = path.name.lower()
        full = path.as_posix().lower()
        if _is_legacy_quote_source(source_label(path), market):
            continue
        if market == "kr" and any(tok in low_name or tok in full for tok in ("_us", "us_", "sec_recent", "sec_filing", "disclosures_us")):
            continue
        if market == "us" and any(tok in low_name or tok in full for tok in ("_kr", "kr_", "dart", "disclosures_kr", "market_cap_cache", "kr_financial")):
            continue
        df = read_csv(path)
        if df.empty:
            continue
        source = source_label(path)
        for row in dataframe_records(df):
            if not _market_matches(row, market):
                continue
            symbol = _row_symbol(row, market)
            if not _symbol_belongs_to_market(symbol, market):
                continue
            row = _sanitize_legacy_quote_fields(dict(row), market)
            row.setdefault("sourceFile", source)
            row.setdefault("sourceType", _source_type_for_label(source, market, file_mtime(path)))
            row.setdefault("sourceDate", file_mtime(path))
            merged[symbol] = _merge_alias_values(merged.get(symbol, {}), row) if symbol in merged else dict(row)
        if source not in sources and merged:
            sources.append(source)
    return merged, sources

def github_actions_status() -> dict[str, Any]:
    repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("MONE_GITHUB_REPOSITORY") or "selene0519/agnas-stock-app"
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("MONE_GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    api_base = f"https://api.github.com/repos/{repo}"
    try:
        wf_res = requests.get(f"{api_base}/actions/workflows", headers=headers, timeout=8)
        runs_res = requests.get(f"{api_base}/actions/runs?per_page=8", headers=headers, timeout=8)
        if wf_res.status_code == 404 and not token:
            return {
                "status": "NEED_TOKEN",
                "repo": repo,
                "message": "private repo이거나 인증이 없어 GitHub Actions를 조회할 수 없습니다. GITHUB_TOKEN 또는 MONE_GITHUB_TOKEN을 .env에 넣으면 연결됩니다.",
                "workflows": [],
                "runs": [],
            }
        if wf_res.status_code >= 400:
            return {"status": "ERROR", "repo": repo, "message": f"workflow 조회 실패 HTTP {wf_res.status_code}", "workflows": [], "runs": []}
        workflows = []
        for wf in wf_res.json().get("workflows", []):
            workflows.append({
                "name": wf.get("name", ""),
                "path": wf.get("path", ""),
                "state": wf.get("state", ""),
                "id": wf.get("id", ""),
            })
        runs = []
        if runs_res.status_code < 400:
            for run in runs_res.json().get("workflow_runs", []):
                runs.append({
                    "name": run.get("name", ""),
                    "event": run.get("event", ""),
                    "status": run.get("status", ""),
                    "conclusion": run.get("conclusion", ""),
                    "created_at": run.get("created_at", ""),
                    "updated_at": run.get("updated_at", ""),
                    "head_branch": run.get("head_branch", ""),
                    "html_url": run.get("html_url", ""),
                })
        schedule_runs = [r for r in runs if r.get("event") == "schedule"]
        dispatch_runs = [r for r in runs if r.get("event") == "workflow_dispatch"]
        successful_runs = [r for r in runs if r.get("conclusion") == "success" and str(r.get("name", "")).lower() == "mone auto accumulator"]
        latest_automation = (schedule_runs[0] if schedule_runs else None) or (dispatch_runs[0] if dispatch_runs else None) or (successful_runs[0] if successful_runs else None)
        return {
            "status": "OK",
            "repo": repo,
            "message": "GitHub Actions API 연결됨" if token else "공개 API로 조회됨",
            "workflows": workflows,
            "runs": runs,
            "latestScheduled": schedule_runs[0] if schedule_runs else None,
            "latestWorkflowDispatch": dispatch_runs[0] if dispatch_runs else None,
            "latestAutomationRun": latest_automation,
            "automationMode": "github_schedule" if schedule_runs else ("external_workflow_dispatch" if dispatch_runs else "unknown"),
        }
    except Exception as exc:
        return {"status": "ERROR", "repo": repo, "message": f"GitHub Actions 조회 실패: {exc}", "workflows": [], "runs": []}


def chart_data(symbol: str, market: str) -> dict[str, Any]:
    target = normalize_symbol(symbol, market)
    df, source = _load_ohlcv(target, market)
    if df.empty:
        prefix = "kr" if market == "kr" else "us"
        return {
            "status": "NO_DATA",
            "symbol": target,
            "market": market,
            "source": "",
            "items": [],
            "message": "선택 종목의 OHLCV CSV를 찾지 못했습니다.",
            "requiredFiles": [
                f"data/market/ohlcv/{prefix}_{target}_daily.csv",
                f"StockApp data/market/ohlcv/{prefix}_{target}_daily.csv",
            ],
        }
    work = df.copy()
    work["ma5"] = work["close"].rolling(5).mean()
    work["ma10"] = work["close"].rolling(10).mean()
    work["ma20"] = work["close"].rolling(20).mean()
    work["ma60"] = work["close"].rolling(60).mean()
    ma20 = work["close"].rolling(20).mean()
    std20 = work["close"].rolling(20).std(ddof=0)  # 모집단 표준편차 (John Bollinger 원저 기준)
    work["bbUpper"] = ma20 + std20 * 2
    work["bbLower"] = ma20 - std20 * 2
    # Wilder's Smoothed RSI (EMA 방식, 업계 표준)
    delta = work["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    work["rsi"] = (100 - (100 / (1 + rs))).round(2)
    ema12 = work["close"].ewm(span=12, adjust=False).mean()
    ema26 = work["close"].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    work["macd"] = macd
    work["macdSignal"] = macd.ewm(span=9, adjust=False).mean()
    cols = ["date", "open", "high", "low", "close", "volume", "ma5", "ma10", "ma20", "ma60", "bbUpper", "bbLower", "rsi", "macd", "macdSignal"]
    items = []
    for row in work.tail(160)[cols].replace({np.nan: None}).to_dict(orient="records"):
        items.append({k: (round(v, 4) if isinstance(v, float) and np.isfinite(v) else v) for k, v in row.items()})
    latest = items[-1] if items else {}
    indicator_status = []
    if len(work) >= 5:
        indicator_status.append("MA5 산출 가능")
    else:
        indicator_status.append("MA5 산출 불가: OHLCV 5일 미만")
    if len(work) >= 20:
        indicator_status.append("MA20·볼린저밴드 산출 가능")
    else:
        indicator_status.append("MA20·볼린저밴드 산출 불가: OHLCV 20일 미만")
    if len(work) >= 14:
        indicator_status.append("RSI 산출 가능")
    else:
        indicator_status.append("RSI 산출 불가: OHLCV 14일 미만")
    if len(work) >= 26:
        indicator_status.append("MACD 산출 가능")
    else:
        indicator_status.append("MACD 산출 불가: OHLCV 26일 미만")
    return {"status": "OK", "symbol": target, "market": market, "source": source, "count": len(items), "latest": latest, "indicatorStatus": indicator_status, "items": items}


def similar_pattern_history(
    symbol: str,
    market: str,
    horizons: tuple[int, ...] = (1, 5, 10),
    top_n: int = 10,
) -> dict[str, Any]:
    """현재 RSI·MACD·볼린저밴드 위치와 가장 비슷했던 과거 시점을 찾아 이후 수익률을 집계한다.

    "Was It?" 스타일 — 지표 상태가 유사했던 과거 구간들의 1/5/10일 후 수익률과 승률을 보여준다.
    """
    target = normalize_symbol(symbol, market)
    df, source = _load_ohlcv(target, market)
    max_horizon = max(horizons)
    min_rows = 40 + max_horizon
    if df.empty or len(df) < min_rows:
        return {
            "status": "NO_DATA",
            "symbol": target,
            "market": market,
            "message": f"유사 패턴 분석에는 최소 {min_rows}일 이상의 OHLCV가 필요합니다.",
            "matches": [],
            "summary": {},
        }

    work = df.copy().reset_index(drop=True)
    close = work["close"]
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std(ddof=0)
    bb_upper = ma20 + std20 * 2
    bb_lower = ma20 - std20 * 2
    bb_width = (bb_upper - bb_lower).replace(0, np.nan)
    work["bbPercent"] = ((close - bb_lower) / bb_width).clip(-0.5, 1.5)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    work["rsi"] = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    work["macdHistPct"] = ((macd - macd_signal) / close.replace(0, np.nan)) * 100

    feature_cols = ["rsi", "bbPercent", "macdHistPct"]
    valid = work.dropna(subset=feature_cols)
    if valid.empty:
        return {
            "status": "NO_DATA",
            "symbol": target,
            "market": market,
            "message": "지표를 계산할 데이터가 부족합니다.",
            "matches": [],
            "summary": {},
        }

    means = valid[feature_cols].mean()
    stds = valid[feature_cols].std(ddof=0).replace(0, 1.0)
    z = (valid[feature_cols] - means) / stds

    current_idx = valid.index[-1]
    current_row = valid.loc[current_idx]
    current_z = z.loc[current_idx]

    buffer_days = 5  # 직전 구간은 현재와 흐름이 이어져 있어 사실상 같은 패턴이므로 제외
    eligible_idx = [
        idx for idx in valid.index
        if idx <= len(work) - 1 - max_horizon and idx <= current_idx - buffer_days
    ]
    if not eligible_idx:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "symbol": target,
            "market": market,
            "message": "이후 수익률을 계산할 수 있는 과거 유사 시점이 부족합니다.",
            "matches": [],
            "summary": {},
        }

    distances = ((z.loc[eligible_idx] - current_z) ** 2).sum(axis=1).pow(0.5)
    ranked = distances.sort_values().head(top_n)

    matches: list[dict[str, Any]] = []
    horizon_returns: dict[int, list[float]] = {h: [] for h in horizons}
    for idx, dist in ranked.items():
        row = work.loc[idx]
        base_close = float(row["close"])
        if not base_close:
            continue
        entry = {
            "date": str(row["date"]),
            "rsi": round(float(row["rsi"]), 2),
            "bbPercent": round(float(row["bbPercent"]), 3),
            "macdHistPct": round(float(row["macdHistPct"]), 3),
            "similarity": round(max(0.0, 1.0 - float(dist) / 4.0), 3),
            "returns": {},
        }
        for h in horizons:
            future_close = float(work.loc[idx + h, "close"])
            ret_pct = (future_close - base_close) / base_close * 100
            entry["returns"][f"d{h}"] = round(ret_pct, 2)
            horizon_returns[h].append(ret_pct)
        matches.append(entry)

    summary: dict[str, Any] = {}
    for h in horizons:
        rets = horizon_returns[h]
        if not rets:
            continue
        wins = sum(1 for r in rets if r > 0)
        summary[f"d{h}"] = {
            "count": len(rets),
            "winRate": round(wins / len(rets) * 100, 1),
            "avgReturn": round(sum(rets) / len(rets), 2),
            "medianReturn": round(float(np.median(rets)), 2),
            "bestReturn": round(max(rets), 2),
            "worstReturn": round(min(rets), 2),
        }

    return {
        "status": "OK",
        "symbol": target,
        "market": market,
        "source": source,
        "current": {
            "date": str(work.loc[current_idx, "date"]),
            "rsi": round(float(current_row["rsi"]), 2),
            "bbPercent": round(float(current_row["bbPercent"]), 3),
            "macdHistPct": round(float(current_row["macdHistPct"]), 3),
        },
        "matchCount": len(matches),
        "matches": matches,
        "summary": summary,
        "message": f"과거 {len(matches)}개 유사 시점 기준 통계이며 투자 조언이 아닙니다.",
    }




def _preferred_disclosure_files(market: str) -> list[Path]:
    mk = "kr" if market == "kr" else "us"
    candidates: list[Path] = []
    if mk == "kr":
        names = [
            DATA_DIR / "disclosures" / "disclosures_kr.csv",
            DATA_DIR / "stockapp" / "disclosures_kr.csv",
            REPORT_DIR / "disclosures_kr.csv",
        ]
    else:
        names = [
            DATA_DIR / "disclosures" / "disclosures_us.csv",
            DATA_DIR / "sec_recent_filings.csv",
            DATA_DIR / "stockapp" / "disclosures_us.csv",
            DATA_DIR / "stockapp" / "sec_recent_filings.csv",
            REPORT_DIR / "disclosures_us.csv",
            REPORT_DIR / "sec_recent_filings.csv",
        ]
    candidates.extend(names)
    for root in stockapp_roots():
        if mk == "kr":
            rels = [
                Path("data/disclosures/disclosures_kr.csv"),
                Path("disclosures/disclosures_kr.csv"),
                Path("reports/disclosures_kr.csv"),
                Path("disclosures_kr.csv"),
            ]
        else:
            rels = [
                Path("data/disclosures/disclosures_us.csv"),
                Path("data/sec_recent_filings.csv"),
                Path("disclosures/disclosures_us.csv"),
                Path("reports/disclosures_us.csv"),
                Path("reports/sec_recent_filings.csv"),
                Path("sec_recent_filings.csv"),
            ]
        candidates.extend(root / rel for rel in rels)
    existing = [p for p in candidates if p.exists() and p.is_file() and p.stat().st_size > 0]
    if not existing:
        exact_names = {"disclosures_kr.csv"} if mk == "kr" else {"disclosures_us.csv", "sec_recent_filings.csv"}
        for p in _find_data_files((r"disclosures", r"sec_recent_filings"), ("sector", "dart_corp", "corp_code", "company_code", "node_modules")):
            if p.name.lower() in exact_names:
                existing.append(p)
    return _unique_paths(existing)


def _disclosure_sort_key(item: dict[str, Any]) -> str:
    return _date_key(item.get("date") or item.get("raw", {}).get("date") or "")


def disclosure_rows(market: str) -> dict[str, Any]:
    out_file = _disclosure_output_file(market)
    if not out_file.exists() or rows_for(out_file) == 0:
        if (market == "kr" and os.environ.get("DART_API_KEY")) or (market == "us" and os.environ.get("FINNHUB_API_KEY")):
            try:
                refresh_disclosures(market=market, days=30)
            except Exception:
                pass
    files = _preferred_disclosure_files(market)
    items: list[dict[str, Any]] = []
    used_sources: list[str] = []
    seen: set[str] = set()
    for path in files[:12]:
        df = read_csv(path)
        if df.empty:
            continue
        source = source_label(path)
        if source not in used_sources:
            used_sources.append(source)
        for row in dataframe_records(df):
            symbol = normalize_symbol(first_value(row, ["stock_code", "종목코드", "ticker", "symbol", "code"], ""), market)
            # Only listed-market disclosures are useful for this stock app.  This
            # prevents DART corp-code master rows or broad SEC tables from flooding
            # the screen as if they were stock disclosures.
            if not symbol or not _symbol_belongs_to_market(symbol, market):
                continue
            if not _market_matches(row, market):
                market_text = first_value(row, ["market", "시장"], "")
                if market_text:
                    continue
            name = first_value(row, NAME_ALIASES + ["corp_name", "company", "회사명"], symbol)
            raw_title = first_value(row, ["title", "공시제목", "report_nm", "보고서명", "filingTitle", "form", "filing", "type"], "")
            form_type = first_value(row, ["form", "formType", "type", "filing", "filingType"], "")
            title = _clean_disclosure_title(raw_title or form_type, market)
            date = first_value(row, ["date", "공시일", "rcept_dt", "filing_date", "filedDate", "accepted", "acceptedDate", "게시일"], "")
            if not title and not date:
                continue
            source_name = first_value(row, ["source", "출처", "provider"], "DART" if market == "kr" else "SEC")
            url = first_value(row, ["url", "link", "공시링크", "html_url", "reportUrl", "filingUrl"], "")
            key = "|".join([market, symbol, _date_key(date), str(title).strip().lower(), str(form_type).strip().lower()])
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "market": market,
                "symbol": symbol,
                "name": name,
                "title": title or "공시 제목 없음",
                "date": date or "공시일 없음",
                "sourceName": source_name,
                "url": url,
                "status": "OK",
                "sourceFile": source,
                "raw": row,
            })
    items = sorted(items, key=_disclosure_sort_key, reverse=True)
    required_files = (
        ["data/disclosures/disclosures_kr.csv"]
        if market == "kr"
        else ["data/disclosures/disclosures_us.csv", "data/sec_recent_filings.csv", "stockapp://sec_recent_filings.csv"]
    )
    return {
        "status": "OK" if items else "MISSING",
        "market": market,
        "count": len(items),
        "sources": used_sources,
        "requiredFiles": required_files,
        "missingReason": "" if items else "시장에 맞는 상장 종목 공시 CSV 행을 찾지 못했습니다.",
        "items": items[:250],
    }

def _load_dart_financial_map(market: str) -> dict[str, dict[str, Any]]:
    """reports/dart_financial_data_kr.csv 에서 종목별 최신 재무 데이터 로드"""
    dart: dict[str, dict[str, Any]] = {}
    if market != "kr":
        return dart
    path = REPORT_DIR / "dart_financial_data_kr.csv"
    if not path.exists():
        return dart
    # read_csv returns DataFrame — dataframe_records로 변환
    df = read_csv(path)
    rows = dataframe_records(df) if hasattr(df, "iterrows") else (df if isinstance(df, list) else [])
    for row in rows:
        raw_sym = str(row.get("symbol", "")).strip()
        sym = normalize_symbol(raw_sym, market)
        year = str(row.get("year", ""))
        if not sym:
            continue
        existing = dart.get(sym)
        if existing is None or year > str(existing.get("year", "")):
            dart[sym] = dict(row)
            # 앞에 0 없는 버전도 등록
            sym_strip = sym.lstrip("0")
            if sym_strip and sym_strip not in dart:
                dart[sym_strip] = dict(row)
    return dart


def _compute_valuation_advanced(symbol: str, market: str, current_price: Any) -> dict[str, Any]:
    from app.services.valuation_advanced import compute_valuation
    return compute_valuation(symbol, market, current_price)


def company_analysis(market: str) -> dict[str, Any]:
    base_map = _combine_symbol_maps(market)
    company_map, company_sources = _latest_data_maps((r"company_integrated", r"company", r"기업"), market, ("news", "sector", "action", "pullback", "risk", "flow", "node_modules"))
    financial_map, financial_sources = _latest_data_maps((r"financial", r"fundamental", r"finance", r"재무", r"income", r"eps"), market, ("sector", "node_modules"))
    dart_map = _load_dart_financial_map(market)   # DART API 재무 데이터
    flow_map, flow_sources = _latest_data_maps((r"flow", r"supply", r"수급", r"investor"), market, ("sector", "node_modules"))
    source_list = []
    for src in company_sources + financial_sources + flow_sources:
        if src not in source_list:
            source_list.append(src)

    if not base_map:
        for item in symbols(market).get("items", []):
            raw = dict(item.get("raw", item))
            symbol = normalize_symbol(item.get("symbol"), market)
            if symbol:
                base_map[symbol] = raw

    items: list[dict[str, Any]] = []
    priority_symbols: list[str] = []
    for payload in (candidate_rows(market, "action"), candidate_rows(market, "pullback"), candidate_rows(market, "flow"), candidate_rows(market, "risk"), positions(market)):
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            symbol = normalize_symbol(item.get("symbol"), market)
            if symbol and _symbol_belongs_to_market(symbol, market) and symbol not in priority_symbols:
                priority_symbols.append(symbol)
    all_symbols = list(dict.fromkeys(priority_symbols + list(base_map.keys()) + list(company_map.keys()) + list(financial_map.keys())))
    seen_symbols: set[str] = set()
    for symbol in all_symbols:
        if not _symbol_belongs_to_market(symbol, market) or symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        merged = dict(base_map.get(symbol, {}))
        merged = _merge_alias_values(merged, company_map.get(symbol, {}))
        merged = _merge_alias_values(merged, financial_map.get(symbol, {}))
        merged = _merge_alias_values(merged, flow_map.get(symbol, {}))
        # DART API 재무 데이터 (가장 신뢰도 높음 — 덮어쓰기)
        dart_row = dart_map.get(symbol)
        if dart_row:
            for dart_key, csv_key in [
                ("roe", "ROE"), ("per", "PER"), ("pbr", "PBR"),
                ("debt_ratio", "debtRatio"), ("operating_margin", "operatingMargin"),
                ("revenue_growth", "revenueGrowth"), ("eps_growth", "epsGrowth"),
                ("peg", "peg"), ("quality_score", "qualityScore"),
                ("growth_score", "growthScore"), ("value_score", "valueScore"),
            ]:
                v = dart_row.get(dart_key)
                if v and str(v).strip() not in ("", "None", "nan"):
                    merged[csv_key] = v
                    merged[dart_key] = v
        merged = apply_quote_cache(merged, market)
        normalized = normalize_security_row(merged, market)
        eps = _display_value(merged, ["EPS", "eps", "주당순이익", "basic_eps", "diluted_eps"], "EPS 데이터 없음")
        per = _display_value(merged, ["PER", "per"], "PER 데이터 없음")
        pbr = _display_value(merged, ["PBR", "pbr"], "PBR 데이터 없음")
        roe = _display_value(merged, ["ROE", "roe"], "ROE 데이터 없음")
        revenue = _display_value(merged, ["매출", "매출액", "revenue", "sales"], "매출 데이터 없음")
        operating_income = _display_value(merged, ["영업이익", "operating_income", "op_income"], "영업이익 데이터 없음")
        net_income = _display_value(merged, ["순이익", "net_income", "당기순이익"], "순이익 데이터 없음")
        annual = _display_value(merged, ["연간실적", "annual_result", "annual_performance", "annual"], "연간실적 데이터 연결 대기")
        quarterly = _display_value(merged, ["분기실적", "quarter_result", "quarterly_performance", "quarterly"], "분기실적 데이터 연결 대기")
        esg = _display_value(merged, ["ESG", "esg", "ESG등급"], "ESG 데이터 연결 대기")
        research = _display_value(merged, ["리서치", "research", "report", "투자의견", "target_opinion"], "리서치 데이터 연결 대기")
        # DART 재무 정보 보강 (더 정확한 값으로 덮어씀)
        dart_row = dart_map.get(symbol) or {}
        def _dart_or(primary_key: str, dart_key: str, fallback: str) -> Any:
            dart_val = dart_row.get(dart_key) or dart_row.get(primary_key)
            if dart_val and str(dart_val).strip() not in ("", "None", "nan", "-"):
                return dart_val
            return _display_value(merged, [primary_key], fallback)

        per_final  = _dart_or("PER", "per", "PER 데이터 없음")
        pbr_final  = _dart_or("PBR", "pbr", "PBR 데이터 없음")
        roe_final  = _dart_or("ROE", "roe", "ROE 데이터 없음")
        peg_final  = dart_row.get("peg") or dart_row.get("peg") or ""
        debt_final = dart_row.get("debt_ratio") or ""
        op_margin  = dart_row.get("operating_margin") or ""
        rev_growth = dart_row.get("revenue_growth") or ""
        eps_growth = dart_row.get("eps_growth") or ""
        dart_quality = dart_row.get("quality_score") or ""
        dart_growth  = dart_row.get("growth_score") or ""
        has_dart = bool(dart_row)
        dart_year = dart_row.get("year") or ""

        # ── 절대가치 점검 / 부도위험·레버리지 (DCF·RIM·EVA·Altman Z·DOL/DFL/DCL) ──
        valuation_advanced = _compute_valuation_advanced(symbol, market, normalized.get("currentPrice"))

        # ── 누락 필드 계산 ────────────────────────────────────────────────
        _fin_vals = [("EPS", eps), ("PER", per_final), ("PBR", pbr_final), ("ROE", roe_final),
                     ("매출", revenue), ("영업이익", operating_income), ("순이익", net_income)]
        missing_fields = [name for name, v in _fin_vals if not v or any(x in str(v) for x in ("데이터 없음", "연결 대기", "원본 없음"))]

        # ── 퀀트/기술분석 점수 (추천 파일 or 통합 파일에서) ──────────────
        def _qnum(keys: list[str]) -> float | None:
            for k in keys:
                v = merged.get(k)
                if v and str(v).strip() not in ("", "None", "nan", "-", "0"):
                    try:
                        return float(str(v).replace("%", "").replace(",", "").strip())
                    except Exception:
                        pass
            return None
        quant_score   = _qnum(["finalScore", "opportunityScore", "finalRankScore", "종합점수"])
        quant_entry   = _qnum(["entryScore", "가치점수"])
        quant_risk    = _qnum(["riskScore", "안정성점수"])
        quant_growth  = _qnum(["upsideScore", "성장점수"])
        quant_prob    = _qnum(["probability"])
        surge_label   = str(merged.get("surgeLabel") or "")
        has_quant     = quant_score is not None

        # ── connectionStatus 결정 ─────────────────────────────────────────
        if has_dart:
            conn_status = "재무(DART) 연결"
        elif not missing_fields:
            conn_status = "정상"
        elif has_quant:
            conn_status = "퀀트 분석 가능"
        else:
            conn_status = "재무 원본 없음"

        items.append({
            "symbol": normalized.get("symbol", symbol),
            "name": normalized.get("name", symbol),
            "market": market,
            "currentPriceText": normalized.get("currentPriceText", "현재가 없음"),
            "priceTime": normalized.get("priceTime", ""),
            "priceSource": normalized.get("priceSource", ""),
            "supply": normalized.get("scores", {}).get("supply", "수급 데이터 없음"),
            "earnings": normalized.get("scores", {}).get("earnings", "재무 데이터 없음"),
            "valuation": normalized.get("scores", {}).get("valuation", "재무 데이터 없음"),
            "chart": normalized.get("scores", {}).get("chart", "차트 데이터 부족"),
            "flowStatus": normalized.get("statuses", {}).get("flow", "수급 데이터 없음"),
            "earningsStatus": normalized.get("statuses", {}).get("earnings", "재무 데이터 없음"),
            "valuationStatus": normalized.get("statuses", {}).get("valuation", "재무 데이터 없음"),
            "dataStatus": "DART" if has_dart else normalized.get("dataStatus", "상태 없음"),
            "dartYear": dart_year,
            "hasDartData": has_dart,
            "eps": eps,
            "per": per_final,
            "pbr": pbr_final,
            "roe": roe_final,
            "peg": peg_final,
            "debtRatio": debt_final,
            "operatingMargin": op_margin,
            "revenueGrowth": rev_growth,
            "epsGrowth": eps_growth,
            "qualityScore": dart_quality,
            "growthScore": dart_growth,
            "revenue": revenue,
            "operatingIncome": operating_income,
            "netIncome": net_income,
            "annualPerformance": annual,
            "quarterlyPerformance": quarterly,
            "incomeStatementStatus": "손익계산서 연결" if any("데이터" not in str(v) and "대기" not in str(v) for v in (revenue, operating_income, net_income, annual, quarterly)) else "손익계산서 데이터 연결 대기",
            "esg": esg,
            "research": research,
            # ── 퀀트 분석 ──────────────────────────────────────────────────
            "quantScore": quant_score,
            "quantEntryScore": quant_entry,
            "quantRiskScore": quant_risk,
            "quantGrowthScore": quant_growth,
            "quantProbability": quant_prob,
            "surgeLabel": surge_label,
            "hasQuantData": has_quant,
            # ── 연결 상태 ──────────────────────────────────────────────────
            "missingFields": missing_fields,
            "connectionStatus": conn_status,
            "valuationAdvanced": valuation_advanced,
            "raw": merged,
        })
        if len(items) >= 120:
            break
    required_files = (
        [
            "data/kr_financial_metrics.csv",
            "data/kr_market_cap_cache.csv",
            "data/disclosures/disclosures_kr.csv",
            "reports/v92_financial_statement_kr.csv",
            "reports/v92_kpi_cards_kr.csv",
            "reports/v92_symbol_snapshot_kr.csv",
        ]
        if market == "kr"
        else [
            "data/sec_recent_filings.csv",
            "data/disclosures/disclosures_us.csv",
            "data/us_financial_metrics.csv",
            "reports/v92_symbol_snapshot_us.csv",
        ]
    )
    quality = _company_financial_quality(items)
    return {
        "status": quality["status"],
        "market": market,
        "count": len(items),
        "source": " · ".join(source_list[:6]) if source_list else "symbols fallback",
        "sources": source_list[:12],
        "requiredFiles": required_files,
        "financialCompleteness": quality,
        "message": quality["note"] if items else "필요 파일 감지 대기",
        "missingReason": "" if items else "시장에 맞는 기업/재무 CSV 행을 찾지 못했습니다.",
        "items": items,
    }


def _execution_status_for_plan(current: float | None, entry: float | None, mode: str) -> str:
    settings = TRADE_MODE_SETTINGS.get(mode, TRADE_MODE_SETTINGS["balanced"])
    if current is None or entry is None or entry <= 0:
        return "체결 판단 불가"
    gap = (current - entry) / entry
    tol = float(settings.get("entry_tolerance_pct", 0.01) or 0.0)
    if mode == "conservative":
        if current <= entry * (1 + 0.003):
            return "체결 가능"
        if current <= entry * 1.02:
            return "대기"
        return "추격 부담"
    if mode == "aggressive":
        if gap <= tol:
            return "체결 가능"
        if gap <= 0.08:
            return "공격 검토"
        return "추격 부담"
    if abs(gap) <= tol:
        return "체결 가능"
    if gap > tol:
        return "대기"
    return "기준가 아래"


def virtual_portfolio_summary(market: str, mode: str = "balanced") -> dict[str, Any]:
    if mode not in TRADE_MODE_SETTINGS:
        mode = "balanced"
    settings = TRADE_MODE_SETTINGS[mode]
    max_positions = {"conservative": 3, "balanced": 5, "aggressive": 8}.get(mode, 5)
    universe = candidate_rows(market, "action").get("items", []) + candidate_rows(market, "pullback").get("items", []) + candidate_rows(market, "flow").get("items", [])
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for item in universe:
        symbol = normalize_symbol(item.get("symbol"), market)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        modes = item.get("recommendationModes") or []
        if mode not in modes and mode != "aggressive":
            continue
        plan = (item.get("virtualPlans") or {}).get(mode) or {}
        if plan.get("status") != "OK":
            continue
        selected.append({"item": item, "plan": plan})
        if len(selected) >= max_positions:
            break

    capital_per_position = float(settings["capital_us"] if market == "us" else settings["capital_kr"])
    total_capital = capital_per_position * max_positions
    invested = sum(float(row["plan"].get("invested", 0) or 0) for row in selected)
    loss_total = sum(float(row["plan"].get("lossTotal", 0) or 0) for row in selected)
    profit_total = sum(float(row["plan"].get("profitTotal", 0) or 0) for row in selected)
    cash = max(0.0, total_capital - invested)
    loss_pct = (loss_total / total_capital * 100) if total_capital else 0
    profit_pct = (profit_total / total_capital * 100) if total_capital else 0

    cards = [
        {"label": "추천 모드", "value": settings["label"], "note": settings["buy_rule"]},
        {"label": "최대 보유", "value": f"{max_positions}종목", "note": f"종목당 {format_price(capital_per_position, market)} 기준"},
        {"label": "손절 시 손실", "value": format_signed_money(loss_total, market), "note": format_percent(loss_pct)},
        {"label": "목표 도달 시 이익", "value": format_signed_money(profit_total, market), "note": format_percent(profit_pct)},
        {"label": "잔여 현금", "value": format_price(cash, market), "note": "정수 수량 계산 후 잔여"},
    ]
    items = []
    for row in selected:
        item = row["item"]
        plan = row["plan"]
        items.append({
            "symbol": item.get("symbol", ""),
            "name": item.get("name", item.get("symbol", "")),
            "swingGrade": item.get("swingGrade", "스윙 C군"),
            "currentPrice": item.get("currentPriceText", "현재가 없음"),
            "entry": plan.get("entryText", "예상 매수가 산출 필요"),
            "shares": plan.get("sharesText", "수량 산출 필요"),
            "invested": plan.get("investedText", "투입금 산출 필요"),
            "loss": plan.get("lossTotalText", "손실 산출 필요"),
            "profit": plan.get("profitTotalText", "이익 산출 필요"),
            "accountLossPct": plan.get("accountLossPctText", "운용 손실률 산출 필요"),
            "accountProfitPct": plan.get("accountProfitPctText", "운용 수익률 산출 필요"),
            "executionStatus": _execution_status_for_plan(item.get("currentPrice"), item.get("entry"), mode),
            "buyRule": plan.get("buyRule", settings["buy_rule"]),
            "holdDays": plan.get("holdDays", settings["hold_days"]),
        })
    return {
        "market": market,
        "mode": mode,
        "modeLabel": settings["label"],
        "maxPositions": max_positions,
        "capitalPerPosition": format_price(capital_per_position, market),
        "totalCapital": format_price(total_capital, market),
        "invested": format_price(invested, market),
        "cash": format_price(cash, market),
        "lossTotal": format_signed_money(loss_total, market),
        "profitTotal": format_signed_money(profit_total, market),
        "lossPct": format_percent(loss_pct),
        "profitPct": format_percent(profit_pct),
        "cards": cards,
        "count": len(items),
        "items": items,
        "note": "StockApp 원본 데이터는 데이터 피드로만 사용하며, 후보 분류와 성향별 가상운용은 MONE 기준으로 재계산합니다.",
    }

def virtual_operation_preview(market: str, mode: str = "balanced") -> dict[str, Any]:
    if mode not in TRADE_MODE_SETTINGS:
        mode = "balanced"
    rows = []
    universe = candidate_rows(market, "action").get("items", []) + candidate_rows(market, "pullback").get("items", []) + candidate_rows(market, "flow").get("items", [])
    seen: set[str] = set()
    for item in universe:
        symbol = normalize_symbol(item.get("symbol"), market)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        modes = item.get("recommendationModes") or []
        if mode not in modes and mode != "aggressive":
            continue
        plan = (item.get("virtualPlans") or {}).get(mode) or {}
        rows.append({
            "symbol": symbol,
            "name": item.get("name", symbol),
            "swingGrade": item.get("swingGrade", "스윙 C군"),
            "mode": mode,
            "modeLabel": TRADE_MODE_SETTINGS[mode]["label"],
            "currentPrice": item.get("currentPriceText", "현재가 없음"),
            "entry": plan.get("entryText", item.get("entryText", "기준가 산출 필요")),
            "shares": plan.get("sharesText", "수량 산출 필요"),
            "invested": plan.get("investedText", "투입금 산출 필요"),
            "loss": plan.get("lossTotalText", "손실 산출 필요"),
            "profit": plan.get("profitTotalText", "이익 산출 필요"),
            "accountLossPct": plan.get("accountLossPctText", "운용 손실률 산출 필요"),
            "accountProfitPct": plan.get("accountProfitPctText", "운용 수익률 산출 필요"),
            "buyRule": plan.get("buyRule", "매수 기준 없음"),
            "holdDays": plan.get("holdDays", "보유기간 없음"),
            "executionStatus": _execution_status_for_plan(item.get("currentPrice"), item.get("entry"), mode),
            "summary": plan.get("summary", "가상 운용 산출 필요"),
        })
    return {"market": market, "mode": mode, "modeLabel": TRADE_MODE_SETTINGS[mode]["label"], "count": len(rows), "items": rows[:80]}



def virtual_conditional_plan(market: str, mode: str = "balanced") -> dict[str, Any]:
    preview = virtual_operation_preview(market, mode)
    portfolio = virtual_portfolio_summary(market, mode)
    return {
        "market": market,
        "mode": mode,
        "modeLabel": preview.get("modeLabel", ""),
        "title": "조건부 가상운용 계획",
        "source": f"reports/mone_v36_virtual_trade_plan_{market}.csv",
        "summarySource": f"reports/mone_v36_virtual_trade_summary_{market}.csv",
        "rule": "추천됨 ≠ 매수됨 · 진입가 도달 시 체결 · 미도달 시 미체결 · 체결된 종목만 손익 계산",
        "count": preview.get("count", 0),
        "items": preview.get("items", []),
        "portfolio": portfolio,
    }

def data_source_status() -> dict[str, Any]:
    groups = [
        {
            "key": "chart",
            "name": "차트/OHLCV",
            "patterns": (r"ohlcv", r"daily", r"chart"),
            "exclude": ("node_modules",),
            "target": "차트·기술분석 > 차트 보기",
        },
        {
            "key": "flow",
            "name": "수급/거래대금",
            "patterns": (r"flow", r"supply", r"수급", r"investor", r"volume"),
            "exclude": ("node_modules",),
            "target": "장중 체크 / 오늘 매수 검토 / 기업분석",
        },
        {
            "key": "orderbook",
            "name": "호가/체결",
            "patterns": (r"orderbook", r"quote", r"quotes", r"bid", r"ask", r"호가", r"체결"),
            "exclude": ("node_modules", "quotes_cache"),
            "target": "장중 체크 / 오늘 매수 검토",
        },
        {
            "key": "disclosure",
            "name": "공시",
            "patterns": (r"disclosure", r"filing", r"dart", r"sec", r"공시"),
            "exclude": ("sector", "dart_corp"),
            "target": "뉴스·기업분석 > 공시",
        },
    ]
    items = []
    for group in groups:
        files = _find_data_files(group["patterns"], group["exclude"])
        csv_files = [path for path in files if path.suffix.lower() == ".csv"]
        latest = max((file_mtime(path) for path in files if path.exists()), default="")
        row_count = sum(rows_for(path) for path in csv_files[:20])
        has_rows = bool(csv_files and row_count > 0)
        items.append({
            "key": group["key"],
            "name": group["name"],
            "status": "OK" if has_rows else "MISSING",
            "files": len(files),
            "csvFiles": len(csv_files),
            "rows": int(row_count),
            "latestUpdatedAt": latest,
            "target": group["target"],
            "examples": [source_label(path) for path in files[:5]],
            "message": "표시 가능한 CSV 행이 감지됨" if has_rows else "API 키/워크플로가 있어도 저장된 CSV 행이 없으면 앱에 표시할 데이터가 없습니다. 공시는 관리/공시 화면에서 수집을 실행하세요.",
        })
    bridge = stockapp_bridge_status()
    roots = bridge.get("roots", [])
    items.append({
        "key": "stockapp_bridge",
        "name": "StockApp 브릿지",
        "status": bridge.get("status", "NOT_FOUND"),
        "files": sum(root.get("csvFiles", 0) for root in roots),
        "csvFiles": sum(root.get("csvFiles", 0) for root in roots),
        "rows": 0,
        "latestUpdatedAt": max((root.get("latestUpdatedAt", "") for root in roots), default=""),
        "target": "MONE 데이터 부족 시 기존 StockApp 작업스케줄러 결과를 fallback으로 사용",
        "examples": [ex for root in roots for ex in root.get("examples", [])][:5],
        "message": bridge.get("message", ""),
    })
    handoff = source_handoff()
    items.append({
        "key": "source_handoff",
        "name": "Source handoff",
        "status": "OK" if SOURCE_HANDOFF_FILE.exists() else "MISSING",
        "files": 1 if SOURCE_HANDOFF_FILE.exists() else 0,
        "csvFiles": 0,
        "rows": 0,
        "latestUpdatedAt": file_mtime(SOURCE_HANDOFF_FILE),
        "target": "Before handoff use StockApp snapshot; after handoff use GitHub Actions",
        "examples": [source_label(SOURCE_HANDOFF_FILE)],
        "message": f"KR={preferred_source_type('kr', handoff.get('kr_handoff_date'))}, US={preferred_source_type('us', handoff.get('us_handoff_date'))}, handoff_at_kst={handoff.get('handoff_at_kst')}",
    })
    return {"items": items}


# ── GitHub raw 폴백 / 파일 신선도 보장 ───────────────────────────────────

_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/selene0519/agnas-stock-app/main"
_GITHUB_CACHE_TTL = 3600  # 1시간 캐시
_github_fetch_lock = _threading.Lock()


def _refresh_from_github(rel_path: str) -> bool:
    """GitHub raw에서 최신 파일 가져오기 (백그라운드 호출용)"""
    target = REPO_ROOT / rel_path
    try:
        url = f"{_GITHUB_RAW_BASE}/{rel_path}"
        req = _url_req.Request(url, headers={"User-Agent": "MONE-DataLoader/1.0"})
        with _url_req.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(resp.read())
                return True
    except Exception:
        pass
    return False


def ensure_fresh(path: Path, max_age_hours: float = 1.0) -> Path:
    """
    파일이 없거나 오래된 경우 GitHub raw에서 백그라운드 갱신.
    TTL: 1시간 (작업스케줄러 장전·장후 수집과 동기화)
    1순위: 로컬 파일 (신선할 때)
    2순위: GitHub raw 다운로드 후 로컬 캐시 (백그라운드, 응답 속도 영향 없음)
    항상 로컬 Path 반환 (없으면 원래 path 반환하여 상위에서 처리)
    """
    max_age_sec = max_age_hours * 3600
    needs_refresh = (
        not path.exists()
        or (time.time() - path.stat().st_mtime) > max_age_sec
    )
    if not needs_refresh:
        return path
    try:
        rel = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path

    def _bg() -> None:
        with _github_fetch_lock:
            _refresh_from_github(rel)

    _threading.Thread(target=_bg, daemon=True).start()
    return path  # 현재 있는 파일 우선 반환 (없으면 None 처리는 호출부에서)


def force_refresh_recommendations(market: str = "kr") -> int:
    """
    추천 CSV 파일 즉시 강제 갱신 (작업스케줄러 push 후 호출용).
    로컬 파일 mtime을 0으로 리셋 → 다음 ensure_fresh() 호출 시 즉시 재다운로드.
    반환: 갱신 대상 파일 수
    """
    pattern = f"mone_v36_final_recommendations_{market}_*.csv"
    count = 0
    for p in REPORT_DIR.glob(pattern):
        try:
            import os as _os
            _os.utime(str(p), (0, 0))  # mtime을 1970년으로 리셋
            count += 1
        except Exception:
            pass
    return count
