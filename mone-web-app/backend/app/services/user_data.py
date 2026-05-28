from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.services import data_loader as data

BACKUP_DIR = data.APP_DIR / "backend" / "backups"


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
    return data.REPO_ROOT / f"watchlist_{market}_growth.csv"


def _holdings_path(market: str) -> Path:
    return data.DATA_DIR / f"holdings_{market}.csv"


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
    return {"status": "OK", "message": "관심종목에서 삭제했습니다.", "market": market, "symbol": target, "backupFile": backup, "count": len(next_df)}


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
    memo = data._safe_str(payload.get("memo"), "수동 저장")
    row = {col: "" for col in df.columns}
    _set_first_existing(row, ["symbol", "ticker", "code", "종목코드"], symbol, "symbol")
    _set_first_existing(row, ["name", "종목명", "stock_name", "종목"], name, "name")
    _set_first_existing(row, ["market", "시장"], "미국주식" if market == "us" else "한국주식", "market")
    _set_first_existing(row, ["avg_price", "평균단가", "평단가"], avg_price, "avg_price")
    _set_first_existing(row, ["quantity", "shares", "보유수량"], quantity, "quantity")
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
    df = data.read_csv(path)
    df = _ensure_columns(df, ["symbol", "name", "market", "avg_price", "quantity", "memo", "updated_at"])
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
    return {"status": "OK", "action": action, "message": "보유종목을 저장했습니다.", "market": market, "symbol": symbol, "backupFile": backup, "count": len(df)}


def delete_holding(symbol: str, market: str) -> dict[str, Any]:
    market = "us" if market == "us" else "kr"
    target = data.normalize_symbol(symbol, market)
    path = _holdings_path(market)
    df = data.read_csv(path)
    if df.empty:
        return {"status": "MISSING", "message": "보유종목 파일이 없습니다.", "market": market, "symbol": target}
    mask = df.apply(lambda row: _row_symbol(row, market) == target, axis=1)
    if not bool(mask.any()):
        return {"status": "NOT_FOUND", "message": "보유종목에서 찾지 못했습니다.", "market": market, "symbol": target, "count": len(df)}
    next_df = df.loc[~mask].copy()
    backup = _write_csv_safe(path, next_df)
    return {"status": "OK", "message": "보유종목에서 삭제했습니다.", "market": market, "symbol": target, "backupFile": backup, "count": len(next_df)}
