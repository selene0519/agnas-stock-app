
"""Persistent news cache and dedupe helpers for v29.

This module is intentionally dependency-light and network-free. It only cleans,
deduplicates, and stores news items that the app has already collected through
Finnhub, Google News, KIS, RSS, or local reports.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(".")
DATA_DIR = PROJECT_ROOT / "data"
NEWS_DIR = DATA_DIR / "news"
REPORT_DIR = PROJECT_ROOT / "reports"
NEWS_CACHE_CSV = NEWS_DIR / "news_cache.csv"
NEWS_CACHE_JSON = REPORT_DIR / "news_cache_summary.json"

EMPTY = {"", "-", "N/A", "NA", "None", "none", "nan", "NaN"}
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "from", "by", "at",
    "stock", "stocks", "shares", "market", "markets", "update", "news", "today", "says",
    "단독", "속보", "종합", "특징주", "증시", "뉴스", "관련", "상승", "하락",
}

CACHE_COLUMNS = [
    "cache_key", "market", "ticker", "title", "summary", "source", "url", "time", "published_ts",
    "origin", "importance", "direction", "sentiment", "severity", "relevance", "cached_at", "last_seen_at",
    "seen_count",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text in EMPTY else text


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame(columns=CACHE_COLUMNS)
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            df = pd.read_csv(path, dtype=str, encoding=enc).fillna("")
            for col in CACHE_COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            return df[CACHE_COLUMNS]
        except Exception:
            continue
    return pd.DataFrame(columns=CACHE_COLUMNS)


def _write_csv(df: pd.DataFrame, path: Path = NEWS_CACHE_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for col in CACHE_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out[CACHE_COLUMNS].to_csv(path, index=False, encoding="utf-8-sig")


def normalize_news_text(text: Any) -> str:
    raw = _safe_str(text).lower()
    raw = re.sub(r"https?://\S+", " ", raw)
    raw = re.sub(r"[\[\](){}<>|·•…’'\"“”‘`~!@#$%^&*_+=,:;?\\/]+", " ", raw)
    raw = re.sub(r"\s+-\s+[^-]{2,40}$", " ", raw)
    raw = re.sub(r"\b(reuters|bloomberg|cnbc|marketwatch|investing\.com|yahoo finance|google news)\b", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def story_tokens(item: dict[str, Any]) -> list[str]:
    text = normalize_news_text(f"{item.get('title','')} {item.get('summary','')}")
    tokens = []
    for tok in text.split():
        tok = tok.strip()
        if len(tok) < 2 or tok in STOPWORDS:
            continue
        tokens.append(tok)
    return tokens[:16]


def news_cache_key(item: dict[str, Any], market: str = "", ticker: str = "") -> str:
    title = normalize_news_text(item.get("title", ""))
    url = _safe_str(item.get("url", ""))
    origin = _safe_str(item.get("origin", ""))
    tick = _safe_str(ticker or item.get("related_ticker", "") or item.get("ticker", "")).upper()
    # URL이 있으면 URL+제목 일부, URL이 없으면 핵심 토큰을 사용한다.
    core = url or " ".join(story_tokens(item)[:10]) or title[:120]
    raw = f"{market}|{tick}|{origin}|{core}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _item_to_row(item: dict[str, Any], market: str = "", ticker: str = "") -> dict[str, Any]:
    tick = _safe_str(ticker or item.get("related_ticker", "") or item.get("ticker", "")).upper()
    now = _now()
    row = {
        "cache_key": news_cache_key(item, market, tick),
        "market": _safe_str(market or item.get("market", "")),
        "ticker": tick,
        "title": _safe_str(item.get("title", "")),
        "summary": _safe_str(item.get("summary", "")),
        "source": _safe_str(item.get("source", "")),
        "url": _safe_str(item.get("url", "")),
        "time": _safe_str(item.get("time", "")),
        "published_ts": _safe_str(item.get("published_ts", "") or item.get("published_raw", "")),
        "origin": _safe_str(item.get("origin", "")),
        "importance": _safe_str(item.get("importance", "")),
        "direction": _safe_str(item.get("direction", "")),
        "sentiment": _safe_str(item.get("sentiment", "")),
        "severity": _safe_str(item.get("severity", "")),
        "relevance": _safe_str(item.get("relevance", "")),
        "cached_at": now,
        "last_seen_at": now,
        "seen_count": "1",
    }
    return row


def _row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    item = {k: _safe_str(row.get(k, "")) for k in CACHE_COLUMNS if k not in {"cache_key", "seen_count", "cached_at", "last_seen_at"}}
    if item.get("ticker"):
        item["related_ticker"] = item["ticker"]
    return item


def _parse_time(value: Any) -> pd.Timestamp:
    text = _safe_str(value)
    if not text:
        return pd.Timestamp.min
    try:
        ts = pd.to_datetime(text, errors="coerce", utc=True)
        if pd.notna(ts):
            return ts.tz_convert(None) if getattr(ts, "tzinfo", None) is not None else ts
    except Exception:
        pass
    return pd.Timestamp.min


def dedupe_news_items(items: list[dict[str, Any]] | None, market: str = "", ticker: str = "", max_items: int = 20) -> list[dict[str, Any]]:
    if not items:
        return []
    best: dict[str, dict[str, Any]] = {}
    token_seen: list[tuple[set[str], str]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        title = _safe_str(raw.get("title", ""))
        if not title:
            continue
        item = dict(raw)
        key = news_cache_key(item, market, ticker)
        tokens = set(story_tokens(item)[:12])
        fuzzy_hit = ""
        if len(tokens) >= 4:
            for old_tokens, old_key in token_seen:
                inter = len(tokens & old_tokens)
                union = max(1, len(tokens | old_tokens))
                if inter / union >= 0.72 or inter >= min(len(tokens), len(old_tokens), 7):
                    fuzzy_hit = old_key
                    break
        use_key = fuzzy_hit or key
        if use_key not in best:
            best[use_key] = item
            if tokens:
                token_seen.append((tokens, use_key))
            continue
        old = best[use_key]
        old_score = float(pd.to_numeric(pd.Series([old.get("relevance", old.get("severity", 0))]), errors="coerce").fillna(0).iloc[0])
        new_score = float(pd.to_numeric(pd.Series([item.get("relevance", item.get("severity", 0))]), errors="coerce").fillna(0).iloc[0])
        old_time = _parse_time(old.get("published_ts") or old.get("published_raw") or old.get("time"))
        new_time = _parse_time(item.get("published_ts") or item.get("published_raw") or item.get("time"))
        if (new_score, new_time) > (old_score, old_time):
            item["duplicate_sources"] = list(old.get("duplicate_sources", [])) + [{"title": old.get("title", ""), "source": old.get("source", ""), "url": old.get("url", "")}]
            best[use_key] = item
        else:
            dup = old.setdefault("duplicate_sources", [])
            dup.append({"title": item.get("title", ""), "source": item.get("source", ""), "url": item.get("url", "")})
    out = list(best.values())
    out.sort(
        key=lambda x: (
            float(pd.to_numeric(pd.Series([x.get("relevance", x.get("severity", 0))]), errors="coerce").fillna(0).iloc[0]),
            _parse_time(x.get("published_ts") or x.get("published_raw") or x.get("time")),
        ),
        reverse=True,
    )
    return out[: max(1, int(max_items))]


def update_news_cache(items: list[dict[str, Any]] | None, market: str = "", ticker: str = "", source: str = "app", max_cache_days: int = 21) -> dict[str, Any]:
    cleaned = dedupe_news_items(items or [], market=market, ticker=ticker, max_items=80)
    existing = _read_csv(NEWS_CACHE_CSV)
    rows = [_item_to_row(x, market=market, ticker=ticker) for x in cleaned]
    incoming = pd.DataFrame(rows, columns=CACHE_COLUMNS)
    if incoming.empty:
        summary = {
            "status": "NO_ITEMS", "updated_at": _now(), "source": source,
            "incoming": 0, "cache_rows": int(len(existing)), "path": str(NEWS_CACHE_CSV),
        }
        NEWS_CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
        NEWS_CACHE_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
    if existing.empty:
        merged = incoming
    else:
        old = existing.set_index("cache_key", drop=False)
        for _, row in incoming.iterrows():
            key = row["cache_key"]
            if key in old.index:
                prev = old.loc[key].to_dict()
                try:
                    count = int(float(prev.get("seen_count", 1))) + 1
                except Exception:
                    count = 2
                prev.update({k: row.get(k, prev.get(k, "")) for k in ["market", "ticker", "title", "summary", "source", "url", "time", "published_ts", "origin", "importance", "direction", "sentiment", "severity", "relevance"] if _safe_str(row.get(k, ""))})
                prev["last_seen_at"] = _now()
                prev["seen_count"] = str(count)
                old.loc[key] = pd.Series(prev)
            else:
                old.loc[key] = row
        merged = old.reset_index(drop=True)
    try:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=max_cache_days)
        seen = pd.to_datetime(merged["last_seen_at"], errors="coerce")
        merged = merged[(seen.isna()) | (seen >= cutoff)].copy()
    except Exception:
        pass
    merged = merged.drop_duplicates("cache_key", keep="last")
    _write_csv(merged, NEWS_CACHE_CSV)
    summary = {
        "status": "OK", "updated_at": _now(), "source": source,
        "incoming": int(len(items or [])), "unique_incoming": int(len(cleaned)),
        "dedup_removed": int(max(0, len(items or []) - len(cleaned))),
        "cache_rows": int(len(merged)), "path": str(NEWS_CACHE_CSV),
    }
    NEWS_CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
    NEWS_CACHE_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def load_cached_news(market: str = "", ticker: str = "", max_age_hours: int = 96, max_items: int = 20) -> list[dict[str, Any]]:
    df = _read_csv(NEWS_CACHE_CSV)
    if df.empty:
        return []
    view = df.copy()
    if market:
        view = view[view["market"].astype(str).eq(str(market)) | view["market"].astype(str).eq("")]
    if ticker:
        tick = str(ticker).upper().strip()
        view = view[view["ticker"].astype(str).str.upper().isin([tick, ""])]
    try:
        cutoff = pd.Timestamp.now() - pd.Timedelta(hours=max_age_hours)
        ts = pd.to_datetime(view["last_seen_at"], errors="coerce")
        view = view[(ts.isna()) | (ts >= cutoff)].copy()
    except Exception:
        pass
    if view.empty:
        return []
    view["_score"] = pd.to_numeric(view["relevance"], errors="coerce").fillna(pd.to_numeric(view["severity"], errors="coerce")).fillna(0)
    view["_time"] = pd.to_datetime(view["published_ts"], errors="coerce")
    view = view.sort_values(["_score", "_time", "last_seen_at"], ascending=[False, False, False]).head(max_items)
    return [_row_to_item(r) for r in view.drop(columns=[c for c in ["_score", "_time"] if c in view.columns]).to_dict(orient="records")]


def summarize_news_cache() -> dict[str, Any]:
    df = _read_csv(NEWS_CACHE_CSV)
    if df.empty:
        return {"status": "NO_CACHE", "cache_rows": 0, "updated_at": _now(), "path": str(NEWS_CACHE_CSV)}
    by_market = df.groupby("market").size().to_dict() if "market" in df.columns else {}
    by_ticker = df[df["ticker"].astype(str) != ""].groupby("ticker").size().sort_values(ascending=False).head(20).to_dict() if "ticker" in df.columns else {}
    summary = {
        "status": "OK", "updated_at": _now(), "cache_rows": int(len(df)), "path": str(NEWS_CACHE_CSV),
        "by_market": {str(k): int(v) for k, v in by_market.items()},
        "top_tickers": {str(k): int(v) for k, v in by_ticker.items()},
    }
    NEWS_CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
    NEWS_CACHE_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
