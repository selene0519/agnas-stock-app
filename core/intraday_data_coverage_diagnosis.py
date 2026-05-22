from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.market_session_engine import current_session_for_market

from core.intraday_orderbook_engine import _is_kr_market, _is_us_market, _normalize_kr_symbol, _normalize_us_symbol, _truthy as _ob_truthy
from core.intraday_realtime_engine import _is_us_market, _kr_market_session, _market_session, summarize_us_quote_source_counts
from core.swing_candidate_io import read_swing_candidate_csv


REPORT_DIR = Path("reports")
COVERAGE_DIAGNOSIS_JSON = REPORT_DIR / "intraday_data_coverage_diagnosis.json"
COVERAGE_DIAGNOSIS_CSV = REPORT_DIR / "intraday_data_coverage_diagnosis.csv"
UNSUPPORTED_SYMBOLS_CSV = REPORT_DIR / "intraday_unsupported_symbols.csv"
IMPROVEMENT_SUGGESTIONS_JSON = REPORT_DIR / "intraday_data_improvement_suggestions.json"

REPORT_PATHS = {
    "realtime_summary": REPORT_DIR / "intraday_realtime_summary.json",
    "realtime_snapshot": REPORT_DIR / "intraday_realtime_snapshot.csv",
    "orderbook_summary": REPORT_DIR / "intraday_orderbook_summary.json",
    "orderbook_snapshot": REPORT_DIR / "intraday_orderbook_snapshot.csv",
    "flow_summary": REPORT_DIR / "intraday_flow_summary.json",
    "flow_snapshot": REPORT_DIR / "intraday_flow_snapshot.csv",
    "sector_summary": REPORT_DIR / "intraday_sector_flow_summary.json",
    "sector_report": REPORT_DIR / "intraday_sector_flow_report.csv",
}
CANDIDATE_PATHS = {
    "us_a": REPORT_DIR / "swing_candidates_us_A_top3.csv",
    "us_b": REPORT_DIR / "swing_candidates_us_B_watch.csv",
    "us_c": REPORT_DIR / "swing_candidates_us_C_excluded.csv",
    "kr_a": REPORT_DIR / "swing_candidates_kr_A_top3.csv",
    "kr_b": REPORT_DIR / "swing_candidates_kr_B_watch.csv",
    "kr_c": REPORT_DIR / "swing_candidates_kr_C_excluded.csv",
}

COVERAGE_COLUMNS = [
    "symbol",
    "market",
    "source_group",
    "quote_available",
    "quote_partial_available",
    "quote_full_available",
    "orderbook_available",
    "flow_available",
    "sector_flow_available",
    "quote_status",
    "orderbook_status",
    "flow_status",
    "quote_source",
    "quote_failure_reason",
    "orderbook_failure_reason",
    "flow_failure_reason",
    "normalized_symbol",
    "symbol_format_valid",
    "market_session",
    "likely_root_cause",
    "recoverable",
    "recommended_action",
    "updated_at",
]

ROOT_CAUSES = {
    "market_closed",
    "pre_market_not_open",
    "after_market",
    "unsupported_market",
    "unsupported_quote_api",
    "us_quote_api_response_empty",
    "invalid_symbol",
    "api_response_empty",
    "quote_api_response_empty",
    "quote_partial_fallback",
    "endpoint_not_configured",
    "kr_flow_endpoint_not_configured",
    "kr_flow_request_failed",
    "kr_flow_response_empty",
    "kr_flow_parser_failed",
    "kr_flow_missing_required_fields",
    "kr_flow_symbol_format_error",
    "kr_flow_market_closed",
    "kr_flow_unsupported_endpoint",
    "kr_flow_permission_or_env_error",
    "rate_limited",
    "parser_error",
    "no_target",
    "no_data",
    "data_available",
    "unknown",
}

UNRECOVERABLE_CAUSES = {
    "unsupported_market", "unsupported_quote_api", "market_closed", "no_target",
    "kr_flow_market_closed", "kr_flow_unsupported_endpoint",
}
RECOVERABLE = {
    "invalid_symbol",
    "parser_error",
    "endpoint_not_configured",
    "kr_flow_endpoint_not_configured",
    "kr_flow_request_failed",
    "kr_flow_response_empty",
    "kr_flow_parser_failed",
    "kr_flow_missing_required_fields",
    "kr_flow_symbol_format_error",
    "kr_flow_permission_or_env_error",
    "api_response_empty",
    "quote_api_response_empty",
    "us_quote_api_response_empty",
    "rate_limited",
    "no_data",
}
ISSUE_ROOT_CAUSES = ROOT_CAUSES - {"data_available"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "1.0", "yes", "y"}


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        if path.exists() and path.stat().st_size > 0:
            return pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except Exception:
        pass
    return pd.DataFrame()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _normalize_reason(value: Any) -> str:
    raw = str(value or "").strip()
    text = raw.lower()
    if not text or text in {"nan", "none", "nat", "-"}:
        return ""
    if text in ROOT_CAUSES:
        return text
    if text.startswith("kr_flow_"):
        return text
    if "unsupported_quote_api" in text or "quote_api" in text and "미지원" in raw:
        return "unsupported_quote_api"
    if "us_quote_api_response_empty" in text:
        return "us_quote_api_response_empty"
    if "unsupported_market" in text or ("미지원" in raw and "호가" in raw):
        return "unsupported_market"
    if "미국주식 현재가 api" in text.lower() or ("미국" in raw and "현재가" in raw and "api" in text.lower()):
        return "us_quote_api_response_empty"
    if "market_closed" in text or "장 마감" in raw or "장전" in raw:
        return "market_closed"
    if "invalid_symbol" in text or "종목코드" in raw:
        return "invalid_symbol"
    if "endpoint_not_configured" in text:
        return "endpoint_not_configured"
    if "parser" in text or "파싱" in raw:
        return "parser_error"
    if "rate_limited" in text or "호출 제한" in raw:
        return "rate_limited"
    if "api" in text and ("없음" in raw or "empty" in text or "no_data" in text):
        return "api_response_empty"
    if text in {"success", "ok"}:
        return ""
    if text in {"no_data", "unsupported"}:
        return text
    return text


def is_fully_available(row: dict[str, Any]) -> bool:
    quote_full = _truthy(row.get("quote_full_available"))
    if not quote_full and _truthy(row.get("quote_available")):
        quote_full = _truthy(row.get("intraday_data_available")) and not _truthy(row.get("quote_fallback_used"))
    return quote_full and _truthy(row.get("orderbook_available")) and _truthy(row.get("flow_available"))


def is_recoverable_issue(row: dict[str, Any]) -> bool:
    root = str(row.get("likely_root_cause", "")).strip()
    if root in {"data_available", "quote_partial_fallback"}:
        return False
    if is_fully_available(row):
        return False
    return str(row.get("recoverable", "")).strip().lower() == "true"


def is_issue_row(row: dict[str, Any]) -> bool:
    root = str(row.get("likely_root_cause", "")).strip()
    return root not in {"", "data_available", "nan", "none"}


def _status_from_row(available: bool, fetch_status: str, failure_reason: str) -> str:
    if available:
        return "success"
    status = _normalize_reason(fetch_status) or _normalize_reason(failure_reason)
    if status in ROOT_CAUSES:
        return status
    if status in {"unsupported", "no_data"}:
        return "unsupported" if status == "unsupported" else "no_data"
    return status or "unknown"


def _symbol_format(symbol: str, market: str) -> tuple[str, bool]:
    if _is_kr_market(market):
        return _normalize_kr_symbol(symbol)
    if _is_us_market(market):
        return _normalize_us_symbol(symbol)
    cleaned = str(symbol or "").strip().upper()
    return cleaned, bool(cleaned)


def _load_source_groups() -> dict[tuple[str, str], str]:
    mapping: dict[tuple[str, str], str] = {}
    for key, path in CANDIDATE_PATHS.items():
        df = read_swing_candidate_csv(path)
        if df.empty:
            continue
        if key.endswith("_a"):
            group = "A_candidate"
        elif key.endswith("_b"):
            group = "B_watch"
        elif key.endswith("_c"):
            group = "C_excluded_sample"
        else:
            group = "unknown"
        symbol_col = "symbol" if "symbol" in df.columns else ("ticker" if "ticker" in df.columns else "")
        if not symbol_col:
            continue
        for _, row in df.iterrows():
            sym = str(row.get(symbol_col, "")).strip().upper()
            market = str(row.get("market", "")).strip()
            if not sym:
                continue
            if group == "C_excluded_sample":
                strong = False
                for col in ["strong_watch_candidate", "weak_market_leader_flag"]:
                    if col in row.index:
                        strong = strong or _truthy(row.get(col))
                if "forecast_label" in row.index:
                    strong = strong or "강한 관찰" in str(row.get("forecast_label", ""))
                if strong:
                    current = mapping.get((sym, market), "")
                    if current in {"", "unknown", "C_excluded_sample"}:
                        mapping[(sym, market)] = "strong_watch"
                    continue
            current = mapping.get((sym, market), "")
            priority = {
                "A_candidate": 5,
                "B_watch": 4,
                "strong_watch": 3,
                "C_excluded_sample": 2,
                "unknown": 1,
            }
            if priority.get(group, 0) >= priority.get(current, 0):
                mapping[(sym, market)] = group
            mapping[(sym, "")] = mapping.get((sym, market), group)
    return mapping


def _sector_available_lookup(sector_report: pd.DataFrame, candidates: dict[tuple[str, str], str]) -> dict[tuple[str, str], bool]:
    sector_ok: set[str] = set()
    if not sector_report.empty and "sector" in sector_report.columns:
        work = sector_report.copy()
        if "sector_target_count" in work.columns:
            counts = pd.to_numeric(work["sector_target_count"], errors="coerce").fillna(0)
            work = work.loc[counts > 0]
        sector_ok = set(work["sector"].astype(str).str.strip()) - {"", "nan", "미분류"}
    lookup: dict[tuple[str, str], bool] = {}
    for path in CANDIDATE_PATHS.values():
        df = read_swing_candidate_csv(path)
        if df.empty:
            continue
        symbol_col = "symbol" if "symbol" in df.columns else ("ticker" if "ticker" in df.columns else "")
        if not symbol_col:
            continue
        for _, row in df.iterrows():
            sym = str(row.get(symbol_col, "")).strip().upper()
            market = str(row.get("market", "")).strip()
            sector = str(row.get("sector", "") or row.get("industry", "")).strip()
            available = bool(sector and sector in sector_ok)
            if sym:
                lookup[(sym, market)] = available
                lookup[(sym, "")] = lookup.get((sym, ""), False) or available
    return lookup


def load_intraday_reports() -> dict[str, Any]:
    reports: dict[str, Any] = {
        "paths": {k: str(v) for k, v in REPORT_PATHS.items()},
        "candidate_paths": {k: str(v) for k, v in CANDIDATE_PATHS.items()},
        "missing_reports": [],
    }
    for name, path in REPORT_PATHS.items():
        key = name.split("_")[0] if "_" in name else name
        if name.endswith("_summary"):
            reports[name] = _read_json(path)
            if not reports[name]:
                reports["missing_reports"].append(str(path))
        else:
            reports[name] = _read_csv(path)
            if reports[name].empty:
                reports["missing_reports"].append(str(path))
    reports["source_groups"] = _load_source_groups()
    reports["sector_lookup"] = _sector_available_lookup(
        reports.get("sector_report", pd.DataFrame()),
        reports["source_groups"],
    )
    return reports


def classify_quote_root_cause(row: dict[str, Any]) -> str:
    quote_full = _truthy(row.get("quote_full_available"))
    quote_partial = _truthy(row.get("quote_partial_available"))
    quote_ok = _truthy(row.get("quote_available")) or quote_full or quote_partial
    market = str(row.get("market", "")).strip()
    session = str(row.get("market_session", "") or _market_session(market)).strip().lower()
    quote_reason = _normalize_reason(row.get("quote_failure_reason")) or _normalize_reason(row.get("quote_status"))
    intraday_reason = str(row.get("intraday_failure_reason", "") or "")

    if quote_full:
        return "data_available"
    if quote_partial and not quote_full:
        source = str(row.get("quote_source", "") or "").strip().lower()
        if source == "kis_us_quote":
            return "data_available"
        return "quote_partial_fallback"
    if not _truthy(row.get("symbol_format_valid")):
        return "invalid_symbol"
    if session == "closed" or quote_reason == "market_closed" or "market_closed" in _normalize_reason(intraday_reason):
        return "market_closed"
    if not quote_ok:
        if quote_reason == "unsupported_quote_api":
            return "unsupported_quote_api"
        if quote_reason in {"api_response_empty", "no_data", "retry_response_empty", "fallback_unavailable"}:
            return "us_quote_api_response_empty" if _is_us_market(market) else "quote_api_response_empty"
        if _is_us_market(market):
            return "us_quote_api_response_empty"
        return "quote_api_response_empty"
    return "data_available"


def classify_orderbook_root_cause(row: dict[str, Any]) -> str:
    if _truthy(row.get("orderbook_available")):
        return "data_available"
    market = str(row.get("market", "")).strip()
    session = str(row.get("market_session", "") or _market_session(market)).strip().lower()
    reason = _normalize_reason(row.get("orderbook_failure_reason")) or _normalize_reason(row.get("orderbook_status"))
    if session == "closed" or reason in {"market_closed", "pre_market_not_open", "after_market"}:
        return "market_closed"
    if _is_us_market(market):
        if reason in ROOT_CAUSES - {"unsupported_market"}:
            return reason
        return "api_response_empty" if reason in {"", "unknown", "no_data"} else reason
    if reason in ROOT_CAUSES:
        return reason
    return reason or "unknown"


def classify_flow_root_cause(row: dict[str, Any]) -> str:
    if _truthy(row.get("flow_available")):
        return "data_available"
    market = str(row.get("market", "")).strip()
    session = str(row.get("market_session", "") or _market_session(market)).strip().lower()
    reason = _normalize_reason(row.get("flow_failure_reason")) or _normalize_reason(row.get("flow_status"))
    if session == "closed" or reason == "market_closed":
        return "market_closed"
    if _is_us_market(market):
        if reason in ROOT_CAUSES - {"unsupported_market"}:
            return reason
        return "api_response_empty" if reason in {"", "unknown", "no_data"} else reason
    if reason in ROOT_CAUSES:
        return reason
    return reason or "unknown"


def classify_missing_reason(row: dict[str, Any]) -> dict[str, Any]:
    quote_full = _truthy(row.get("quote_full_available"))
    quote_partial = _truthy(row.get("quote_partial_available"))
    quote_ok = _truthy(row.get("quote_available")) or quote_full or quote_partial
    orderbook_ok = _truthy(row.get("orderbook_available"))
    flow_ok = _truthy(row.get("flow_available"))
    market = str(row.get("market", "")).strip()
    session = str(row.get("market_session", "") or _market_session(market)).strip().lower()
    symbol_valid = _truthy(row.get("symbol_format_valid"))

    quote_reason = _normalize_reason(row.get("quote_failure_reason"))
    orderbook_reason = _normalize_reason(row.get("orderbook_failure_reason"))
    flow_reason = _normalize_reason(row.get("flow_failure_reason"))
    quote_status = _normalize_reason(row.get("quote_status"))
    orderbook_status = _normalize_reason(row.get("orderbook_status"))
    flow_status = _normalize_reason(row.get("flow_status"))

    reasons = [r for r in [quote_reason, orderbook_reason, flow_reason, quote_status, orderbook_status, flow_status] if r]

    if quote_full and orderbook_ok and flow_ok:
        root = "data_available"
        recoverable = "False"
        action = "정상 수신"
        if not _truthy(row.get("sector_flow_available")):
            action = "정상 수신 (업종 흐름만 표본 부족 시 sector 매핑 확인)"
        return {
            "likely_root_cause": root,
            "recoverable": recoverable,
            "recommended_action": action,
        }
    if quote_partial and (orderbook_ok or flow_ok) and not quote_full:
        source = str(row.get("quote_source", "") or row.get("quote_fallback_source", "")).strip()
        root = "quote_partial_fallback"
        recoverable = "False"
        if source == "kis_us_quote":
            action = "미국주식 현재가 KIS 수신 성공. 거래량/거래대금은 KIS 응답에 없거나 미수신"
        elif source == "finnhub_quote":
            action = "KIS 실패 후 Finnhub 보조 수신. 거래량/거래대금은 API 미제공"
        elif source in {"csv_fallback"} or source.startswith("fallback_"):
            action = f"저장 가격 fallback 사용({source}): 거래량/거래대금 미수신"
        else:
            action = (
                f"가격 fallback 사용({source or 'unknown'}): 거래량/거래대금은 API 미수신으로 장중 판단 제한"
            )
        return {
            "likely_root_cause": root,
            "recoverable": recoverable,
            "recommended_action": action,
        }
    if not symbol_valid or "invalid_symbol" in reasons:
        root = "invalid_symbol"
        recoverable = "True"
        action = "한국주식 6자리 종목코드 문자열 유지 필요"
        return {
            "likely_root_cause": root,
            "recoverable": recoverable,
            "recommended_action": action,
        }
    if not quote_ok and session != "closed" and "market_closed" not in reasons:
        sym = str(row.get("normalized_symbol") or row.get("symbol", "")).strip()
        if _is_us_market(market):
            if quote_reason == "unsupported_quote_api":
                root = "unsupported_quote_api"
                recoverable = "False"
                action = "미국주식 현재가 API가 해당 심볼을 지원하지 않습니다. 후보 CSV 가격 fallback만 검토하세요."
            else:
                root = "us_quote_api_response_empty"
                recoverable = "True"
                action = (
                    f"미국주식 현재가 API endpoint/파라미터/fallback 확인"
                    f"{f' ({sym})' if sym else ''}"
                )
        else:
            root = "quote_api_response_empty"
            recoverable = "True"
            action = (
                f"장중 현재가/거래대금 quote API 재조회 또는 fallback 확인"
                f"{f' ({sym})' if sym else ''}"
            )
        return {
            "likely_root_cause": root,
            "recoverable": recoverable,
            "recommended_action": action,
        }
    if (session == "closed" or "market_closed" in reasons) and not (quote_ok and _is_us_market(market)):
        root = "market_closed"
        recoverable = "False"
        action = "장마감 시간: 장중 재확인 필요"
    elif quote_ok and _is_us_market(market) and (not orderbook_ok or not flow_ok):
        root = "data_available"
        recoverable = "False"
        missing_bits = []
        if not orderbook_ok:
            missing_bits.append("호가/체결강도")
        if not flow_ok:
            missing_bits.append("수급/프로그램")
        qsrc = str(row.get("quote_source", "") or "").strip().lower()
        if qsrc == "kis_us_quote":
            action = f"미국주식 현재가 KIS 수신 성공. {'·'.join(missing_bits)}는 API 미지원 가능성"
        elif qsrc == "finnhub_quote":
            action = f"KIS 실패 후 Finnhub 보조 수신. {'·'.join(missing_bits)}는 API 미지원 가능성"
        else:
            action = f"미국주식 현재가는 수신됨. {'·'.join(missing_bits)}는 API 미지원 가능성"
    elif "unsupported_market" in reasons:
        root = "unsupported_market"
        recoverable = "False"
        action = "수급/호가 데이터 제공 시장 확인 필요"
    elif "endpoint_not_configured" in reasons:
        root = "endpoint_not_configured"
        recoverable = "True"
        action = "KIS endpoint 설정 및 TR ID 확인 필요"
    elif "parser_error" in reasons or "no_orderbook_fields" in reasons:
        root = "parser_error"
        recoverable = "True"
        action = "API 응답 필드명 파싱 확인 필요"
    elif "api_response_empty" in reasons:
        root = "api_response_empty"
        recoverable = "True"
        action = "API 응답 필드명 파싱 확인 필요"
    elif "rate_limited" in reasons:
        root = "rate_limited"
        recoverable = "Unknown"
        action = "API 호출 제한: 잠시 후 재시도"
    elif "no_target" in reasons:
        root = "no_target"
        recoverable = "False"
        action = "조회 대상 없음: 스냅샷 대상 목록 확인"
    elif "no_data" in reasons:
        root = "no_data"
        recoverable = "True"
        action = "장중 데이터 재조회 또는 fallback 확인"
    else:
        root = "unknown"
        recoverable = "Unknown"
        action = "지원 불가로 표시만 유지"

    return {
        "likely_root_cause": root,
        "recoverable": recoverable,
        "recommended_action": action,
    }


def _row_from_snapshots(
    symbol: str,
    market: str,
    quote_row: dict[str, Any],
    orderbook_row: dict[str, Any],
    flow_row: dict[str, Any],
    source_group: str,
    sector_available: bool,
) -> dict[str, Any]:
    normalized, valid = _symbol_format(symbol, market)
    session = str(
        quote_row.get("intraday_market_session", "")
        or _market_session(market)
    ).strip()
    quote_full_available = _truthy(quote_row.get("quote_full_available")) or (
        _truthy(quote_row.get("intraday_data_available")) and not _truthy(quote_row.get("quote_fallback_used"))
    )
    quote_partial_available = _truthy(quote_row.get("quote_partial_available")) or (
        _truthy(quote_row.get("quote_fallback_used"))
    )
    quote_available = _truthy(quote_row.get("quote_available")) or quote_full_available or quote_partial_available
    orderbook_available = _truthy(orderbook_row.get("orderbook_data_available"))
    flow_available = _truthy(flow_row.get("flow_data_available"))

    quote_failure = _normalize_reason(quote_row.get("quote_failure_reason")) or _normalize_reason(
        quote_row.get("intraday_failure_reason")
    ) or _normalize_reason(quote_row.get("intraday_fetch_status"))
    orderbook_failure = _normalize_reason(orderbook_row.get("orderbook_failure_reason")) or _normalize_reason(
        orderbook_row.get("orderbook_fetch_status")
    )
    flow_failure = _normalize_reason(flow_row.get("flow_failure_reason")) or _normalize_reason(
        flow_row.get("flow_fetch_status")
    )

    display_symbol = normalized if _is_kr_market(market) and valid else symbol
    row = {
        "symbol": display_symbol,
        "market": market,
        "source_group": source_group or "unknown",
        "quote_available": quote_available,
        "quote_partial_available": quote_partial_available,
        "quote_full_available": quote_full_available,
        "orderbook_available": orderbook_available,
        "flow_available": flow_available,
        "sector_flow_available": sector_available,
        "quote_source": str(quote_row.get("quote_source", "") or quote_row.get("intraday_data_source", "")),
        "quote_status": _status_from_row(quote_available, str(quote_row.get("intraday_fetch_status", "")), quote_failure),
        "orderbook_status": _status_from_row(orderbook_available, str(orderbook_row.get("orderbook_fetch_status", "")), orderbook_failure),
        "flow_status": _status_from_row(flow_available, str(flow_row.get("flow_fetch_status", "")), flow_failure),
        "quote_failure_reason": quote_failure or "unknown",
        "orderbook_failure_reason": orderbook_failure or "unknown",
        "flow_failure_reason": flow_failure or "unknown",
        "normalized_symbol": normalized,
        "symbol_format_valid": valid,
        "market_session": session,
        "updated_at": _now(),
    }
    classified = classify_missing_reason(row)
    row.update(classified)
    row["quote_root_cause"] = classify_quote_root_cause(row)
    row["orderbook_root_cause"] = classify_orderbook_root_cause(row)
    row["flow_root_cause"] = classify_flow_root_cause(row)
    row["recoverable"] = str(row.get("recoverable", "False"))
    row["quote_available"] = bool(quote_available)
    row["quote_partial_available"] = bool(quote_partial_available)
    row["quote_full_available"] = bool(quote_full_available)
    row["orderbook_available"] = bool(orderbook_available)
    row["flow_available"] = bool(flow_available)
    row["sector_flow_available"] = bool(sector_available)
    row["symbol_format_valid"] = bool(valid)
    return row


def build_symbol_coverage_table(reports: dict[str, Any] | None = None) -> pd.DataFrame:
    data = reports or load_intraday_reports()
    quote_df: pd.DataFrame = data.get("realtime_snapshot", pd.DataFrame())
    orderbook_df: pd.DataFrame = data.get("orderbook_snapshot", pd.DataFrame())
    flow_df: pd.DataFrame = data.get("flow_snapshot", pd.DataFrame())
    source_groups: dict[tuple[str, str], str] = data.get("source_groups", {})
    sector_lookup: dict[tuple[str, str], bool] = data.get("sector_lookup", {})

    if quote_df.empty and orderbook_df.empty and flow_df.empty:
        return pd.DataFrame(columns=COVERAGE_COLUMNS)

    def _map_df(df: pd.DataFrame) -> dict[tuple[str, str], dict[str, Any]]:
        out: dict[tuple[str, str], dict[str, Any]] = {}
        if df.empty or "symbol" not in df.columns:
            return out
        if "market" not in df.columns:
            df = df.copy()
            df["market"] = ""
        for _, row in df.iterrows():
            sym = str(row.get("symbol", "")).strip().upper()
            mkt = str(row.get("market", "")).strip()
            if sym:
                out[(sym, mkt)] = row.to_dict()
                out[(sym, "")] = row.to_dict()
        return out

    quote_map = _map_df(quote_df)
    orderbook_map = _map_df(orderbook_df)
    flow_map = _map_df(flow_df)

    keys: set[tuple[str, str]] = set()
    for mapping in (quote_map, orderbook_map, flow_map):
        for sym, mkt in mapping:
            if sym and mkt:
                keys.add((sym, mkt))
    if not keys and not quote_df.empty:
        for _, row in quote_df.iterrows():
            sym = str(row.get("symbol", "")).strip().upper()
            mkt = str(row.get("market", "")).strip()
            if sym:
                keys.add((sym, mkt))

    rows: list[dict[str, Any]] = []
    for sym, mkt in sorted(keys):
        if not sym:
            continue
        group = source_groups.get((sym, mkt), source_groups.get((sym, ""), "unknown"))
        sector_ok = sector_lookup.get((sym, mkt), sector_lookup.get((sym, ""), False))
        rows.append(
            _row_from_snapshots(
                sym,
                mkt,
                quote_map.get((sym, mkt), quote_map.get((sym, ""), {})),
                orderbook_map.get((sym, mkt), orderbook_map.get((sym, ""), {})),
                flow_map.get((sym, mkt), flow_map.get((sym, ""), {})),
                group,
                sector_ok,
            )
        )
    out = pd.DataFrame(rows, columns=COVERAGE_COLUMNS)
    if out.empty:
        return out
    out["_sym"] = out["symbol"].astype(str).str.upper()
    out["_mkt"] = out["market"].astype(str).str.strip()
    return out.drop_duplicates(subset=["_sym", "_mkt"], keep="first").drop(columns=["_sym", "_mkt"], errors="ignore")


def summarize_coverage_by_market(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"한국주식": {}, "미국주식": {}, "unknown": {}}
    out: dict[str, Any] = {}
    quote_snap = _read_csv(REPORT_PATHS["realtime_snapshot"])
    us_source_counts = summarize_us_quote_source_counts(quote_snap)
    for market_label, matcher in [("한국주식", _is_kr_market), ("미국주식", _is_us_market)]:
        mask = df["market"].astype(str).map(matcher)
        subset = df.loc[mask]
        if subset.empty:
            out[market_label] = {"symbol_count": 0}
            continue
        block = {
            "symbol_count": int(len(subset)),
            "quote_available_rate": round(float(subset["quote_available"].astype(str).str.lower().isin(["true", "1"]).mean()), 4),
            "orderbook_available_rate": round(float(subset["orderbook_available"].astype(str).str.lower().isin(["true", "1"]).mean()), 4),
            "flow_available_rate": round(float(subset["flow_available"].astype(str).str.lower().isin(["true", "1"]).mean()), 4),
            "sector_flow_available_rate": round(float(subset["sector_flow_available"].astype(str).str.lower().isin(["true", "1"]).mean()), 4),
            "market_closed_count": int(subset["likely_root_cause"].astype(str).eq("market_closed").sum()) if "likely_root_cause" in subset.columns else 0,
            "quote_api_empty_count": int((~subset["quote_available"].astype(str).str.lower().isin(["true", "1"])).sum()),
        }
        if market_label == "미국주식" and not quote_snap.empty:
            us_n = max(1, int((quote_snap["market"].astype(str).map(_is_us_market)).sum()))
            block["kis_us_quote_rate"] = round(us_source_counts["kis_us_quote_success_count"] / us_n, 4)
            block["finnhub_fallback_rate"] = round(us_source_counts["finnhub_fallback_used_count"] / us_n, 4)
            block["csv_fallback_rate"] = round(us_source_counts["csv_fallback_used_count"] / us_n, 4)
            block["quote_full_rate"] = round(
                float(
                    quote_snap.loc[quote_snap["market"].astype(str).map(_is_us_market)]["quote_full_available"]
                    .astype(str)
                    .str.lower()
                    .isin(["true", "1"])
                    .mean()
                ),
                4,
            ) if "quote_full_available" in quote_snap.columns else 0.0
            block["quote_partial_rate"] = round(
                float(
                    quote_snap.loc[quote_snap["market"].astype(str).map(_is_us_market)]["quote_partial_available"]
                    .astype(str)
                    .str.lower()
                    .isin(["true", "1"])
                    .mean()
                ),
                4,
            ) if "quote_partial_available" in quote_snap.columns else 0.0
            block.update(us_source_counts)
        out[market_label] = block
    other = df.loc[~df["market"].astype(str).map(lambda m: _is_kr_market(m) or _is_us_market(m))]
    if not other.empty:
        out["unknown"] = {"symbol_count": int(len(other))}
    return out


def summarize_orderbook_flow_reception(
    orderbook_df: pd.DataFrame,
    flow_df: pd.DataFrame,
) -> dict[str, Any]:
    """스냅샷 기준 호가·수급 수신 집계 (진단 JSON/CSV용)."""

    def _mask_market(frame: pd.DataFrame, is_kr: bool) -> pd.Series:
        if frame.empty or "market" not in frame.columns:
            return pd.Series(dtype=bool)
        matcher = _is_kr_market if is_kr else _is_us_market
        return frame["market"].astype(str).map(matcher)

    def _count_reason(frame: pd.DataFrame, col: str, reason: str) -> int:
        if frame.empty or col not in frame.columns:
            return 0
        return int(frame[col].astype(str).str.strip().str.lower().eq(reason).sum())

    def _count_contains(frame: pd.DataFrame, col: str, needle: str) -> int:
        if frame.empty or col not in frame.columns:
            return 0
        return int(frame[col].astype(str).str.lower().str.contains(needle, regex=False, na=False).sum())

    ob_kr = orderbook_df.loc[_mask_market(orderbook_df, True)] if not orderbook_df.empty else orderbook_df
    ob_us = orderbook_df.loc[_mask_market(orderbook_df, False)] if not orderbook_df.empty else orderbook_df
    fl_kr = flow_df.loc[_mask_market(flow_df, True)] if not flow_df.empty else flow_df
    fl_us = flow_df.loc[_mask_market(flow_df, False)] if not flow_df.empty else flow_df

    def _ob_ok(sub: pd.DataFrame) -> int:
        if sub.empty:
            return 0
        col = "orderbook_available" if "orderbook_available" in sub.columns else "orderbook_data_available"
        if col not in sub.columns:
            return 0
        return int(sub[col].map(_ob_truthy).sum())

    def _flow_ok(sub: pd.DataFrame) -> int:
        if sub.empty:
            return 0
        col = "flow_available" if "flow_available" in sub.columns else "flow_data_available"
        if col not in sub.columns:
            return 0
        return int(sub[col].map(_ob_truthy).sum())

    kr_ob_n = int(len(ob_kr))
    us_ob_n = int(len(ob_us))
    kr_fl_n = int(len(fl_kr))
    us_fl_n = int(len(fl_us))
    kr_flow_reasons: dict[str, int] = {}
    if not fl_kr.empty and "flow_failure_reason" in fl_kr.columns:
        flow_success_mask = pd.Series(False, index=fl_kr.index)
        if "flow_available" in fl_kr.columns:
            flow_success_mask = flow_success_mask | fl_kr["flow_available"].map(_ob_truthy)
        if "flow_data_available" in fl_kr.columns:
            flow_success_mask = flow_success_mask | fl_kr["flow_data_available"].map(_ob_truthy)
        if "kr_flow_success" in fl_kr.columns:
            flow_success_mask = flow_success_mask | fl_kr["kr_flow_success"].map(_ob_truthy)
        reason_series = fl_kr["flow_failure_reason"].astype(str).str.strip()
        reason_series = reason_series.loc[~flow_success_mask & reason_series.ne("") & reason_series.ne("unknown")]
        kr_flow_reasons = {str(k): int(v) for k, v in reason_series.value_counts(dropna=False).to_dict().items()}

    return {
        "kr_orderbook_attempt": int(ob_kr.get("kis_kr_orderbook_attempted", pd.Series(False)).map(_ob_truthy).sum()) if "kis_kr_orderbook_attempted" in ob_kr.columns else kr_ob_n,
        "kr_orderbook_success": _ob_ok(ob_kr),
        "kr_orderbook_fail": max(0, kr_ob_n - _ob_ok(ob_kr)),
        "us_orderbook_attempt": int(ob_us.get("kis_us_orderbook_attempted", pd.Series(False)).map(_ob_truthy).sum()) if "kis_us_orderbook_attempted" in ob_us.columns else us_ob_n,
        "us_orderbook_success": _ob_ok(ob_us),
        "us_orderbook_fail": max(0, us_ob_n - _ob_ok(ob_us)),
        "us_orderbook_api_empty": (
            _count_reason(ob_us, "orderbook_failure_reason", "api_response_empty")
            + _count_contains(ob_us, "kis_us_orderbook_error", "api_response_empty")
        ),
        "us_orderbook_no_fields": (
            _count_reason(ob_us, "orderbook_failure_reason", "no_orderbook_fields")
            + _count_contains(ob_us, "kis_us_orderbook_error", "no_orderbook_fields")
        ),
        "kr_flow_attempt": int(fl_kr.get("kr_flow_attempted", pd.Series(False)).map(_ob_truthy).sum()) if "kr_flow_attempted" in fl_kr.columns else kr_fl_n,
        "kr_flow_success": _flow_ok(fl_kr),
        "kr_flow_fail": max(0, kr_fl_n - _flow_ok(fl_kr)),
        "kr_flow_failure_reason_counts": kr_flow_reasons,
        "kr_flow_endpoint_not_configured": (
            _count_reason(fl_kr, "flow_failure_reason", "endpoint_not_configured")
            + _count_reason(fl_kr, "flow_failure_reason", "kr_flow_endpoint_not_configured")
        ),
        "kr_flow_request_failed": _count_reason(fl_kr, "flow_failure_reason", "kr_flow_request_failed"),
        "kr_flow_response_empty": _count_reason(fl_kr, "flow_failure_reason", "kr_flow_response_empty"),
        "kr_flow_parser_failed": _count_reason(fl_kr, "flow_failure_reason", "kr_flow_parser_failed"),
        "kr_flow_missing_required_fields": _count_reason(fl_kr, "flow_failure_reason", "kr_flow_missing_required_fields"),
        "kr_flow_symbol_format_error": _count_reason(fl_kr, "flow_failure_reason", "kr_flow_symbol_format_error"),
        "kr_flow_market_closed": _count_reason(fl_kr, "flow_failure_reason", "kr_flow_market_closed"),
        "kr_flow_unsupported_endpoint": _count_reason(fl_kr, "flow_failure_reason", "kr_flow_unsupported_endpoint"),
        "kr_flow_permission_or_env_error": _count_reason(fl_kr, "flow_failure_reason", "kr_flow_permission_or_env_error"),
        "us_alt_flow_success": _flow_ok(fl_us),
        "us_alt_flow_fail": max(0, us_fl_n - _flow_ok(fl_us)),
    }


def summarize_coverage_by_data_type(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {}
    total = max(1, len(df))
    boolish = lambda col: df[col].astype(str).str.lower().isin(["true", "1", "1.0"])
    return {
        "quote": {
            "available_count": int(boolish("quote_available").sum()),
            "available_rate": round(float(boolish("quote_available").mean()), 4),
            "missing_count": int((~boolish("quote_available")).sum()),
        },
        "orderbook": {
            "available_count": int(boolish("orderbook_available").sum()),
            "available_rate": round(float(boolish("orderbook_available").mean()), 4),
            "missing_count": int((~boolish("orderbook_available")).sum()),
        },
        "flow": {
            "available_count": int(boolish("flow_available").sum()),
            "available_rate": round(float(boolish("flow_available").mean()), 4),
            "missing_count": int((~boolish("flow_available")).sum()),
        },
        "sector_flow": {
            "available_count": int(boolish("sector_flow_available").sum()),
            "available_rate": round(float(boolish("sector_flow_available").mean()), 4),
            "missing_count": int((~boolish("sector_flow_available")).sum()),
        },
        "total_symbol_count": int(total),
    }


def _count_root_causes(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "likely_root_cause" not in df.columns:
        return {}
    issues = df.loc[df["likely_root_cause"].astype(str).isin(ISSUE_ROOT_CAUSES)]
    if issues.empty:
        return {}
    return dict(Counter(issues["likely_root_cause"].astype(str).tolist()))


def _count_typed_root_causes(df: pd.DataFrame, classifier) -> dict[str, int]:
    if df.empty:
        return {}
    causes = df.apply(lambda row: classifier(row.to_dict()), axis=1)
    issues = causes[causes.astype(str).isin(ISSUE_ROOT_CAUSES)]
    if issues.empty:
        return {}
    return dict(Counter(issues.astype(str).tolist()))


def count_recoverable_issues(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    return int(df.apply(lambda row: is_recoverable_issue(row.to_dict()), axis=1).sum())


def count_unrecoverable_issues(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    return int(df["likely_root_cause"].astype(str).isin(UNRECOVERABLE_CAUSES).sum())


def build_improvement_suggestions(df: pd.DataFrame) -> dict[str, Any]:
    priority_1: list[str] = []
    priority_2: list[str] = []
    unsupported_items: list[str] = []
    monitor_later: list[str] = []

    if df.empty:
        return {
            "updated_at": _now(),
            "priority_1_fixes": ["장중 스냅샷 리포트가 없습니다. intraday 엔진을 먼저 실행하세요."],
            "priority_2_fixes": [],
            "unsupported_items": [],
            "monitor_later_items": [],
            "summary_message": "진단 대상 데이터 없음",
        }

    boolish = lambda col: df[col].astype(str).str.lower().isin(["true", "1", "1.0"])
    issue_df = df.loc[df.apply(lambda row: is_recoverable_issue(row.to_dict()), axis=1)]

    invalid_count = int((issue_df["likely_root_cause"].astype(str) == "invalid_symbol").sum()) if not issue_df.empty else 0
    parser_count = int((issue_df["likely_root_cause"].astype(str) == "parser_error").sum()) if not issue_df.empty else 0
    endpoint_count = int((issue_df["likely_root_cause"].astype(str) == "endpoint_not_configured").sum()) if not issue_df.empty else 0
    us_mask = df["market"].astype(str).map(_is_us_market) if not df.empty and "market" in df.columns else pd.Series(dtype=bool)
    us_quote_missing = int((us_mask & ~boolish("quote_available")).sum()) if not df.empty else 0
    us_ob_missing = int((us_mask & ~boolish("orderbook_available")).sum())
    us_flow_missing = int((us_mask & ~boolish("flow_available")).sum())
    closed_count = int((df["likely_root_cause"].astype(str) == "market_closed").sum())

    quote_only_mask = (~boolish("quote_available")) & (boolish("orderbook_available") | boolish("flow_available"))
    quote_only = df.loc[quote_only_mask]
    partial_mask = boolish("quote_partial_available") & (~boolish("quote_full_available"))
    partial_df = df.loc[partial_mask]
    if not quote_only.empty:
        kr_quote_only = quote_only.loc[quote_only["market"].astype(str).map(_is_kr_market)]
        us_quote_only = quote_only.loc[quote_only["market"].astype(str).map(_is_us_market)]
        if not kr_quote_only.empty:
            symbols = ", ".join(kr_quote_only["symbol"].astype(str).tolist()[:8])
            priority_1.append(
                f"한국주식 quote API 미수신 {len(kr_quote_only)}개: {symbols} - quote API 재조회 또는 fallback 확인"
            )
        if not us_quote_only.empty:
            symbols = ", ".join(us_quote_only["symbol"].astype(str).tolist()[:8])
            priority_1.append(
                f"미국주식 현재가 API 응답 없음 {len(us_quote_only)}건: {symbols} - endpoint/파라미터/fallback 확인 필요"
            )
        other_quote = quote_only.loc[~quote_only["market"].astype(str).map(_is_kr_market) & ~quote_only["market"].astype(str).map(_is_us_market)]
        if not other_quote.empty:
            symbols = ", ".join(other_quote["symbol"].astype(str).tolist()[:8])
            priority_2.append(
                f"quote API 미수신 {len(other_quote)}개: {symbols} - quote API 재조회 또는 fallback 확인"
            )
    if not partial_df.empty:
        kr_partial = partial_df.loc[partial_df["market"].astype(str).map(_is_kr_market)]
        if not kr_partial.empty:
            symbols = ", ".join(kr_partial["symbol"].astype(str).tolist()[:8])
            priority_2.append(
                f"한국주식 quote API 미수신 {len(kr_partial)}개 중 {len(kr_partial)}개는 orderbook/후보 가격 fallback 적용: {symbols}"
            )
        priority_2.append("거래량/거래대금은 실제 API 미수신으로 장중 판단 제한")

    if invalid_count:
        priority_1.append("한국주식 symbol 앞자리 0 유지 여부 확인")
    if parser_count or endpoint_count:
        priority_1.append("orderbook endpoint 응답 필드명 파싱 확인")
        priority_1.append("수급 API 시장별 지원 여부 분리")

    other_recoverable = issue_df.loc[~issue_df["likely_root_cause"].astype(str).eq("quote_api_response_empty")]
    if not other_recoverable.empty and not priority_1:
        roots = ", ".join(sorted(set(other_recoverable["likely_root_cause"].astype(str).tolist()))[:4])
        priority_2.append(f"개선 가능 미수신 종목 {len(other_recoverable)}개: {roots}")

    if us_ob_missing:
        unsupported_items.append(f"미국주식 호가/체결강도는 API 미지원 가능성 ({us_ob_missing}건)")
    if us_flow_missing:
        unsupported_items.append(f"미국주식 수급/프로그램은 API 미지원 가능성 ({us_flow_missing}건)")
    if us_quote_missing and not any("미국주식 현재가 API" in s for s in priority_1):
        unsupported_items.append(
            f"미국주식 현재가 API 응답 없음 {us_quote_missing}건: KIS 해외 현재가·Finnhub 키·fallback CSV 확인"
        )
    unrecoverable_df = df.loc[
        df["recoverable"].astype(str).str.lower().eq("false")
        & df["likely_root_cause"].astype(str).isin(UNRECOVERABLE_CAUSES)
    ]
    unsupported_items.extend([
        item for item in sorted(set(unrecoverable_df["recommended_action"].astype(str).tolist()))
        if item and not item.startswith("정상 수신")
    ][:5])

    if closed_count:
        monitor_later.append("장중 시간에 재실행하여 market_closed 원인 제거 후 재확인")

    quote_rate = float(boolish("quote_available").mean())
    recoverable_n = count_recoverable_issues(df)
    unrecoverable_n = count_unrecoverable_issues(df)
    summary_message = (
        f"장중 커버리지 진단: 현재가 수신률 {quote_rate * 100:.1f}%. "
        f"개선 가능 {recoverable_n}건, 미지원/불가 {unrecoverable_n}건."
    )
    return {
        "updated_at": _now(),
        "priority_1_fixes": list(dict.fromkeys(priority_1)),
        "priority_2_fixes": list(dict.fromkeys(priority_2)),
        "unsupported_items": list(dict.fromkeys(unsupported_items)),
        "monitor_later_items": list(dict.fromkeys(monitor_later)),
        "summary_message": summary_message,
    }


def build_unsupported_symbols_table(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if df.empty:
        return pd.DataFrame(columns=["symbol", "market", "unsupported_data_type", "failure_reason", "recommended_action", "updated_at"])
    for _, row in df.iterrows():
        sym = str(row.get("symbol", "")).strip()
        market = str(row.get("market", "")).strip()
        action = str(row.get("recommended_action", "")).strip()
        updated = str(row.get("updated_at", _now()))
        checks = [
            ("quote", not _truthy(row.get("quote_available")), str(row.get("quote_failure_reason", ""))),
            ("orderbook", not _truthy(row.get("orderbook_available")), str(row.get("orderbook_failure_reason", ""))),
            ("flow", not _truthy(row.get("flow_available")), str(row.get("flow_failure_reason", ""))),
            ("sector_flow", not _truthy(row.get("sector_flow_available")), "sector_sample_or_mapping"),
        ]
        for data_type, missing, reason in checks:
            if not missing:
                continue
            reason_norm = _normalize_reason(reason) or "unknown"
            if reason_norm not in {"unsupported_market", "endpoint_not_configured", "unsupported", "no_data"} and data_type != "sector_flow":
                if reason_norm not in UNRECOVERABLE_CAUSES and reason_norm != "market_closed":
                    continue
            if data_type == "sector_flow" and reason_norm not in {"sector_sample_or_mapping", "unknown", ""}:
                pass
            rows.append({
                "symbol": sym,
                "market": market,
                "unsupported_data_type": data_type,
                "failure_reason": reason_norm or "unsupported",
                "recommended_action": action or "지원 불가로 표시만 유지",
                "updated_at": updated,
            })
    return pd.DataFrame(rows)


def _overall_status(df: pd.DataFrame, missing_reports: list[str]) -> str:
    if missing_reports and len(missing_reports) >= 6:
        return "ERROR"
    if df.empty:
        return "WARNING"
    boolish = lambda col: df[col].astype(str).str.lower().isin(["true", "1", "1.0"])
    quote_rate = float(boolish("quote_available").mean())
    orderbook_rate = float(boolish("orderbook_available").mean())
    flow_rate = float(boolish("flow_available").mean())
    recoverable_count = count_recoverable_issues(df)
    unrecoverable_count = count_unrecoverable_issues(df)

    if quote_rate >= 0.85 and orderbook_rate >= 0.5 and flow_rate >= 0.5 and recoverable_count <= 3:
        return "OK"
    if quote_rate >= 0.6 and recoverable_count <= max(5, len(df) // 3):
        return "NOTICE"
    if recoverable_count >= max(3, len(df) // 4) or quote_rate < 0.5:
        return "WARNING"
    if unrecoverable_count == len(df):
        return "NOTICE"
    return "NOTICE"


def save_intraday_data_coverage_diagnosis() -> dict[str, Any]:
    reports = load_intraday_reports()
    df = build_symbol_coverage_table(reports)
    market_coverage = summarize_coverage_by_market(df)
    data_type_coverage = summarize_coverage_by_data_type(df)
    root_cause_counts = _count_root_causes(df)
    quote_root_cause_counts = _count_typed_root_causes(df, classify_quote_root_cause)
    orderbook_root_cause_counts = _count_typed_root_causes(df, classify_orderbook_root_cause)
    flow_root_cause_counts = _count_typed_root_causes(df, classify_flow_root_cause)
    suggestions = build_improvement_suggestions(df)
    unsupported_df = build_unsupported_symbols_table(df)

    boolish = lambda col: df[col].astype(str).str.lower().isin(["true", "1", "1.0"]) if not df.empty else pd.Series(dtype=bool)
    recoverable_issue_count = count_recoverable_issues(df)
    unrecoverable_issue_count = count_unrecoverable_issues(df)
    unsupported_count = int((df["likely_root_cause"].astype(str) == "unsupported_market").sum()) if not df.empty else 0
    us_quote_api_empty_count = int((df["likely_root_cause"].astype(str) == "us_quote_api_response_empty").sum()) if not df.empty else 0
    if not us_quote_api_empty_count and quote_root_cause_counts.get("us_quote_api_response_empty"):
        us_quote_api_empty_count = int(quote_root_cause_counts["us_quote_api_response_empty"])
    market_closed_count = int((df["likely_root_cause"].astype(str) == "market_closed").sum()) if not df.empty else 0
    invalid_symbol_count = int((df["likely_root_cause"].astype(str) == "invalid_symbol").sum()) if not df.empty else 0
    parser_error_count = int((df["likely_root_cause"].astype(str) == "parser_error").sum()) if not df.empty else 0

    missing_symbols = df.loc[~boolish("quote_available"), "symbol"].astype(str).tolist()[:15] if not df.empty else []

    quote_full_rate = float(boolish("quote_full_available").mean()) if "quote_full_available" in df.columns and not df.empty else 0.0
    quote_partial_rate = float(boolish("quote_partial_available").mean()) if "quote_partial_available" in df.columns and not df.empty else 0.0
    fallback_count = int(boolish("quote_partial_available").sum() - boolish("quote_full_available").sum()) if not df.empty else 0
    if fallback_count < 0:
        fallback_count = int(boolish("quote_partial_available").sum()) if not df.empty else 0
    quote_api_empty = int((~boolish("quote_available")).sum()) if not df.empty else 0
    kr_mask = df["market"].astype(str).map(_is_kr_market) if not df.empty and "market" in df.columns else pd.Series(dtype=bool)
    kr_quote_missing = int((kr_mask & ~boolish("quote_available")).sum()) if not df.empty else 0
    kr_quote_fallback = int((kr_mask & boolish("quote_partial_available") & ~boolish("quote_full_available")).sum()) if not df.empty else 0
    quote_snap = reports.get("realtime_snapshot", pd.DataFrame())
    us_quote_source_counts = summarize_us_quote_source_counts(quote_snap)

    orderbook_df = reports.get("orderbook_snapshot", pd.DataFrame())
    flow_df = reports.get("flow_snapshot", pd.DataFrame())
    reception_stats = summarize_orderbook_flow_reception(orderbook_df, flow_df)
    overall_status = _overall_status(df, reports.get("missing_reports", []))
    kr_cov = market_coverage.get("한국주식", {}) if isinstance(market_coverage, dict) else {}
    if (
        _kr_market_session() == "regular"
        and int(kr_cov.get("symbol_count", 0) or 0) > 0
        and float(kr_cov.get("orderbook_available_rate", 0.0) or 0.0) <= 0.0
    ):
        overall_status = "ERROR"

    current_market_sessions = {
        "한국주식": current_session_for_market("한국주식"),
        "미국주식": current_session_for_market("미국주식"),
    }

    summary = {
        "updated_at": _now(),
        "current_market_sessions": current_market_sessions,
        "overall_status": overall_status,
        **reception_stats,
        "total_symbol_count": int(len(df)),
        "quote_available_rate": data_type_coverage.get("quote", {}).get("available_rate", 0.0),
        "quote_full_available_rate": round(quote_full_rate, 4),
        "quote_partial_available_rate": round(quote_partial_rate, 4),
        "quote_fallback_used_count": fallback_count,
        "quote_api_empty_count": quote_api_empty,
        "kr_quote_missing_count": kr_quote_missing,
        "kr_quote_fallback_count": kr_quote_fallback,
        **us_quote_source_counts,
        "orderbook_available_rate": data_type_coverage.get("orderbook", {}).get("available_rate", 0.0),
        "flow_available_rate": data_type_coverage.get("flow", {}).get("available_rate", 0.0),
        "sector_flow_available_rate": data_type_coverage.get("sector_flow", {}).get("available_rate", 0.0),
        "market_coverage": market_coverage,
        "data_type_coverage": data_type_coverage,
        "root_cause_counts": root_cause_counts,
        "quote_root_cause_counts": quote_root_cause_counts,
        "orderbook_root_cause_counts": orderbook_root_cause_counts,
        "flow_root_cause_counts": flow_root_cause_counts,
        "us_quote_api_empty_count": us_quote_api_empty_count,
        "recoverable_issue_count": recoverable_issue_count,
        "unrecoverable_issue_count": unrecoverable_issue_count,
        "unsupported_count": unsupported_count,
        "market_closed_count": market_closed_count,
        "invalid_symbol_count": invalid_symbol_count,
        "parser_error_count": parser_error_count,
        "rate_limited_count": int((df["likely_root_cause"].astype(str) == "rate_limited").sum()) if not df.empty else 0,
        "top_missing_symbols": missing_symbols,
        "improvement_priority": suggestions.get("priority_1_fixes", []),
        "warnings": [],
        "errors": [],
    }
    if reports.get("missing_reports"):
        summary["warnings"].append(f"누락 리포트 {len(reports['missing_reports'])}개")
    if recoverable_issue_count:
        summary["warnings"].append(f"개선 가능 이슈 {recoverable_issue_count}건")
    if us_quote_api_empty_count:
        summary["warnings"].append(f"미국주식 현재가 API 응답 없음 {us_quote_api_empty_count}건 (KIS/Finnhub/fallback 확인)")
    if us_quote_source_counts.get("finnhub_fallback_used_count"):
        summary["warnings"].append(
            f"KIS 실패 후 Finnhub 보조 수신 {us_quote_source_counts['finnhub_fallback_used_count']}건"
        )
    if us_quote_source_counts.get("kis_us_quote_success_count"):
        summary["warnings"].append(
            f"미국주식 현재가 KIS 수신 성공 {us_quote_source_counts['kis_us_quote_success_count']}건"
        )
    if unsupported_count:
        summary["warnings"].append(f"호가/수급 등 미지원 분류 {unsupported_count}건")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(COVERAGE_DIAGNOSIS_CSV, index=False, encoding="utf-8-sig")
    unsupported_df.to_csv(UNSUPPORTED_SYMBOLS_CSV, index=False, encoding="utf-8-sig")
    COVERAGE_DIAGNOSIS_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    IMPROVEMENT_SUGGESTIONS_JSON.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    return {
        "summary_path": str(COVERAGE_DIAGNOSIS_JSON),
        "coverage_csv_path": str(COVERAGE_DIAGNOSIS_CSV),
        "unsupported_csv_path": str(UNSUPPORTED_SYMBOLS_CSV),
        "suggestions_path": str(IMPROVEMENT_SUGGESTIONS_JSON),
        "rows": int(len(df)),
        **summary,
        "improvement_suggestions": suggestions,
    }


def main() -> int:
    result = save_intraday_data_coverage_diagnosis()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result.get("overall_status") == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
