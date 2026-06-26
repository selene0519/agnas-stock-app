from __future__ import annotations

import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.services import data_loader as data
from app.services import supabase_db as sdb

BACKUP_DIR = data.APP_DIR / "backend" / "backups"

_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def file_lock(path: Path) -> threading.Lock:
    """동일 CSV 경로에 대한 읽기~쓰기 구간을 직렬화하는 락.
    여러 진입점(보유종목 수동수정, KIS 동기화 등)이 같은 파일을 read-modify-write
    하면서 서로의 변경을 덮어쓰는 lost-update를 막기 위함 — 경로 기준으로 공유해야
    호출 위치가 달라도 같은 락을 잡는다."""
    key = str(path.resolve())
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[key] = lock
        return lock


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")


def _backup_file(path: Path) -> str:
    if not path.exists():
        return ""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / stamp / path.relative_to(data.REPO_ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return dest.relative_to(data.APP_DIR).as_posix()


def _write_csv_safe(path: Path, df: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = _backup_file(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.fillna("").to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)
    return backup


def _watchlist_path(market: str) -> Path:
    return data.REPO_ROOT / f"watchlist_{market}.csv"


def _watchlist_growth_path(market: str) -> Path:
    return data.REPO_ROOT / f"watchlist_{market}_growth.csv"


def _holdings_path(market: str) -> Path:
    return data.REPO_ROOT / f"holdings_{market}.csv"


SOLD_POSITIONS_COLUMNS = [
    "recordedAt", "market", "symbol", "name", "quantity", "avgPrice",
    "exitPrice", "exitPriceSource", "realizedPnl", "realizedReturnPct",
]


def _sold_positions_path() -> Path:
    return data.REPO_ROOT / "data" / "sold_positions_history.csv"


def _latest_ohlcv_close(symbol: str, market: str) -> float | None:
    mk = "us" if market == "us" else "kr"
    path = data.REPO_ROOT / "data" / "market" / "ohlcv" / f"{mk}_{symbol}_daily.csv"
    df = data.read_csv(path)
    if df.empty or "close" not in df.columns or "date" not in df.columns:
        return None
    try:
        return data._safe_float(df.sort_values("date").iloc[-1]["close"])
    except Exception:
        return None


def record_sold_positions(removed: list[dict[str, Any]]) -> None:
    """보유종목에서 사라진 종목을 영구 기록한다 (생존편향 방지).
    상장폐지·매도로 holdings.csv에서 빠진 종목의 손익이 지금까지는 어디에도
    남지 않아 포트폴리오 수익률이 살아남은 종목만으로 낙관적으로 계산됐다.
    exitPrice는 최신 OHLCV 종가를 우선 쓰고, 없으면 avgPrice로 대체한다는
    출처(exitPriceSource)를 같이 남겨 수치의 신뢰도를 숨기지 않는다."""
    if not removed:
        return
    path = _sold_positions_path()
    with file_lock(path):
        existing = data.read_csv(path)
        rows = existing.to_dict(orient="records") if not existing.empty else []
        for item in removed:
            symbol = data._safe_str(item.get("symbol"))
            if not symbol:
                continue
            market = "us" if str(item.get("market", "kr")).lower() == "us" else "kr"
            quantity = data._safe_float(item.get("quantity")) or 0.0
            avg_price = data._safe_float(item.get("avgPrice") or item.get("avg_price")) or 0.0
            exit_price = _latest_ohlcv_close(symbol, market)
            exit_source = "ohlcv_latest_close"
            if not exit_price or exit_price <= 0:
                exit_price = avg_price
                exit_source = "avg_price_fallback_no_exit_data"
            realized_pnl = (exit_price - avg_price) * quantity if avg_price > 0 else 0.0
            realized_return_pct = ((exit_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            rows.append({
                "recordedAt": _now(),
                "market": market,
                "symbol": symbol,
                "name": data._safe_str(item.get("name"), symbol),
                "quantity": quantity,
                "avgPrice": avg_price,
                "exitPrice": exit_price,
                "exitPriceSource": exit_source,
                "realizedPnl": round(realized_pnl, 2),
                "realizedReturnPct": round(realized_return_pct, 2),
            })
        df = pd.DataFrame(rows, columns=SOLD_POSITIONS_COLUMNS)
        _write_csv_safe(path, df)


def get_sold_positions(market: str = "all") -> dict[str, Any]:
    df = data.read_csv(_sold_positions_path())
    if not df.empty and market in ("kr", "us"):
        df = df[df["market"] == market]
    items = df.to_dict(orient="records") if not df.empty else []
    total_realized_pnl = sum(data._safe_float(r.get("realizedPnl")) or 0.0 for r in items)
    return {
        "status": "OK",
        "market": market,
        "count": len(items),
        "items": items,
        "totalRealizedPnl": round(total_realized_pnl, 2),
        "note": "여기 기록은 이 기능을 추가한 시점 이후의 매도만 포함합니다. 그 이전에 매도/상장폐지된 종목의 손익은 소급 반영되지 않습니다.",
    }


def _row_symbol(row: dict[str, Any] | pd.Series, market: str) -> str:
    return data.normalize_symbol(data.first_value(row, data.SYMBOL_ALIASES), market)


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    work = df.copy()
    if work.empty and not len(work.columns):
        work = pd.DataFrame(columns=columns)
    for col in columns:
        if col not in work.columns:
            work[col] = ""
    return work


def _set_first_existing(row: dict[str, Any], columns: list[str], value: Any, default_col: str) -> None:
    found = False
    for col in columns:
        if col in row:
            row[col] = value
            found = True
    if not found:
        row[default_col] = value


def _normalized_direct_rows(df: pd.DataFrame, market: str) -> list[dict[str, Any]]:
    rows = []
    for row in data.dataframe_records(df):
        row = data.apply_quote_cache(row, market)
        normalized = data.normalize_security_row(row, market)
        quantity = data.first_number(row, ["quantity", "보유수량", "shares"])
        avg_price = data.first_number(row, ["avg_price", "평균단가", "평단가"])
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
            "avgPriceText": data.format_price(avg_price, market) if avg_price is not None else "평균단가 없음",
            "marketValue": market_value,
            "marketValueText": data.format_price(market_value, market) if market_value is not None else "평가금액 없음",
            "costBasis": cost_basis,
            "costBasisText": data.format_price(cost_basis, market) if cost_basis is not None else "매입금액 없음",
            "returnPct": return_pct_value,
            "returnPctText": data.format_percent(return_pct_value),
            "pnl": pnl_value,
            "pnlText": data.format_signed_money(pnl_value, market),
            "nextAction": data.first_value(row, ["다음행동", "조치", "memo", "메모"], "다음 행동 없음"),
        })
        rows.append(normalized)
    return rows


def get_watchlist(market: str) -> dict[str, Any]:
    path = _watchlist_path(market)
    df = data.read_csv(path)
    items = [data.normalize_security_row(data.apply_quote_cache(row, market), market) for row in data.dataframe_records(df)]
    return {
        "market": market,
        "source": path.relative_to(data.REPO_ROOT).as_posix(),
        "count": len(items),
        "items": items,
        "updatedAt": data.file_mtime(path) if path.exists() else "",
    }


def add_watchlist(payload: dict[str, Any]) -> dict[str, Any]:
    market = "us" if str(payload.get("market", "kr")).lower() == "us" else "kr"
    symbol = data.normalize_symbol(payload.get("symbol"), market)
    if not symbol:
        return {"status": "ERROR", "message": "종목코드/티커가 필요합니다.", "market": market}
    name = data._safe_str(payload.get("name"), symbol)
    memo = data._safe_str(payload.get("memo"), "수동 추가")
    path = _watchlist_path(market)
    df = data.read_csv(path)
    df = _ensure_columns(df, ["symbol", "ticker", "name", "market", "memo", "updated_at"])
    existing_symbols = {_row_symbol(row, market) for row in data.dataframe_records(df)}
    if symbol in existing_symbols:
        return {"status": "DUPLICATE", "message": "이미 관심종목입니다.", "market": market, "symbol": symbol, "count": len(df)}

    row = {col: "" for col in df.columns}
    _set_first_existing(row, ["symbol", "ticker", "code", "종목코드"], symbol, "symbol")
    _set_first_existing(row, ["name", "종목명", "stock_name", "종목"], name, "name")
    _set_first_existing(row, ["market", "시장"], "us" if market == "us" else "kr", "market")
    _set_first_existing(row, ["memo", "메모", "why_watch", "watch_trigger"], memo, "memo")
    row["updated_at"] = _now() if "updated_at" in row else _now()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    backup = _write_csv_safe(path, df)
    sdb.upsert_watch(market, symbol, {"name": name, "memo": memo})
    return {"status": "OK", "message": "관심종목에 추가했습니다.", "market": market, "symbol": symbol, "backupFile": backup, "count": len(df)}


def delete_watchlist(symbol: str, market: str) -> dict[str, Any]:
    market = "us" if market == "us" else "kr"
    target = data.normalize_symbol(symbol, market)
    path = _watchlist_path(market)
    df = data.read_csv(path)
    if df.empty:
        return {"status": "MISSING", "message": "관심종목 파일이 없습니다.", "market": market, "symbol": target}
    mask = df.apply(lambda row: _row_symbol(row, market) == target, axis=1)
    if not bool(mask.any()):
        return {"status": "NOT_FOUND", "message": "관심종목에서 찾지 못했습니다.", "market": market, "symbol": target, "count": len(df)}
    next_df = df.loc[~mask].copy()
    backup = _write_csv_safe(path, next_df)
    sdb.delete_watch(market, target)
    return {"status": "OK", "message": "관심종목에서 삭제했습니다.", "market": market, "symbol": target, "backupFile": backup, "count": len(next_df)}


def _auto_watch_reason(item: dict[str, Any]) -> tuple[str, float]:
    tags = {str(tag).upper() for tag in item.get("strategyTags") or []}
    texts = " ".join(
        str(item.get(key) or "")
        for key in (
            "candidateType",
            "candidateTypeLabel",
            "timingLabel",
            "timingReason",
            "surgeLabel",
            "finReason",
            "pullbackState",
            "pullbackReason",
        )
    )
    text_upper = texts.upper()
    score = 0.0
    reasons: list[str] = []

    if "PULLBACK_BUY" in tags or "PULLBACK" in text_upper or "눌림" in texts:
        score += 34.0
        reasons.append("눌림목")
    if "UNDERVALUED_GROWTH" in tags or "GROWTH" in text_upper or "성장" in texts:
        score += 28.0
        reasons.append("성장")
    if "LEADER" in text_upper or item.get("isLeader") is True:
        score += 18.0
        reasons.append("주도주")
    if "MOMENTUM" in tags or "모멘텀" in texts:
        score += 12.0
        reasons.append("모멘텀")
    if str(item.get("supplySignal") or "").upper() in {"STRONG_BUY", "INST_BUY"}:
        score += 10.0
        reasons.append("수급")

    final_score = data.first_number(item, ["finalScore", "finalRankScore", "probability"]) or 0.0
    expected_value = data.first_number(item, ["expectedValue"]) or 0.0
    risk_score = data.first_number(item, ["riskScore"]) or 0.0
    entry_score = data.first_number(item, ["entryScore"]) or 0.0
    score += final_score * 0.28 + max(-10.0, min(15.0, expected_value)) * 1.2 + risk_score * 0.08 + entry_score * 0.08

    if item.get("evNegative") is True or expected_value < 0:
        score -= 25.0
    if str(item.get("tradeBlockStatus") or "").upper() in {"CAUTION", "BLOCK"}:
        score -= 10.0
    if str(item.get("decisionBucket") or "") in {"보류", "제외"}:
        score -= 18.0

    if not reasons:
        reasons.append("고득점")
    return " · ".join(dict.fromkeys(reasons)), round(score, 2)


def auto_watchlist_candidates(market: str = "all", limit_per_market: int = 12) -> dict[str, Any]:
    markets = ["kr", "us"] if str(market).lower() == "all" else ["us" if str(market).lower() == "us" else "kr"]
    modes = ["conservative", "balanced", "aggressive"]
    horizons = ["short", "swing", "mid"]
    limit_per_market = max(3, min(int(limit_per_market or 12), 30))
    all_items: list[dict[str, Any]] = []
    sources: list[str] = []

    for mk in markets:
        keyed: dict[str, dict[str, Any]] = {}
        for mode in modes:
            for horizon in horizons:
                path = data.REPORT_DIR / f"mone_v36_final_recommendations_{mk}_{mode}_{horizon}.csv"
                rows = data.dataframe_records(data.read_csv(path))
                if rows and path.name not in sources:
                    sources.append(path.name)
                for item in rows:
                    symbol = data.normalize_symbol(item.get("symbol"), mk)
                    if not symbol:
                        continue
                    reason, auto_score = _auto_watch_reason(item)
                    if auto_score < 35:
                        continue
                    row = {
                        "market": mk,
                        "symbol": symbol,
                        "name": data.first_value(item, data.NAME_ALIASES, symbol),
                        "targetReason": reason,
                        "memo": f"자동선별 · {reason}",
                        "autoWatchCategory": reason,
                        "autoWatchScore": auto_score,
                        "finalScore": data.first_number(item, ["finalScore", "finalRankScore", "probability"]),
                        "expectedValue": data.first_number(item, ["expectedValue"]),
                        "mode": mode,
                        "horizon": horizon,
                        "decisionBucket": item.get("decisionBucket", ""),
                        "timingLabel": item.get("timingLabel", ""),
                        "candidateTypeLabel": item.get("candidateTypeLabel", ""),
                        "updated_at": _now(),
                    }
                    key = f"{mk}-{symbol}"
                    if key not in keyed or auto_score > float(keyed[key].get("autoWatchScore") or 0):
                        keyed[key] = row
        all_items.extend(sorted(keyed.values(), key=lambda row: float(row.get("autoWatchScore") or 0), reverse=True)[:limit_per_market])

    return {
        "status": "OK",
        "market": market,
        "limitPerMarket": limit_per_market,
        "count": len(all_items),
        "sources": sources[:12],
        "items": all_items,
        "updatedAt": _now(),
        "policy": "추천 3x3 조합에서 눌림목·성장·주도주·모멘텀·수급 후보를 점수화해 시장별 상위 종목만 선별",
    }


def apply_auto_watchlist(market: str = "all", limit_per_market: int = 12) -> dict[str, Any]:
    payload = auto_watchlist_candidates(market, limit_per_market)
    items = payload.get("items") or []
    backup_files: list[str] = []
    for mk in (["kr", "us"] if str(market).lower() == "all" else ["us" if str(market).lower() == "us" else "kr"]):
        market_rows = [row for row in items if row.get("market") == mk]
        if not market_rows:
            continue
        columns = ["market", "symbol", "name", "memo", "targetReason", "autoWatchCategory", "autoWatchScore", "finalScore", "expectedValue", "mode", "horizon", "decisionBucket", "timingLabel", "candidateTypeLabel", "updated_at"]
        df = pd.DataFrame(market_rows, columns=columns)
        for path in (_watchlist_path(mk), _watchlist_growth_path(mk)):
            backup = _write_csv_safe(path, df)
            if backup:
                backup_files.append(backup)
    return {**payload, "status": "OK", "backupFiles": backup_files, "message": "핵심 관심종목을 자동 선별 목록으로 교체했습니다."}


def get_holdings(market: str) -> dict[str, Any]:
    market = "us" if market == "us" else "kr"
    path = _holdings_path(market)
    df = data.read_csv(path)
    items = _normalized_direct_rows(df, market)
    return {
        "market": market,
        "source": path.relative_to(data.REPO_ROOT).as_posix(),
        "count": len(items),
        "items": items,
        "updatedAt": data.file_mtime(path) if path.exists() else "",
    }


def _prepare_holding_row(df: pd.DataFrame, payload: dict[str, Any], market: str) -> dict[str, Any]:
    symbol = data.normalize_symbol(payload.get("symbol") or payload.get("ticker") or payload.get("code"), market)
    name = data._safe_str(payload.get("name"), symbol)
    avg_price = data._safe_str(payload.get("avgPrice") or payload.get("avg_price") or payload.get("평균단가"), "")
    quantity = data._safe_str(payload.get("quantity") or payload.get("shares") or payload.get("보유수량"), "")
    stop_price = data._safe_str(payload.get("stopPrice") or payload.get("stop_price") or payload.get("손절가"), "")
    target_price = data._safe_str(payload.get("targetPrice") or payload.get("target_price") or payload.get("목표가"), "")
    memo = data._safe_str(payload.get("memo"), "수동 저장")
    row = {col: "" for col in df.columns}
    _set_first_existing(row, ["symbol", "ticker", "code", "종목코드"], symbol, "symbol")
    _set_first_existing(row, ["name", "종목명", "stock_name", "종목"], name, "name")
    _set_first_existing(row, ["market", "시장"], "미국주식" if market == "us" else "한국주식", "market")
    _set_first_existing(row, ["avgPrice", "avg_price", "평균단가", "평단가"], avg_price, "avg_price")
    _set_first_existing(row, ["quantity", "shares", "보유수량"], quantity, "quantity")
    _set_first_existing(row, ["stopPrice", "stop_price", "손절가"], stop_price, "stopPrice")
    _set_first_existing(row, ["targetPrice", "target_price", "목표가"], target_price, "targetPrice")
    _set_first_existing(row, ["memo", "메모"], memo, "memo")
    if "holding_type" in row and not row.get("holding_type"):
        row["holding_type"] = "core"
    if "updated_at" in row:
        row["updated_at"] = _now()
    return row


def upsert_holding(payload: dict[str, Any], mode: str = "post", symbol_arg: str | None = None) -> dict[str, Any]:
    market = "us" if str(payload.get("market", "kr")).lower() == "us" else "kr"
    symbol = data.normalize_symbol(symbol_arg or payload.get("symbol") or payload.get("ticker") or payload.get("code"), market)
    if not symbol:
        return {"status": "ERROR", "message": "종목코드/티커가 필요합니다.", "market": market}
    path = _holdings_path(market)
    with file_lock(path):
        df = data.read_csv(path)
        df = _ensure_columns(df, ["symbol", "name", "market", "quantity", "avgPrice", "stopPrice", "targetPrice"])
        mask = df.apply(lambda row: _row_symbol(row, market) == symbol, axis=1) if not df.empty else pd.Series([], dtype=bool)
        row = _prepare_holding_row(df, {**payload, "symbol": symbol}, market)
        action = "updated" if bool(mask.any()) else "created"
        if bool(mask.any()):
            idx = mask[mask].index[0]
            for col, value in row.items():
                if data._safe_str(value, ""):
                    df.at[idx, col] = value
        else:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        backup = _write_csv_safe(path, df)
    sdb.upsert_holding(market, symbol, payload)
    return {"status": "OK", "action": action, "message": "보유종목을 저장했습니다.", "market": market, "symbol": symbol, "backupFile": backup, "count": len(df)}


def delete_holding(symbol: str, market: str) -> dict[str, Any]:
    market = "us" if market == "us" else "kr"
    target = data.normalize_symbol(symbol, market)
    path = _holdings_path(market)
    with file_lock(path):
        df = data.read_csv(path)
        if df.empty:
            return {"status": "MISSING", "message": "보유종목 파일이 없습니다.", "market": market, "symbol": target}
        mask = df.apply(lambda row: _row_symbol(row, market) == target, axis=1)
        if not bool(mask.any()):
            return {"status": "NOT_FOUND", "message": "보유종목에서 찾지 못했습니다.", "market": market, "symbol": target, "count": len(df)}
        next_df = df.loc[~mask].copy()
        backup = _write_csv_safe(path, next_df)
    sdb.delete_holding(market, target)
    return {"status": "OK", "message": "보유종목에서 삭제했습니다.", "market": market, "symbol": target, "backupFile": backup, "count": len(next_df)}
