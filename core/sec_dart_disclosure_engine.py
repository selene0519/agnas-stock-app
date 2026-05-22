from __future__ import annotations

import csv
import gzip
import html
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

SEC_CONFIG_PATH = PROJECT_ROOT / "sec_config.json"
SEC_CONFIG_EXAMPLE_PATH = PROJECT_ROOT / "sec_config.example.json"
SEC_CIK_CACHE = DATA_DIR / "sec_cik_cache.csv"
SEC_RECENT_FILINGS = DATA_DIR / "sec_recent_filings.csv"
SEC_FILING_TEXT_CACHE = DATA_DIR / "sec_filing_text_cache.csv"

DART_ORIGINAL_TEXT_CACHE = DATA_DIR / "dart_original_text_cache.csv"
DART_DOCUMENT_SUMMARY_CACHE = DATA_DIR / "dart_document_summary_cache.csv"
KR_FINANCIAL_METRICS = DATA_DIR / "kr_financial_metrics.csv"
KR_MARKET_CAP_CACHE = DATA_DIR / "kr_market_cap_cache.csv"

SEC_FILING_COLUMNS = [
    "ticker",
    "cik",
    "market",
    "company_name",
    "form_type",
    "filing_date",
    "filed_at",
    "accession_no",
    "title",
    "filing_url",
    "risk_label",
    "risk_keywords",
    "sec_risk_level",
    "judgment",
    "source",
    "checked_at",
    "updated_at",
    "status",
]

SEC_CIK_COLUMNS = ["ticker", "cik", "company_name", "updated_at", "status"]

SEC_TEXT_COLUMNS = [
    "ticker",
    "form_type",
    "accession_no",
    "filing_url",
    "text_excerpt",
    "risk_keywords",
    "updated_at",
    "status",
]

DART_TEXT_COLUMNS = [
    "rcept_no",
    "corp_code",
    "corp_name",
    "report_nm",
    "document_text",
    "updated_at",
    "status",
]

DART_SUMMARY_COLUMNS = [
    "rcept_no",
    "corp_code",
    "corp_name",
    "report_nm",
    "contract_amount",
    "equity_ratio_pct",
    "sales_ratio_pct",
    "issue_shares",
    "conversion_price",
    "investment_amount",
    "dividend_per_share",
    "audit_opinion",
    "risk_keywords",
    "disclosure_risk_level",
    "judgment",
    "updated_at",
    "status",
]

KR_FINANCIAL_COLUMNS = [
    "ticker",
    "market",
    "corp_name",
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "market_cap",
    "market_cap_source",
    "per",
    "roe",
    "debt_ratio",
    "operating_margin",
    "net_margin",
    "revenue_growth",
    "financial_judgment",
    "updated_at",
    "status",
]

SEC_RISK_KEYWORDS = [
    "material weakness",
    "going concern",
    "substantial doubt",
    "impairment",
    "restructuring",
    "restatement",
    "investigation",
    "lawsuit",
    "default",
    "delisting",
    "liquidity risk",
    "customer concentration",
    "guidance withdrawn",
]

DART_RISK_KEYWORDS = [
    "감사의견 거절",
    "한정의견",
    "상장폐지",
    "관리종목",
    "투자주의환기",
    "유상증자",
    "전환사채",
    "신주인수권부사채",
    "횡령",
    "배임",
    "소송",
    "채무불이행",
    "자본잠식",
]

INVESTMENT_PURPOSES: dict[str, dict[str, Any]] = {
    "단기 스윙": {
        "prefer": ["거래대금", "거래량", "confidence_score", "손익비"],
        "avoid": ["no_buy_score", "market_risk_score"],
        "description": "거래대금 증가와 손익비를 우선 보고, 매수금지 점수가 높으면 제외합니다.",
    },
    "안정 성장": {
        "prefer": ["roe", "revenue_growth", "operating_margin"],
        "avoid": ["debt_ratio", "no_buy_score"],
        "description": "ROE, 매출 성장, 영업이익률을 우선 보고 부채 부담을 낮게 봅니다.",
    },
    "실적 개선": {
        "prefer": ["revenue_growth", "operating_margin", "net_margin"],
        "avoid": ["debt_ratio"],
        "description": "매출 성장과 수익성 개선 흐름을 우선합니다.",
    },
    "저평가": {
        "prefer": ["roe"],
        "avoid": ["per", "debt_ratio", "no_buy_score"],
        "description": "PER/부채 부담은 낮고 ROE가 양호한 종목을 우선합니다.",
    },
    "배당": {
        "prefer": ["dividend_per_share", "dividend_yield"],
        "avoid": ["no_buy_score"],
        "description": "배당 관련 공시와 배당률이 있는 종목을 우선합니다.",
    },
    "고위험 성장": {
        "prefer": ["revenue_growth", "confidence_score"],
        "avoid": ["delisting", "capital_impairment"],
        "description": "성장성은 보되 상장폐지·자본잠식 위험은 제외합니다.",
    },
    "공시 리스크 회피": {
        "prefer": ["confidence_score"],
        "avoid": ["sec_risk_level", "disclosure_risk_level", "no_buy_score"],
        "description": "SEC/DART 위험 키워드가 있는 종목을 보수적으로 낮춥니다.",
    },
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_disclosure_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_csv(SEC_CIK_CACHE, SEC_CIK_COLUMNS)
    _ensure_csv(SEC_RECENT_FILINGS, SEC_FILING_COLUMNS)
    _ensure_csv(SEC_FILING_TEXT_CACHE, SEC_TEXT_COLUMNS)
    _ensure_csv(DART_ORIGINAL_TEXT_CACHE, DART_TEXT_COLUMNS)
    _ensure_csv(DART_DOCUMENT_SUMMARY_CACHE, DART_SUMMARY_COLUMNS)
    _ensure_csv(KR_FINANCIAL_METRICS, KR_FINANCIAL_COLUMNS)
    _ensure_csv(KR_MARKET_CAP_CACHE, ["ticker", "market_cap", "shares", "price", "source", "updated_at", "status"])


def _ensure_csv(path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        try:
            df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
            changed = False
            for col in columns:
                if col not in df.columns:
                    df[col] = ""
                    changed = True
            if changed:
                df.to_csv(path, index=False, encoding="utf-8-sig")
        except Exception:
            pass
        return
    pd.DataFrame(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")


def read_csv_safe(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame(columns=columns or [])
        return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    except Exception:
        return pd.DataFrame(columns=columns or [])


def _decode_http_bytes(raw: bytes) -> str:
    if raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def load_sec_api_key() -> tuple[str, dict[str, Any]]:
    cfg: dict[str, Any] = {}
    if SEC_CONFIG_PATH.exists():
        try:
            cfg = json.loads(SEC_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    if SEC_CONFIG_PATH.exists() and cfg.get("enabled") is False:
        return "", cfg
    token = str(cfg.get("api_key") or cfg.get("token") or os.environ.get("SEC_API_KEY") or os.environ.get("SEC_API_TOKEN") or "").strip()
    return token, cfg


def load_dart_api_key() -> str:
    candidates = [PROJECT_ROOT / "dart_config.json", PROJECT_ROOT / "dart_config_template.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            token = str(cfg.get("api_key") or cfg.get("crtfc_key") or cfg.get("dart_api_key") or "").strip()
            if token and "YOUR" not in token.upper():
                return token
        except Exception:
            continue
    return str(os.environ.get("DART_API_KEY") or "").strip()


def load_us_symbols(limit: int = 20) -> list[str]:
    paths = [
        PROJECT_ROOT / "holdings_us.csv",
        PROJECT_ROOT / "data" / "holdings_us.csv",
        PROJECT_ROOT / "watchlist_us.csv",
        PROJECT_ROOT / "watchlist_us_growth.csv",
        PROJECT_ROOT / "candidate_universe_us.csv",
    ]
    symbols: list[str] = []
    for path in paths:
        df = read_csv_safe(path)
        if df.empty:
            continue
        col = _first_col(df, ["ticker", "symbol", "종목코드", "종목"])
        if not col:
            continue
        for raw in df[col].astype(str).tolist():
            sym = re.sub(r"[^A-Za-z.\-]", "", raw).upper().strip()
            if sym and sym not in symbols:
                symbols.append(sym)
            if len(symbols) >= limit:
                return symbols
    return symbols[:limit]


def load_kr_symbols(limit: int = 12) -> list[str]:
    paths = [
        PROJECT_ROOT / "holdings_kr.csv",
        PROJECT_ROOT / "data" / "holdings_kr.csv",
        PROJECT_ROOT / "watchlist_kr.csv",
        PROJECT_ROOT / "watchlist_kr_growth.csv",
        PROJECT_ROOT / "candidate_universe_kr.csv",
    ]
    symbols: list[str] = []
    for path in paths:
        df = read_csv_safe(path)
        if df.empty:
            continue
        col = _first_col(df, ["ticker", "symbol", "종목코드", "종목"])
        if not col:
            continue
        for raw in df[col].astype(str).tolist():
            sym = _normalize_kr_ticker(raw)
            if sym and sym not in symbols:
                symbols.append(sym)
            if len(symbols) >= limit:
                return symbols
    return symbols[:limit]


def _first_col(df: pd.DataFrame, names: list[str]) -> str:
    lower_map = {str(c).lower(): c for c in df.columns}
    for name in names:
        if name in df.columns:
            return name
        if name.lower() in lower_map:
            return str(lower_map[name.lower()])
    return ""


def detect_risk_keywords(text: str, keywords: list[str]) -> list[str]:
    source = str(text or "").lower()
    found: list[str] = []
    for kw in keywords:
        if kw.lower() in source and kw not in found:
            found.append(kw)
    return found


def classify_risk_level(keywords: list[str]) -> tuple[str, str]:
    if not keywords:
        return "낮음", "공시 위험 키워드 제한"
    if len(keywords) >= 3:
        return "높음", "위험 키워드 다수 확인 필요"
    return "주의", "위험 키워드 확인 필요"


def classify_sec_filing_risk(text: str, form_type: str = "") -> dict[str, Any]:
    keywords = detect_risk_keywords(f"{form_type} {text}", SEC_RISK_KEYWORDS)
    level, judgment = classify_risk_level(keywords)
    return {
        "risk_label": level,
        "risk_keywords": " / ".join(keywords),
        "judgment": judgment,
    }


def fetch_sec_company_tickers() -> pd.DataFrame:
    ensure_disclosure_files()
    req = urllib.request.Request(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": "stock-app disclosure cache contact@example.com"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.loads(_decode_http_bytes(resp.read()))
    rows = []
    for item in payload.values() if isinstance(payload, dict) else []:
        ticker = str(item.get("ticker", "")).upper().strip()
        cik = str(item.get("cik_str", "")).zfill(10)
        if ticker and cik:
            rows.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "company_name": item.get("title", ""),
                    "updated_at": _now(),
                    "status": "OK",
                }
            )
    out = pd.DataFrame(rows, columns=SEC_CIK_COLUMNS)
    out.to_csv(SEC_CIK_CACHE, index=False, encoding="utf-8-sig")
    return out


def resolve_sec_cik_for_ticker(ticker: str, *, refresh: bool = False) -> tuple[str, str]:
    ensure_disclosure_files()
    ticker = str(ticker or "").upper().strip()
    cache = read_csv_safe(SEC_CIK_CACHE, SEC_CIK_COLUMNS)
    if refresh or cache.empty:
        try:
            cache = fetch_sec_company_tickers()
        except Exception:
            cache = read_csv_safe(SEC_CIK_CACHE, SEC_CIK_COLUMNS)
    if cache.empty or not ticker:
        return "", ""
    hit = cache[cache["ticker"].astype(str).str.upper().eq(ticker)]
    if hit.empty:
        return "", ""
    row = hit.iloc[0]
    return str(row.get("cik", "")).zfill(10), str(row.get("company_name", ""))


def fetch_sec_recent_filings_from_edgar(ticker: str, *, limit: int = 20) -> list[dict[str, Any]]:
    cik, company_name = resolve_sec_cik_for_ticker(ticker)
    if not cik:
        return []
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "stock-app disclosure cache contact@example.com"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.loads(_decode_http_bytes(resp.read()))
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", []) or []
    dates = recent.get("filingDate", []) or []
    accession = recent.get("accessionNumber", []) or []
    docs = recent.get("primaryDocument", []) or []
    descriptions = recent.get("primaryDocDescription", []) or []
    rows: list[dict[str, Any]] = []
    for idx, form in enumerate(forms):
        if str(form) not in {"10-K", "10-Q", "8-K"}:
            continue
        acc = str(accession[idx] if idx < len(accession) else "")
        acc_nodash = acc.replace("-", "")
        doc = str(docs[idx] if idx < len(docs) else "")
        filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/{doc}" if acc and doc else ""
        title = str(descriptions[idx] if idx < len(descriptions) else form)
        risk = classify_sec_filing_risk(title, str(form))
        rows.append(
            {
                "ticker": str(ticker).upper(),
                "cik": cik,
                "market": "미국주식",
                "company_name": company_name,
                "form_type": form,
                "filing_date": str(dates[idx] if idx < len(dates) else ""),
                "filed_at": str(dates[idx] if idx < len(dates) else ""),
                "accession_no": acc,
                "title": title,
                "filing_url": filing_url,
                "risk_label": risk["risk_label"],
                "risk_keywords": risk["risk_keywords"],
                "sec_risk_level": risk["risk_label"],
                "judgment": risk["judgment"],
                "source": "sec.gov",
                "checked_at": _now(),
                "updated_at": _now(),
                "status": "OK",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def fetch_sec_recent_filings_for_symbol(
    symbol: str,
    api_key: str,
    *,
    days: int = 30,
    forms: tuple[str, ...] = ("10-K", "10-Q", "8-K"),
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not api_key:
        return []
    start = (datetime.now() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d")
    form_query = " OR ".join(f'formType:"{form}"' for form in forms)
    query = {
        "query": {
            "query_string": {
                "query": f'ticker:{symbol.upper()} AND ({form_query}) AND filedAt:[{start} TO *]'
            }
        },
        "from": "0",
        "size": str(max(1, int(limit))),
        "sort": [{"filedAt": {"order": "desc"}}],
    }
    url = "https://api.sec-api.io?" + urllib.parse.urlencode({"token": api_key})
    req = urllib.request.Request(
        url,
        data=json.dumps(query).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "stock-app disclosure cache"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(_decode_http_bytes(resp.read()))
    filings = payload.get("filings") or []
    out: list[dict[str, Any]] = []
    for item in filings:
        title = str(item.get("description") or item.get("formType") or "")
        risk = classify_sec_filing_risk(" ".join([title, str(item.get("documentFormatFiles", ""))]), str(item.get("formType", "")))
        out.append(
            {
                "ticker": symbol.upper(),
                "cik": str(item.get("cik", "") or "").zfill(10) if item.get("cik", "") else "",
                "market": "미국주식",
                "company_name": item.get("companyName", ""),
                "form_type": item.get("formType", ""),
                "filing_date": item.get("filedAt", ""),
                "filed_at": item.get("filedAt", ""),
                "accession_no": item.get("accessionNo", ""),
                "title": title,
                "filing_url": item.get("linkToFilingDetails") or item.get("linkToHtml") or "",
                "risk_label": risk["risk_label"],
                "risk_keywords": risk["risk_keywords"],
                "sec_risk_level": risk["risk_label"],
                "judgment": risk["judgment"],
                "source": "sec-api.io",
                "checked_at": _now(),
                "updated_at": _now(),
                "status": "OK",
            }
        )
    return out


def build_us_sec_watch_table(*, refresh: bool = False, max_symbols: int = 20, days: int = 30) -> dict[str, Any]:
    ensure_disclosure_files()
    cache = read_csv_safe(SEC_RECENT_FILINGS, SEC_FILING_COLUMNS)
    if not refresh:
        return {"ok": True, "rows": int(len(cache)), "path": str(SEC_RECENT_FILINGS), "message": "cache_only"}

    api_key, cfg = load_sec_api_key()
    sec_enabled = bool(cfg.get("enabled", False)) if cfg else bool(api_key)
    if not api_key and not sec_enabled:
        return {"ok": True, "rows": int(len(cache)), "path": str(SEC_RECENT_FILINGS), "message": "SEC API 키 없음: 캐시만 사용"}

    symbols = load_us_symbols(limit=max_symbols)
    if not symbols:
        return {"ok": True, "rows": int(len(cache)), "path": str(SEC_RECENT_FILINGS), "message": "미국 관심종목 없음"}

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for sym in symbols:
        try:
            if api_key:
                rows.extend(fetch_sec_recent_filings_for_symbol(sym, api_key, days=days))
            else:
                rows.extend(fetch_sec_recent_filings_from_edgar(sym, limit=10))
        except urllib.error.HTTPError as exc:
            errors.append(f"{sym}:HTTP {exc.code}")
        except Exception as exc:
            errors.append(f"{sym}:{exc.__class__.__name__}")

    if rows:
        fresh = pd.DataFrame(rows, columns=SEC_FILING_COLUMNS)
        combined = pd.concat([fresh, cache], ignore_index=True)
        key_cols = [c for c in ["ticker", "accession_no", "form_type", "filed_at"] if c in combined.columns]
        if key_cols:
            combined = combined.drop_duplicates(subset=key_cols, keep="first")
        combined = combined.reindex(columns=SEC_FILING_COLUMNS, fill_value="")
        combined.to_csv(SEC_RECENT_FILINGS, index=False, encoding="utf-8-sig")
        cache = combined

    msg = "갱신 완료"
    if errors:
        msg += "; " + "; ".join(errors[:8])
    return {"ok": True, "rows": int(len(cache)), "path": str(SEC_RECENT_FILINGS), "message": msg}


def fetch_sec_filing_text(filing_url: str) -> str:
    if not filing_url:
        return ""
    req = urllib.request.Request(
        filing_url,
        headers={"User-Agent": "stock-app disclosure cache"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return normalize_document_text(raw)


def fetch_dart_original_document(rcept_no: str, api_key: str | None = None) -> bytes:
    api_key = api_key or load_dart_api_key()
    if not api_key or not rcept_no:
        return b""
    params = urllib.parse.urlencode({"crtfc_key": api_key, "rcept_no": rcept_no})
    url = "https://opendart.fss.or.kr/api/document.xml?" + params
    req = urllib.request.Request(url, headers={"User-Agent": "stock-app dart document cache"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def dart_corp_code_for_symbol(symbol: str) -> tuple[str, str]:
    path = DATA_DIR / "dart_corp_codes.csv"
    df = read_csv_safe(path)
    if df.empty:
        return "", ""
    code = _normalize_kr_ticker(symbol)
    stock_col = _first_col(df, ["stock_code", "종목코드"])
    corp_col = _first_col(df, ["corp_code", "고유번호"])
    name_col = _first_col(df, ["corp_name", "corp_name_eng", "회사명", "종목명"])
    if not stock_col or not corp_col:
        return "", ""
    hit = df[df[stock_col].astype(str).str.zfill(6).eq(code)]
    if hit.empty:
        return "", ""
    row = hit.iloc[0]
    return str(row.get(corp_col, "")).strip(), str(row.get(name_col, "")).strip() if name_col else ""


def fetch_dart_recent_disclosures_for_symbol(symbol: str, api_key: str, *, days: int = 7, page_count: int = 10) -> list[dict[str, str]]:
    corp_code, corp_name = dart_corp_code_for_symbol(symbol)
    if not api_key or not corp_code:
        return []
    end = datetime.now()
    begin = end - timedelta(days=max(1, int(days)))
    params = urllib.parse.urlencode(
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": begin.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"),
            "page_no": 1,
            "page_count": max(1, min(100, int(page_count))),
            "sort": "date",
            "sort_mth": "desc",
        }
    )
    req = urllib.request.Request("https://opendart.fss.or.kr/api/list.json?" + params, headers={"User-Agent": "stock-app dart cache"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(_decode_http_bytes(resp.read()))
    if str(payload.get("status", "")) not in {"000", "013"}:
        return []
    out: list[dict[str, str]] = []
    for item in payload.get("list", []) or []:
        out.append(
            {
                "rcept_no": str(item.get("rcept_no", "") or ""),
                "corp_code": corp_code,
                "corp_name": str(item.get("corp_name", "") or corp_name),
                "report_nm": str(item.get("report_nm", "") or ""),
            }
        )
    return out


def build_dart_original_text_cache_from_watchlist(
    *,
    refresh: bool = False,
    max_symbols: int = 8,
    days: int = 7,
    max_documents: int = 10,
) -> dict[str, Any]:
    ensure_disclosure_files()
    cache = read_csv_safe(DART_ORIGINAL_TEXT_CACHE, DART_TEXT_COLUMNS)
    if not refresh:
        return {"ok": True, "rows": int(len(cache)), "path": str(DART_ORIGINAL_TEXT_CACHE), "message": "cache_only"}
    api_key = load_dart_api_key()
    if not api_key:
        return {"ok": True, "rows": int(len(cache)), "path": str(DART_ORIGINAL_TEXT_CACHE), "message": "DART API 키 없음: 캐시만 사용"}
    symbols = load_kr_symbols(limit=max_symbols)
    if not symbols:
        return {"ok": True, "rows": int(len(cache)), "path": str(DART_ORIGINAL_TEXT_CACHE), "message": "한국 관심종목 없음"}

    existing = set(cache.get("rcept_no", pd.Series(dtype=str)).astype(str).tolist()) if not cache.empty else set()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for sym in symbols:
        if len(rows) >= max_documents:
            break
        try:
            disclosures = fetch_dart_recent_disclosures_for_symbol(sym, api_key, days=days, page_count=8)
        except Exception as exc:
            errors.append(f"{sym}:{exc.__class__.__name__}")
            continue
        for item in disclosures:
            rcept_no = str(item.get("rcept_no", ""))
            if not rcept_no or rcept_no in existing:
                continue
            try:
                raw = fetch_dart_original_document(rcept_no, api_key)
                text = extract_dart_document_text(raw)
                rows.append(
                    {
                        "rcept_no": rcept_no,
                        "corp_code": item.get("corp_code", ""),
                        "corp_name": item.get("corp_name", ""),
                        "report_nm": item.get("report_nm", ""),
                        "document_text": text[:60000],
                        "updated_at": _now(),
                        "status": "OK" if text else "DATA_MISSING",
                    }
                )
                existing.add(rcept_no)
            except Exception as exc:
                errors.append(f"{rcept_no}:{exc.__class__.__name__}")
            if len(rows) >= max_documents:
                break

    if rows:
        combined = pd.concat([pd.DataFrame(rows, columns=DART_TEXT_COLUMNS), cache], ignore_index=True)
        combined = combined.drop_duplicates(subset=["rcept_no"], keep="first")
        combined = combined.reindex(columns=DART_TEXT_COLUMNS, fill_value="")
        combined.to_csv(DART_ORIGINAL_TEXT_CACHE, index=False, encoding="utf-8-sig")
        build_dart_document_summary_cache(refresh=False)
        cache = combined
    msg = f"DART 원문 {len(rows)}건 수집"
    if errors:
        msg += "; " + "; ".join(errors[:8])
    return {"ok": True, "rows": int(len(cache)), "path": str(DART_ORIGINAL_TEXT_CACHE), "message": msg}


def extract_dart_document_text(raw: bytes | str) -> str:
    if isinstance(raw, str) and raw.strip().isdigit():
        try:
            raw = fetch_dart_original_document(raw.strip())
        except Exception:
            return "원문 추출 실패"
    if not raw:
        return ""
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.lower().endswith((".xml", ".html", ".htm", ".txt")):
                    chunks.append(zf.read(name).decode("utf-8", errors="replace"))
    except zipfile.BadZipFile:
        chunks.append(raw.decode("utf-8", errors="replace"))
    return normalize_document_text("\n".join(chunks))


def normalize_document_text(text: str) -> str:
    text = html.unescape(str(text or ""))
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_dart_key_numbers(text: str) -> dict[str, str]:
    source = str(text or "")

    def find(patterns: list[str]) -> str:
        for pat in patterns:
            m = re.search(pat, source, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    return {
        "contract_amount": find([r"계약금액[^0-9\-]*([0-9,\.]+)\s*(?:원|천원|백만원|억원)?", r"계약\s*금액[^0-9\-]*([0-9,\.]+)"]),
        "equity_ratio_pct": find([r"자기자본\s*대비[^0-9\-]*([0-9,\.]+)\s*%", r"자본\s*대비[^0-9\-]*([0-9,\.]+)\s*%"]),
        "sales_ratio_pct": find([r"매출액\s*대비[^0-9\-]*([0-9,\.]+)\s*%", r"최근\s*매출액\s*대비[^0-9\-]*([0-9,\.]+)\s*%"]),
        "issue_shares": find([r"발행(?:예정)?주식(?:수)?[^0-9\-]*([0-9,\.]+)\s*주"]),
        "conversion_price": find([r"전환가액[^0-9\-]*([0-9,\.]+)\s*원"]),
        "investment_amount": find([r"투자금액[^0-9\-]*([0-9,\.]+)\s*(?:원|천원|백만원|억원)?"]),
        "dividend_per_share": find([r"주당\s*배당금[^0-9\-]*([0-9,\.]+)\s*원"]),
        "audit_opinion": find([r"감사의견[^가-힣A-Za-z]*(적정|한정|의견거절|부적정)"]),
    }


def parse_dart_key_numbers(text: str, report_name: str = "") -> dict[str, str]:
    out = extract_dart_key_numbers(f"{report_name}\n{text}")
    return out


def cache_dart_document_text(rcept_no: str, corp_code: str = "", corp_name: str = "", report_nm: str = "") -> dict[str, Any]:
    ensure_disclosure_files()
    cache = read_csv_safe(DART_ORIGINAL_TEXT_CACHE, DART_TEXT_COLUMNS)
    if rcept_no and not cache.empty and "rcept_no" in cache.columns:
        hit = cache[cache["rcept_no"].astype(str).eq(str(rcept_no))]
        if not hit.empty:
            return {"ok": True, "status": "CACHED", "text": str(hit.iloc[0].get("document_text", ""))}
    try:
        raw = fetch_dart_original_document(rcept_no)
        text = extract_dart_document_text(raw)
        row = {
            "rcept_no": rcept_no,
            "corp_code": corp_code,
            "corp_name": corp_name,
            "report_nm": report_nm,
            "document_text": text[:60000],
            "updated_at": _now(),
            "status": "OK" if text and text != "원문 추출 실패" else "ERROR",
        }
        combined = pd.concat([pd.DataFrame([row], columns=DART_TEXT_COLUMNS), cache], ignore_index=True)
        combined = combined.drop_duplicates(subset=["rcept_no"], keep="first")
        combined.to_csv(DART_ORIGINAL_TEXT_CACHE, index=False, encoding="utf-8-sig")
        build_dart_document_summary_cache(refresh=False)
        return {"ok": True, "status": row["status"], "text": text}
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "text": "원문 추출 실패", "error": f"{exc.__class__.__name__}: {exc}"}


def build_dart_document_summary_cache(*, refresh: bool = False, max_documents: int = 10) -> dict[str, Any]:
    ensure_disclosure_files()
    text_cache = read_csv_safe(DART_ORIGINAL_TEXT_CACHE, DART_TEXT_COLUMNS)
    summary = read_csv_safe(DART_DOCUMENT_SUMMARY_CACHE, DART_SUMMARY_COLUMNS)
    if text_cache.empty:
        return {"ok": True, "rows": int(len(summary)), "path": str(DART_DOCUMENT_SUMMARY_CACHE), "message": "DART 원문 캐시 없음"}

    rows: list[dict[str, Any]] = []
    for _, row in text_cache.head(max_documents if refresh else len(text_cache)).iterrows():
        text = str(row.get("document_text", ""))
        numbers = extract_dart_key_numbers(text)
        kws = detect_risk_keywords(text, DART_RISK_KEYWORDS)
        level, judgment = classify_risk_level(kws)
        rows.append(
            {
                "rcept_no": row.get("rcept_no", ""),
                "corp_code": row.get("corp_code", ""),
                "corp_name": row.get("corp_name", ""),
                "report_nm": row.get("report_nm", ""),
                **numbers,
                "risk_keywords": " / ".join(kws),
                "disclosure_risk_level": level,
                "judgment": judgment,
                "updated_at": _now(),
                "status": "OK" if text else "DATA_MISSING",
            }
        )
    out = pd.DataFrame(rows, columns=DART_SUMMARY_COLUMNS)
    out.to_csv(DART_DOCUMENT_SUMMARY_CACHE, index=False, encoding="utf-8-sig")
    return {"ok": True, "rows": int(len(out)), "path": str(DART_DOCUMENT_SUMMARY_CACHE), "message": "DART 원문 요약 캐시 생성"}


def calculate_kr_per_roe_debt_ratio(row: dict[str, Any]) -> dict[str, float | str]:
    revenue = _to_num(row.get("revenue"))
    operating_income = _to_num(row.get("operating_income"))
    net_income = _to_num(row.get("net_income"))
    liabilities = _to_num(row.get("total_liabilities"))
    equity = _to_num(row.get("total_equity"))
    market_cap = _to_num(row.get("market_cap"))
    per = market_cap / net_income if market_cap and net_income and net_income > 0 else ""
    roe = (net_income / equity * 100) if equity and net_income else ""
    debt_ratio = (liabilities / equity * 100) if equity and liabilities else ""
    operating_margin = (operating_income / revenue * 100) if revenue and operating_income else ""
    net_margin = (net_income / revenue * 100) if revenue and net_income else ""
    return {
        "per": _round_or_blank(per),
        "roe": _round_or_blank(roe),
        "debt_ratio": _round_or_blank(debt_ratio),
        "operating_margin": _round_or_blank(operating_margin),
        "net_margin": _round_or_blank(net_margin),
    }


def calculate_kr_financial_ratios(symbol: str, financial_items: dict[str, Any], market_snapshot: Any = None) -> dict[str, Any]:
    base = dict(financial_items or {})
    base["ticker"] = _normalize_kr_ticker(symbol)
    if not _to_num(base.get("market_cap")):
        cap_info = lookup_kr_market_cap(symbol, market_snapshot=market_snapshot)
        base["market_cap"] = cap_info.get("market_cap", "")
        base["market_cap_source"] = cap_info.get("source", "")
    else:
        base["market_cap_source"] = base.get("market_cap_source", "provided")
    ratios = calculate_kr_per_roe_debt_ratio(base)
    if not ratios.get("per"):
        ratios["per"] = "확인 필요"
    return {**base, **ratios}


def _to_num(value: Any) -> float | None:
    try:
        text = str(value).replace(",", "").replace("%", "").replace("원", "").replace("$", "").strip()
        if text in {"", "nan", "None"}:
            return None
        return float(text)
    except Exception:
        return None


def _find_market_cap_in_frame(df: pd.DataFrame, symbol: str) -> tuple[str, str]:
    if df is None or df.empty:
        return "", ""
    code = _normalize_kr_ticker(symbol)
    ticker_col = _first_col(df, ["ticker", "symbol", "stock_code", "종목코드", "종목"])
    if ticker_col:
        work = df[df[ticker_col].astype(str).map(_normalize_kr_ticker).eq(code)].copy()
    else:
        work = df.copy()
    if work.empty:
        return "", ""
    row = work.iloc[0]
    cap_col = _first_col(work, ["market_cap", "marcap", "시가총액", "상장시가총액"])
    if cap_col:
        cap = _to_num(row.get(cap_col))
        if cap and cap > 0:
            return str(int(cap)), f"file:{cap_col}"
    price_col = _first_col(work, ["current_price", "last_price", "close", "현재가", "종가"])
    shares_col = _first_col(work, ["shares", "listed_shares", "outstanding_shares", "상장주식수", "발행주식수"])
    price = _to_num(row.get(price_col)) if price_col else None
    shares = _to_num(row.get(shares_col)) if shares_col else None
    if price and shares:
        return str(int(price * shares)), f"file:{price_col}*{shares_col}"
    return "", ""


def lookup_kr_market_cap(symbol: str, market_snapshot: Any = None, *, refresh: bool = False) -> dict[str, Any]:
    """Find KR market cap from local caches first, then FinanceDataReader/Naver fallback.

    PER remains 확인 필요 when no market cap can be found.
    """
    ensure_disclosure_files()
    code = _normalize_kr_ticker(symbol)
    if not code:
        return {"market_cap": "", "source": "ticker 없음", "status": "DATA_MISSING"}

    if isinstance(market_snapshot, dict):
        cap, source = _find_market_cap_in_frame(pd.DataFrame([market_snapshot]), code)
        if cap:
            return {"market_cap": cap, "source": source, "status": "OK"}
    elif isinstance(market_snapshot, pd.DataFrame):
        cap, source = _find_market_cap_in_frame(market_snapshot, code)
        if cap:
            return {"market_cap": cap, "source": source, "status": "OK"}

    cache = read_csv_safe(KR_MARKET_CAP_CACHE)
    if not refresh and not cache.empty:
        hit = cache[cache.get("ticker", pd.Series(dtype=str)).astype(str).map(_normalize_kr_ticker).eq(code)]
        if not hit.empty:
            row = hit.iloc[0]
            cap = _to_num(row.get("market_cap"))
            if cap and cap > 0:
                return {"market_cap": str(int(cap)), "source": row.get("source", "kr_market_cap_cache"), "status": "OK"}

    local_files = [
        DATA_DIR / "fundamentals" / "kr_fundamentals.csv",
        DATA_DIR / "kr_fundamentals.csv",
        PROJECT_ROOT / "kr_fundamentals.csv",
        PROJECT_ROOT / "candidate_universe_kr.csv",
        PROJECT_ROOT / "watchlist_kr_growth.csv",
        PROJECT_ROOT / "watchlist_kr.csv",
        PROJECT_ROOT / "predictions.csv",
        DATA_DIR / "portfolio_response_summary.csv",
    ]
    for path in local_files:
        df = read_csv_safe(path)
        cap, source = _find_market_cap_in_frame(df, code)
        if cap:
            row = {"ticker": code, "market_cap": cap, "shares": "", "price": "", "source": f"{path.name}:{source}", "updated_at": _now(), "status": "OK"}
            _upsert_market_cap_cache(row)
            return {"market_cap": cap, "source": row["source"], "status": "OK"}

    try:
        import FinanceDataReader as fdr

        listing = fdr.StockListing("KRX")
        cap, source = _find_market_cap_in_frame(listing.rename(columns={"Code": "ticker", "Marcap": "market_cap", "Stocks": "shares", "Close": "price"}), code)
        if cap:
            row = {"ticker": code, "market_cap": cap, "shares": "", "price": "", "source": f"FinanceDataReader:{source}", "updated_at": _now(), "status": "OK"}
            _upsert_market_cap_cache(row)
            return {"market_cap": cap, "source": row["source"], "status": "OK"}
    except Exception:
        pass

    try:
        import requests
        from bs4 import BeautifulSoup

        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        m = re.search(r"시가총액\s*([0-9,]+)\s*억원", text)
        if m:
            cap = str(int(float(m.group(1).replace(",", "")) * 100_000_000))
            row = {"ticker": code, "market_cap": cap, "shares": "", "price": "", "source": "Naver Finance", "updated_at": _now(), "status": "OK"}
            _upsert_market_cap_cache(row)
            return {"market_cap": cap, "source": "Naver Finance", "status": "OK"}
    except Exception:
        pass

    return {"market_cap": "", "source": "market_cap 없음", "status": "DATA_MISSING"}


def _upsert_market_cap_cache(row: dict[str, Any]) -> None:
    cache = read_csv_safe(KR_MARKET_CAP_CACHE)
    new = pd.DataFrame([row])
    out = pd.concat([new, cache], ignore_index=True)
    out["ticker"] = out["ticker"].astype(str).map(_normalize_kr_ticker)
    out = out.drop_duplicates(subset=["ticker"], keep="first")
    out.to_csv(KR_MARKET_CAP_CACHE, index=False, encoding="utf-8-sig")


def _round_or_blank(value: Any) -> str:
    if value == "" or value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except Exception:
        return ""


def build_kr_financial_metrics(*, refresh: bool = False) -> dict[str, Any]:
    ensure_disclosure_files()
    candidates = [
        DATA_DIR / "fundamentals" / "kr_fundamentals.csv",
        DATA_DIR / "kr_fundamentals.csv",
        PROJECT_ROOT / "kr_fundamentals.csv",
    ]
    source = next((p for p in candidates if p.exists() and p.stat().st_size > 0), None)
    if source is None:
        return {"ok": True, "rows": 0, "path": str(KR_FINANCIAL_METRICS), "message": "한국 재무 원천 캐시 없음"}
    df = read_csv_safe(source)
    if df.empty:
        return {"ok": True, "rows": 0, "path": str(KR_FINANCIAL_METRICS), "message": "한국 재무 원천 캐시 비어 있음"}
    rows: list[dict[str, Any]] = []
    for _, src in df.iterrows():
        base = {
            "ticker": _normalize_kr_ticker(src.get(_first_col(df, ["ticker", "symbol", "종목코드", "종목"]), "")),
            "market": "한국주식",
            "corp_name": src.get(_first_col(df, ["corp_name", "name", "종목명", "회사명"]), ""),
            "revenue": src.get(_first_col(df, ["revenue", "sales", "매출액"]), ""),
            "operating_income": src.get(_first_col(df, ["operating_income", "영업이익"]), ""),
            "net_income": src.get(_first_col(df, ["net_income", "당기순이익", "순이익"]), ""),
            "total_assets": src.get(_first_col(df, ["total_assets", "자산총계"]), ""),
            "total_liabilities": src.get(_first_col(df, ["total_liabilities", "부채총계"]), ""),
            "total_equity": src.get(_first_col(df, ["total_equity", "자본총계"]), ""),
            "market_cap": src.get(_first_col(df, ["market_cap", "시가총액"]), ""),
            "revenue_growth": src.get(_first_col(df, ["revenue_growth", "매출성장률"]), ""),
        }
        enriched = calculate_kr_financial_ratios(base.get("ticker", ""), base)
        metrics = {k: enriched.get(k, "") for k in ["per", "roe", "debt_ratio", "operating_margin", "net_margin"]}
        judgment = "계산 가능" if any(v not in ("", "확인 필요") for v in metrics.values()) else "재무 데이터 부족"
        rows.append({**base, "market_cap": enriched.get("market_cap", ""), "market_cap_source": enriched.get("market_cap_source", ""), **metrics, "financial_judgment": judgment, "updated_at": _now(), "status": "OK" if judgment == "계산 가능" else "DATA_MISSING"})
    out = pd.DataFrame(rows, columns=KR_FINANCIAL_COLUMNS)
    out.to_csv(KR_FINANCIAL_METRICS, index=False, encoding="utf-8-sig")
    return {"ok": True, "rows": int(len(out)), "path": str(KR_FINANCIAL_METRICS), "message": f"source={source}"}


def fetch_dart_financial_statement(corp_code: str, api_key: str, *, bsns_year: str | None = None, reprt_code: str = "11011") -> list[dict[str, Any]]:
    if not api_key or not corp_code:
        return []
    year = bsns_year or str(datetime.now().year - 1)
    params = urllib.parse.urlencode(
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": year,
            "reprt_code": reprt_code,
        }
    )
    req = urllib.request.Request("https://opendart.fss.or.kr/api/fnlttSinglAcnt.json?" + params, headers={"User-Agent": "stock-app dart financial cache"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.loads(_decode_http_bytes(resp.read()))
    if str(payload.get("status", "")) not in {"000", "013"}:
        return []
    return list(payload.get("list", []) or [])


def extract_kr_financial_items(items: list[dict[str, Any]]) -> dict[str, str]:
    preferred = [x for x in items if str(x.get("fs_div", "")).upper() == "CFS"] or items
    aliases = {
        "revenue": ["매출액", "수익(매출액)", "영업수익"],
        "operating_income": ["영업이익", "영업손실"],
        "net_income": ["당기순이익", "당기순손익", "당기순손실"],
        "total_assets": ["자산총계"],
        "total_liabilities": ["부채총계"],
        "total_equity": ["자본총계"],
    }
    out = {key: "" for key in aliases}
    for item in preferred:
        account = str(item.get("account_nm", "") or "").strip()
        amount = str(item.get("thstrm_amount", "") or "").strip()
        if not amount:
            continue
        for key, names in aliases.items():
            if not out[key] and any(name == account or name in account for name in names):
                out[key] = amount
    return out


def build_kr_financial_metrics_from_dart(
    *,
    refresh: bool = False,
    max_symbols: int = 8,
    bsns_year: str | None = None,
    reprt_code: str = "11011",
) -> dict[str, Any]:
    ensure_disclosure_files()
    existing = read_csv_safe(KR_FINANCIAL_METRICS, KR_FINANCIAL_COLUMNS)
    if not refresh:
        return {"ok": True, "rows": int(len(existing)), "path": str(KR_FINANCIAL_METRICS), "message": "cache_only"}
    api_key = load_dart_api_key()
    if not api_key:
        return {"ok": True, "rows": int(len(existing)), "path": str(KR_FINANCIAL_METRICS), "message": "DART API 키 없음: 캐시만 사용"}
    symbols = load_kr_symbols(limit=max_symbols)
    if not symbols:
        return {"ok": True, "rows": int(len(existing)), "path": str(KR_FINANCIAL_METRICS), "message": "한국 관심종목 없음"}

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for sym in symbols:
        corp_code, corp_name = dart_corp_code_for_symbol(sym)
        if not corp_code:
            errors.append(f"{sym}:corp_code 없음")
            continue
        try:
            items = fetch_dart_financial_statement(corp_code, api_key, bsns_year=bsns_year, reprt_code=reprt_code)
            base = extract_kr_financial_items(items)
            base.update({"ticker": sym, "market": "한국주식", "corp_name": corp_name, "market_cap": "", "market_cap_source": "", "revenue_growth": ""})
            enriched = calculate_kr_financial_ratios(sym, base)
            metrics = {k: enriched.get(k, "") for k in ["per", "roe", "debt_ratio", "operating_margin", "net_margin"]}
            judgment = "계산 가능" if any(v not in ("", "확인 필요") for v in metrics.values()) else "재무 데이터 부족"
            rows.append(
                {
                    **base,
                    "market_cap": enriched.get("market_cap", ""),
                    "market_cap_source": enriched.get("market_cap_source", ""),
                    **metrics,
                    "financial_judgment": judgment,
                    "updated_at": _now(),
                    "status": "OK" if judgment == "계산 가능" else "DATA_MISSING",
                }
            )
        except Exception as exc:
            errors.append(f"{sym}:{exc.__class__.__name__}")
    if rows:
        out = pd.DataFrame(rows, columns=KR_FINANCIAL_COLUMNS)
        out.to_csv(KR_FINANCIAL_METRICS, index=False, encoding="utf-8-sig")
        existing = out
    msg = f"DART 재무제표 {len(rows)}건 계산"
    if errors:
        msg += "; " + "; ".join(errors[:8])
    return {"ok": True, "rows": int(len(existing)), "path": str(KR_FINANCIAL_METRICS), "message": msg}


def _normalize_kr_ticker(value: Any) -> str:
    text = re.sub(r"[^0-9]", "", str(value or ""))
    return text.zfill(6) if text else ""


def apply_investment_purpose_filter(df: pd.DataFrame, purpose: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    preset = INVESTMENT_PURPOSES.get(purpose, {})
    score = pd.Series(50.0, index=out.index)
    reasons: list[list[str]] = [[] for _ in range(len(out))]

    def add_reason(mask: pd.Series, text: str) -> None:
        for idx in out.index[mask.fillna(False)]:
            reasons[list(out.index).index(idx)].append(text)

    if "confidence_score" in out.columns:
        conf = pd.to_numeric(out["confidence_score"], errors="coerce")
        mask = conf >= 70
        score.loc[mask] += 10
        add_reason(mask, "예측 신뢰도 양호")
    if "no_buy_score" in out.columns:
        nb = pd.to_numeric(out["no_buy_score"], errors="coerce")
        mask = nb >= 70
        score.loc[mask] -= 25
        add_reason(mask, "매수금지 점수 높음")
        mask = nb <= 30
        score.loc[mask] += 8
        add_reason(mask, "매수금지 점수 낮음")
    if "market_risk_score" in out.columns:
        mr = pd.to_numeric(out["market_risk_score"], errors="coerce")
        mask = mr >= 70
        score.loc[mask] -= 12
        add_reason(mask, "시장위험 높음")
    if purpose in {"안정 성장", "실적 개선", "저평가"}:
        for col, label in [("roe", "ROE 양호"), ("revenue_growth", "매출 성장"), ("operating_margin", "영업이익률 양호")]:
            if col in out.columns:
                val = pd.to_numeric(out[col], errors="coerce")
                mask = val > 0
                score.loc[mask] += 8
                add_reason(mask, label)
        if "debt_ratio" in out.columns:
            debt = pd.to_numeric(out["debt_ratio"], errors="coerce")
            mask = debt >= 200
            score.loc[mask] -= 15
            add_reason(mask, "부채비율 주의")
    if purpose == "공시 리스크 회피":
        for col in ["sec_risk_level", "disclosure_risk_level"]:
            if col in out.columns:
                risk = out[col].astype(str)
                mask = risk.isin(["주의", "높음"])
                score.loc[mask] -= 20
                add_reason(mask, "공시 리스크 확인")
    out["purpose"] = purpose
    out["purpose_score"] = score.clip(0, 100).round(1)
    out["purpose_reason"] = [" / ".join(x) if x else str(preset.get("description", "저장 데이터 기준 목적별 점수")) for x in reasons]
    return out.sort_values("purpose_score", ascending=False)


def disclosure_cache_status() -> dict[str, Any]:
    ensure_disclosure_files()
    files = {
        "sec_recent_filings": SEC_RECENT_FILINGS,
        "sec_filing_text_cache": SEC_FILING_TEXT_CACHE,
        "dart_original_text_cache": DART_ORIGINAL_TEXT_CACHE,
        "dart_document_summary_cache": DART_DOCUMENT_SUMMARY_CACHE,
        "kr_financial_metrics": KR_FINANCIAL_METRICS,
    }
    return {
        name: {
            "path": str(path),
            "exists": path.exists(),
            "rows": int(len(read_csv_safe(path))),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if path.exists() else "",
        }
        for name, path in files.items()
    }
