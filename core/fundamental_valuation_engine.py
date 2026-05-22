from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "reports"
DATA_DIR = PROJECT_ROOT / "data"

CANDIDATE_FILES = [
    REPORT_DIR / "swing_candidates_kr_A_top3.csv",
    REPORT_DIR / "swing_candidates_kr_B_watch.csv",
    REPORT_DIR / "swing_candidates_kr_C_excluded.csv",
    REPORT_DIR / "swing_candidates_us_A_top3.csv",
    REPORT_DIR / "swing_candidates_us_B_watch.csv",
    REPORT_DIR / "swing_candidates_us_C_excluded.csv",
]

FUNDAMENTAL_CACHE_FILES = [
    REPORT_DIR / "fundamental_cache.csv",
    REPORT_DIR / "fundamental_cache_kr.csv",
    REPORT_DIR / "fundamental_cache_us.csv",
    DATA_DIR / "kr_financial_metrics.csv",
]

SUMMARY_JSON = REPORT_DIR / "fundamental_valuation_summary.json"
DETAIL_CSV = REPORT_DIR / "fundamental_valuation_detail.csv"

KR_MARKET_ALIASES = {"kr", "korea", "kospi", "kosdaq", "한국", "한국주식", "국장", "국내", "korean"}
US_MARKET_ALIASES = {"us", "usa", "nasdaq", "nyse", "amex", "미국", "미국주식", "미장", "해외", "american"}

OUTPUT_COLUMNS = [
    "earnings_score",
    "earnings_data_status",
    "earnings_reason",
    "earnings_warning",
    "earnings_source",
    "revenue_growth",
    "operating_income_growth",
    "net_income_growth",
    "valuation_score",
    "valuation_data_status",
    "valuation_reason",
    "valuation_warning",
    "valuation_source",
    "per",
    "pbr",
    "psr",
    "roe",
    "market_cap",
]

DETAIL_COLUMNS = [
    "symbol",
    "market",
    "name",
    "earnings_attempted",
    "earnings_success",
    "earnings_score",
    "earnings_data_status",
    "earnings_reason",
    "valuation_attempted",
    "valuation_success",
    "valuation_score",
    "valuation_data_status",
    "valuation_reason",
    "per",
    "pbr",
    "psr",
    "roe",
    "market_cap",
    "data_source",
    "updated_at",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc, low_memory=False).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _to_num(value: Any, default: float = math.nan) -> float:
    try:
        if value is None:
            return default
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "n/a", "na", "-", "확인 필요"}:
            return default
        text = text.replace(",", "").replace("%", "")
        text = re.sub(r"[^0-9.\-+]", "", text)
        if text in {"", "-", "+", "."}:
            return default
        return float(text)
    except Exception:
        return default


def _blank_if_nan(value: Any, digits: int = 2) -> Any:
    num = _to_num(value)
    if math.isnan(num):
        return ""
    return round(num, digits)


def _pct_growth(latest: Any, previous: Any) -> float:
    latest_num = _to_num(latest)
    previous_num = _to_num(previous)
    if math.isnan(latest_num) or math.isnan(previous_num) or previous_num == 0:
        return math.nan
    return (latest_num / abs(previous_num) - (1 if previous_num > 0 else -1)) * 100


def normalize_market(value: Any, *, file_hint: str = "") -> str:
    text = str(value or "").strip().lower()
    hint = str(file_hint or "").lower()
    if any(alias.lower() in text for alias in KR_MARKET_ALIASES) or "_kr" in hint:
        return "KR"
    if any(alias.lower() in text for alias in US_MARKET_ALIASES) or "_us" in hint:
        return "US"
    return "KR" if re.fullmatch(r"\d{1,6}", text) else "US"


def normalize_symbol(value: Any, market: str) -> str:
    raw = str(value or "").strip().upper()
    if market == "KR":
        digits = re.sub(r"\D", "", raw)
        return digits.zfill(6) if digits else ""
    return raw.replace(".US", "").strip()


def _first_nonempty(row: Any, names: list[str], default: str = "") -> str:
    if row is None:
        return default
    for name in names:
        try:
            value = row.get(name, "")
        except Exception:
            value = ""
        text = str(value or "").strip()
        if text and text.lower() not in {"nan", "none", "n/a", "na", "-"}:
            return text
    return default


def _candidate_key(row: Any, *, file_hint: str = "") -> tuple[str, str]:
    market = normalize_market(_first_nonempty(row, ["market", "시장"]), file_hint=file_hint)
    symbol = normalize_symbol(_first_nonempty(row, ["symbol", "ticker", "종목코드", "code"]), market)
    return market, symbol


def _load_cache_rows() -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for path in FUNDAMENTAL_CACHE_FILES:
        df = _read_csv(path)
        if df.empty:
            continue
        for _, row in df.iterrows():
            source_market = _first_nonempty(row, ["market"], "")
            market = normalize_market(source_market, file_hint=path.name)
            symbol = normalize_symbol(_first_nonempty(row, ["symbol", "ticker", "stock_code"]), market)
            if not symbol:
                continue
            data = row.to_dict()
            data["_cache_file"] = path.name
            data["_market_norm"] = market
            key = (market, symbol)
            current = rows.get(key, {})
            if _cache_priority(data) >= _cache_priority(current):
                rows[key] = data
    return rows


def _cache_priority(row: dict[str, Any]) -> int:
    if not row:
        return -1
    source = str(row.get("source", row.get("_cache_file", ""))).lower()
    status = str(row.get("status", row.get("runner_status", ""))).upper()
    score = 0
    if status == "OK":
        score += 10
    if "kr_financial_metrics" in str(row.get("_cache_file", "")):
        score += 2
    if any(token in source for token in ("dart", "finnhub", "sec", "kis")):
        score += 5
    metric_count = sum(1 for key in ("PER", "PBR", "PSR", "per", "pbr", "psr", "market_cap") if not math.isnan(_to_num(row.get(key))))
    return score + metric_count


def _score_earnings_from_values(
    *,
    revenue_growth: float = math.nan,
    operating_income_growth: float = math.nan,
    net_income_growth: float = math.nan,
    latest_operating_income: float = math.nan,
    latest_net_income: float = math.nan,
    previous_net_income: float = math.nan,
    fallback_score: float = math.nan,
) -> tuple[Any, str, str, str]:
    available = [
        not math.isnan(revenue_growth),
        not math.isnan(operating_income_growth),
        not math.isnan(net_income_growth),
        not math.isnan(latest_operating_income),
        not math.isnan(latest_net_income),
    ]
    if not any(available):
        if not math.isnan(fallback_score):
            return round(max(0, min(100, fallback_score)), 1), "partial", "기존 API 재무 캐시 점수 반영", "실적 일부 부족, 보수 반영"
        return "", "data_missing", "실적 원자료 없음", "실적 데이터 부족"

    score = 50.0
    reasons: list[str] = []
    warnings: list[str] = []

    def growth_points(label: str, value: float, strong: float, weak: float) -> None:
        nonlocal score
        if math.isnan(value):
            warnings.append(f"{label} 부족")
            return
        if value >= strong:
            score += 12
            reasons.append(f"{label} 성장 양호 {value:.1f}%")
        elif value > weak:
            score += 6
            reasons.append(f"{label} 성장 {value:.1f}%")
        elif value < -10:
            score -= 10
            warnings.append(f"{label} 감소 {value:.1f}%")

    growth_points("매출", revenue_growth, 15, 0)
    growth_points("영업이익", operating_income_growth, 20, 0)
    growth_points("순이익", net_income_growth, 20, 0)

    if not math.isnan(latest_net_income):
        if latest_net_income < 0:
            score -= 18
            warnings.append("적자 상태")
        elif not math.isnan(previous_net_income) and previous_net_income < 0:
            score += 12
            reasons.append("흑자전환")
        else:
            score += 4
            reasons.append("흑자 유지")
    if not math.isnan(previous_net_income) and previous_net_income > 0 and not math.isnan(latest_net_income) and latest_net_income < 0:
        score -= 22
        warnings.append("적자전환")
    if not math.isnan(latest_operating_income) and latest_operating_income < 0:
        score -= 10
        warnings.append("영업적자")

    status = "ok" if sum(available) >= 3 and not warnings else "partial"
    warning = "" if status == "ok" else "실적 일부 부족, 보수 반영"
    reason = " / ".join(reasons[:4]) if reasons else "실적 데이터 제한적"
    return round(max(0, min(100, score)), 1), status, reason, warning


def _score_valuation(per: float, pbr: float, psr: float, roe: float) -> tuple[Any, str, str, str]:
    inputs = [not math.isnan(v) and v > 0 for v in (per, pbr, psr)]
    if not any(inputs):
        return "", "data_missing", "PER/PBR/PSR 원자료 없음", "밸류 데이터 없음"

    score = 50.0
    reasons: list[str] = []
    warnings: list[str] = []

    if not math.isnan(per) and per > 0:
        if per <= 12:
            score += 18
            reasons.append(f"PER 낮음 {per:.2f}")
        elif per <= 25:
            score += 8
            reasons.append(f"PER 보통 {per:.2f}")
        elif per >= 60:
            score -= 18
            warnings.append(f"PER 고평가 {per:.2f}")
        else:
            score -= 6
            warnings.append(f"PER 부담 {per:.2f}")
    else:
        warnings.append("PER 부족")

    if not math.isnan(pbr) and pbr > 0:
        if pbr <= 1.2:
            score += 14
            reasons.append(f"PBR 낮음 {pbr:.2f}")
        elif pbr <= 3:
            score += 6
            reasons.append(f"PBR 보통 {pbr:.2f}")
        elif pbr >= 10:
            score -= 14
            warnings.append(f"PBR 고평가 {pbr:.2f}")
        else:
            score -= 4
            warnings.append(f"PBR 부담 {pbr:.2f}")
    else:
        warnings.append("PBR 부족")

    if not math.isnan(psr) and psr > 0:
        if psr <= 2:
            score += 10
            reasons.append(f"PSR 낮음 {psr:.2f}")
        elif psr <= 6:
            score += 4
            reasons.append(f"PSR 보통 {psr:.2f}")
        elif psr >= 15:
            score -= 12
            warnings.append(f"PSR 고평가 {psr:.2f}")
        else:
            score -= 4
            warnings.append(f"PSR 부담 {psr:.2f}")
    else:
        warnings.append("PSR 부족")

    if not math.isnan(roe):
        if roe >= 15:
            score += 8
            reasons.append(f"ROE 양호 {roe:.1f}%")
        elif roe < 0:
            score -= 10
            warnings.append(f"ROE 적자 {roe:.1f}%")

    status = "ok" if sum(inputs) >= 2 else "partial"
    warning = "" if status == "ok" else "밸류 일부 부족"
    reason_parts = reasons[:4] if reasons else warnings[:4]
    reason = " / ".join(reason_parts) if reason_parts else "밸류 원자료 제한적"
    return round(max(0, min(100, score)), 1), status, reason, warning


def _remove_stale_earnings_warning(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = re.split(r"\s*/\s*|\s*\|\s*|\s*;\s*", text)
    kept = []
    for part in parts:
        low = part.lower()
        if "실적 데이터 부족" in part or ("earnings" in low and ("missing" in low or "fallback" in low)):
            continue
        kept.append(part)
    return " / ".join(dict.fromkeys(p for p in kept if p))


def _financials_from_cache(cache: dict[str, Any]) -> dict[str, Any]:
    revenue = _to_num(_first_nonempty(cache, ["revenue", "sales"]))
    operating_income = _to_num(_first_nonempty(cache, ["operating_income", "operating_profit"]))
    net_income = _to_num(_first_nonempty(cache, ["net_income"]))
    equity = _to_num(_first_nonempty(cache, ["total_equity", "equity"]))
    market_cap = _to_num(_first_nonempty(cache, ["market_cap", "marketCapitalization"]))
    per = _to_num(_first_nonempty(cache, ["per", "PER", "peTTM", "peNormalizedAnnual"]))
    pbr = _to_num(_first_nonempty(cache, ["pbr", "PBR", "pbAnnual", "pbQuarterly"]))
    psr = _to_num(_first_nonempty(cache, ["psr", "PSR", "psTTM", "psAnnual"]))
    roe = _to_num(_first_nonempty(cache, ["roe", "ROE", "roeTTM"]))
    rev_growth = _to_num(_first_nonempty(cache, ["revenue_growth", "sales_growth", "revenue_cagr_3y", "revenueGrowthTTMYoy", "revenueGrowthQuarterlyYoy"]))
    op_growth = _to_num(_first_nonempty(cache, ["operating_income_growth", "operating_margin_change"]))
    net_growth = _to_num(_first_nonempty(cache, ["net_income_growth", "epsGrowthTTMYoy", "epsGrowthQuarterlyYoy"]))
    fallback = _to_num(_first_nonempty(cache, ["earnings_score", "fundamental_score"]))

    if math.isnan(per) and not math.isnan(market_cap) and not math.isnan(net_income) and net_income > 0:
        per = market_cap / net_income
    if math.isnan(pbr) and not math.isnan(market_cap) and not math.isnan(equity) and equity > 0:
        pbr = market_cap / equity
    if math.isnan(psr) and not math.isnan(market_cap) and not math.isnan(revenue) and revenue > 0:
        psr = market_cap / revenue
    if math.isnan(roe) and not math.isnan(net_income) and not math.isnan(equity) and equity > 0:
        roe = net_income / equity * 100

    return {
        "revenue": revenue,
        "operating_income": operating_income,
        "net_income": net_income,
        "total_equity": equity,
        "market_cap": market_cap,
        "per": per,
        "pbr": pbr,
        "psr": psr,
        "roe": roe,
        "revenue_growth": rev_growth,
        "operating_income_growth": op_growth,
        "net_income_growth": net_growth,
        "fallback_earnings_score": fallback,
    }


def _finnhub_key() -> str:
    if os.environ.get("FINNHUB_API_KEY"):
        return str(os.environ.get("FINNHUB_API_KEY")).strip()
    path = PROJECT_ROOT / "finnhub_config.json"
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("enabled") is False:
                return ""
            return str(data.get("api_key") or data.get("token") or data.get("finnhub_api_key") or "").strip()
    except Exception:
        return ""
    return ""


def _fetch_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 12) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "stock-app fundamentals"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _fetch_finnhub_metrics(symbol: str, token: str) -> tuple[dict[str, Any], str]:
    if not token:
        return {}, "Finnhub API 키 없음"
    try:
        import urllib.parse

        url = "https://finnhub.io/api/v1/stock/metric?" + urllib.parse.urlencode(
            {"symbol": symbol.upper(), "metric": "all", "token": token}
        )
        payload = _fetch_json(url)
        metric = payload.get("metric") or {}
        if not metric:
            return {}, "Finnhub metric 응답 없음"
        return metric, "Finnhub"
    except Exception as exc:
        return {}, f"Finnhub 조회 실패: {exc.__class__.__name__}"


def _sec_company_cik(symbol: str) -> tuple[str, str]:
    try:
        from core.sec_dart_disclosure_engine import resolve_sec_cik_for_ticker

        return resolve_sec_cik_for_ticker(symbol)
    except Exception:
        return "", ""


def _extract_recent_fact(facts: dict[str, Any], names: list[str]) -> tuple[float, float]:
    for name in names:
        item = facts.get("us-gaap", {}).get(name, {})
        units = item.get("units", {}) if isinstance(item, dict) else {}
        values = units.get("USD") or units.get("shares") or []
        if not values:
            continue
        rows = [
            r
            for r in values
            if str(r.get("form", "")) in {"10-K", "10-Q"} and _to_num(r.get("val")) == _to_num(r.get("val"))
        ]
        rows = sorted(rows, key=lambda r: str(r.get("end", "")))
        if len(rows) >= 2:
            return _to_num(rows[-1].get("val")), _to_num(rows[-2].get("val"))
        if len(rows) == 1:
            return _to_num(rows[-1].get("val")), math.nan
    return math.nan, math.nan


def _fetch_sec_facts(symbol: str) -> tuple[dict[str, Any], str]:
    cik, _company = _sec_company_cik(symbol)
    if not cik:
        return {}, "SEC CIK 매칭 실패"
    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json"
        payload = _fetch_json(url, headers={"User-Agent": "stock-app fundamentals contact@example.com"})
        facts = payload.get("facts") or {}
        revenue, revenue_prev = _extract_recent_fact(facts, ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"])
        operating_income, operating_prev = _extract_recent_fact(facts, ["OperatingIncomeLoss"])
        net_income, net_prev = _extract_recent_fact(facts, ["NetIncomeLoss"])
        equity, _equity_prev = _extract_recent_fact(facts, ["StockholdersEquity"])
        return {
            "revenue": revenue,
            "operating_income": operating_income,
            "net_income": net_income,
            "total_equity": equity,
            "revenue_growth": _pct_growth(revenue, revenue_prev),
            "operating_income_growth": _pct_growth(operating_income, operating_prev),
            "net_income_growth": _pct_growth(net_income, net_prev),
        }, "SEC"
    except Exception as exc:
        return {}, f"SEC 조회 실패: {exc.__class__.__name__}"


def _api_metrics_for_symbol(symbol: str, market: str) -> tuple[dict[str, Any], str, str]:
    if market == "US":
        token = _finnhub_key()
        metric, source_or_reason = _fetch_finnhub_metrics(symbol, token)
        if metric:
            return metric, "Finnhub", ""
        sec, sec_source_or_reason = _fetch_sec_facts(symbol)
        if sec:
            return sec, "SEC", source_or_reason
        return {}, "Finnhub/SEC", f"{source_or_reason}; {sec_source_or_reason}"
    if market == "KR":
        try:
            from core.sec_dart_disclosure_engine import build_kr_financial_metrics_from_dart

            result = build_kr_financial_metrics_from_dart(refresh=True, max_symbols=12)
            return {}, "DART/KIS", str(result.get("message", "DART 갱신 시도"))
        except Exception as exc:
            return {}, "DART/KIS", f"DART 조회 실패: {exc.__class__.__name__}"
    return {}, "", "지원하지 않는 시장"


def build_row_scores(
    row: Any,
    *,
    cache: dict[tuple[str, str], dict[str, Any]] | None = None,
    file_hint: str = "",
    fetch_missing: bool = False,
) -> dict[str, Any]:
    cache = cache or _load_cache_rows()
    market, symbol = _candidate_key(row, file_hint=file_hint)
    name = _first_nonempty(row, ["name", "종목명"], symbol)
    used = dict(cache.get((market, symbol), {}))
    api_failure = ""
    source = _first_nonempty(used, ["source", "_cache_file"], "")

    if fetch_missing and not used:
        api_data, api_source, api_failure = _api_metrics_for_symbol(symbol, market)
        if api_data:
            used = api_data
            source = api_source
        elif api_failure:
            source = api_source

    financials = _financials_from_cache(used)
    earnings_score, earnings_status, earnings_reason, earnings_warning = _score_earnings_from_values(
        revenue_growth=financials["revenue_growth"],
        operating_income_growth=financials["operating_income_growth"],
        net_income_growth=financials["net_income_growth"],
        latest_operating_income=financials["operating_income"],
        latest_net_income=financials["net_income"],
        fallback_score=financials["fallback_earnings_score"],
    )
    if earnings_status == "data_missing" and api_failure:
        earnings_reason = api_failure

    valuation_score, valuation_status, valuation_reason, valuation_warning = _score_valuation(
        financials["per"],
        financials["pbr"],
        financials["psr"],
        financials["roe"],
    )
    if valuation_status == "data_missing" and api_failure:
        valuation_reason = "PER/PBR 원자료 없음; " + api_failure

    source = source or ("DART/KIS" if market == "KR" else "Finnhub/SEC")
    updated_at = _first_nonempty(used, ["updated_at"], _now())
    out = {
        "symbol": symbol,
        "market": "한국주식" if market == "KR" else "미국주식",
        "name": name,
        "earnings_attempted": True,
        "earnings_success": earnings_status != "data_missing",
        "earnings_score": earnings_score,
        "earnings_data_status": earnings_status,
        "earnings_reason": earnings_reason,
        "earnings_warning": earnings_warning,
        "earnings_source": source,
        "revenue_growth": _blank_if_nan(financials["revenue_growth"]),
        "operating_income_growth": _blank_if_nan(financials["operating_income_growth"]),
        "net_income_growth": _blank_if_nan(financials["net_income_growth"]),
        "valuation_attempted": True,
        "valuation_success": valuation_status != "data_missing",
        "valuation_score": valuation_score,
        "valuation_data_status": valuation_status,
        "valuation_reason": valuation_reason,
        "valuation_warning": valuation_warning,
        "valuation_source": source,
        "per": _blank_if_nan(financials["per"]),
        "pbr": _blank_if_nan(financials["pbr"]),
        "psr": _blank_if_nan(financials["psr"]),
        "roe": _blank_if_nan(financials["roe"]),
        "market_cap": "" if math.isnan(financials["market_cap"]) else int(financials["market_cap"]),
        "data_source": source,
        "updated_at": updated_at,
    }
    return out


def apply_fundamental_valuation_scores(
    candidate_df: pd.DataFrame,
    *,
    fetch_missing: bool = False,
    file_hint: str = "",
    cache: dict[tuple[str, str], dict[str, Any]] | None = None,
    max_api_symbols: int = 8,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = candidate_df.copy() if candidate_df is not None else pd.DataFrame()
    for col in OUTPUT_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    if out.empty:
        return out, pd.DataFrame(columns=DETAIL_COLUMNS)

    cache = cache or _load_cache_rows()
    detail_rows: list[dict[str, Any]] = []
    api_count = 0
    for idx, row in out.iterrows():
        market, symbol = _candidate_key(row, file_hint=file_hint)
        use_fetch = fetch_missing and (market, symbol) not in cache and api_count < max_api_symbols
        if use_fetch:
            api_count += 1
            time.sleep(0.1)
        scored = build_row_scores(row, cache=cache, file_hint=file_hint, fetch_missing=use_fetch)
        for col in OUTPUT_COLUMNS:
            out.at[idx, col] = scored.get(col, "")
        if (
            scored.get("earnings_data_status") != "data_missing"
            and "catalyst_warnings" in out.columns
        ):
            out.at[idx, "catalyst_warnings"] = _remove_stale_earnings_warning(out.at[idx, "catalyst_warnings"])
        detail_rows.append({col: scored.get(col, "") for col in DETAIL_COLUMNS})
    detail = pd.DataFrame(detail_rows, columns=DETAIL_COLUMNS)
    return out, detail


def _summary_from_detail(detail: pd.DataFrame) -> dict[str, Any]:
    if detail is None or detail.empty:
        return {
            "updated_at": _now(),
            "earnings_target_count": 0,
            "earnings_success_count": 0,
            "earnings_failure_count": 0,
            "earnings_failure_reason_counts": {},
            "valuation_target_count": 0,
            "valuation_success_count": 0,
            "valuation_failure_count": 0,
            "valuation_failure_reason_counts": {},
            "api_usage": {"DART": False, "KIS": False, "Finnhub": False, "SEC": False},
            "detail_path": str(DETAIL_CSV),
        }
    earnings_success = detail["earnings_success"].astype(str).str.lower().isin(["true", "1", "1.0"])
    valuation_success = detail["valuation_success"].astype(str).str.lower().isin(["true", "1", "1.0"])
    source_text = " ".join(detail.get("data_source", pd.Series(dtype=str)).astype(str).tolist()).lower()
    earn_fail = detail.loc[~earnings_success, "earnings_reason"].astype(str).str.strip()
    val_fail = detail.loc[~valuation_success, "valuation_reason"].astype(str).str.strip()
    return {
        "updated_at": _now(),
        "earnings_target_count": int(len(detail)),
        "earnings_success_count": int(earnings_success.sum()),
        "earnings_failure_count": int((~earnings_success).sum()),
        "earnings_failure_reason_counts": dict(Counter(x or "실적 데이터 부족" for x in earn_fail)),
        "valuation_target_count": int(len(detail)),
        "valuation_success_count": int(valuation_success.sum()),
        "valuation_failure_count": int((~valuation_success).sum()),
        "valuation_failure_reason_counts": dict(Counter(x or "밸류 데이터 없음" for x in val_fail)),
        "api_usage": {
            "DART": "dart" in source_text,
            "KIS": "kis" in source_text,
            "Finnhub": "finnhub" in source_text,
            "SEC": "sec" in source_text,
        },
        "detail_path": str(DETAIL_CSV),
    }


def refresh_candidate_files(
    candidate_files: list[Path] | None = None,
    *,
    fetch_missing: bool = False,
    max_api_symbols: int = 8,
) -> dict[str, Any]:
    files = candidate_files or CANDIDATE_FILES
    cache = _load_cache_rows()
    detail_frames: list[pd.DataFrame] = []
    updated_files: list[str] = []
    for path in files:
        df = _read_csv(path)
        if df.empty and not path.exists():
            continue
        enriched, detail = apply_fundamental_valuation_scores(
            df,
            fetch_missing=fetch_missing,
            file_hint=path.name,
            cache=cache,
            max_api_symbols=max_api_symbols,
        )
        _write_csv(enriched, path)
        updated_files.append(str(path))
        if not detail.empty:
            detail["source_file"] = path.name
            detail_frames.append(detail)
    all_detail = pd.concat(detail_frames, ignore_index=True, sort=False) if detail_frames else pd.DataFrame(columns=DETAIL_COLUMNS)
    if not all_detail.empty:
        all_detail = all_detail.drop_duplicates(subset=["market", "symbol", "source_file"], keep="first")
    _write_csv(all_detail, DETAIL_CSV)
    summary = _summary_from_detail(all_detail)
    summary["updated_files"] = updated_files
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Try API refresh for symbols missing from local caches.")
    parser.add_argument("--max-api-symbols", type=int, default=8)
    args = parser.parse_args()
    summary = refresh_candidate_files(fetch_missing=args.refresh, max_api_symbols=max(0, args.max_api_symbols))
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
