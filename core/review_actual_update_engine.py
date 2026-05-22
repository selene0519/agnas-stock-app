from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd


PREDICTIONS_FILE = Path("predictions.csv")
ACTUAL_OHLC_COLUMNS = ["actual_open", "actual_high", "actual_low", "actual_close"]
ACTUAL_REQUIRED_COLUMNS = [
    "actual_open",
    "actual_high",
    "actual_low",
    "actual_close",
    "actual_volume",
    "actual_update_status",
    "actual_update_reason",
    "actual_updated_at",
]
ACTUAL_METADATA_COLUMNS = ["actual_date", "actual_volume", "actual_source"]
NULL_TEXT = {"", "nan", "none", "null", "nat", "n/a", "na", "-"}
KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")


@dataclass
class ActualUpdateStats:
    scanned: int = 0
    eligible: int = 0
    skipped_existing: int = 0
    flat_suspect_rows: int = 0
    cleared_flat_rows: int = 0
    updated_rows: int = 0
    filled_cells: int = 0
    fetch_failed: int = 0
    invalid_rows: int = 0
    future_rows: int = 0
    pending_not_ready_rows: int = 0
    output_rows: int = 0


FetchActualFn = Callable[[Any, Any, Any], dict[str, Any] | None]


def is_missing(value: Any) -> bool:
    try:
        if value is None or pd.isna(value):
            return True
    except Exception:
        if value is None:
            return True
    return str(value).strip().lower() in NULL_TEXT


def safe_float(value: Any, default: float = math.nan) -> float:
    if is_missing(value):
        return default
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").replace("$", "").strip()
        return float(value)
    except Exception:
        return default


def read_predictions(path: Path = PREDICTIONS_FILE) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def backup_predictions_file(path: Path = PREDICTIONS_FILE) -> Path | None:
    if not path.exists():
        return None
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = backup_dir / f"{path.stem}_before_review_actual_update_{stamp}{path.suffix}"
    shutil.copy2(path, out)
    return out


def flatten_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[0]).strip() for c in out.columns]
    else:
        out.columns = [str(c).strip() for c in out.columns]
    return out


def is_kr_market(market: Any, ticker: Any = "") -> bool:
    text = str(market or "").strip().lower()
    kr_tokens = ["\ud55c\uad6d", "\uad6d\ub0b4", "kr", "kor", "korea", "kospi", "kosdaq"]
    us_tokens = ["\ubbf8\uad6d", "us", "usa", "nasdaq", "nyse", "amex"]
    if any(token in text for token in kr_tokens):
        return True
    if any(token in text for token in us_tokens):
        return False
    raw_ticker = str(ticker or "").strip().upper()
    compact = raw_ticker.replace(".KS", "").replace(".KQ", "")
    return compact.isdigit()


def normalize_ticker(ticker: Any, market: Any = "") -> str:
    raw = str(ticker or "").strip().upper()
    if not raw:
        return ""
    if is_kr_market(market, raw):
        raw = raw.replace("KRX:", "").replace("KOSPI:", "").replace("KOSDAQ:", "").strip()
        if raw.endswith(".KS") or raw.endswith(".KQ"):
            return raw
        if raw.isdigit():
            return raw.zfill(6)
    return raw


def market_actual_ready(market: Any, target: date, now: datetime | None = None) -> bool:
    """Return True only after the target market's daily OHLC should be complete."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)

    if is_kr_market(market):
        now_kst = now.astimezone(KST)
        if target < now_kst.date():
            return True
        if target > now_kst.date():
            return False
        return (now_kst.hour, now_kst.minute) >= (16, 30)

    now_et = now.astimezone(ET)
    if target < now_et.date():
        return True
    if target > now_et.date():
        return False
    return (now_et.hour, now_et.minute) >= (17, 30)


def coerce_ohlc_frame(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = flatten_price_columns(raw.reset_index() if "Date" not in raw.columns else raw)
    if "Date" not in df.columns and len(df.columns) > 0:
        df = df.rename(columns={df.columns[0]: "Date"})
    required = ["Date", "Open", "High", "Low", "Close"]
    if any(c not in df.columns for c in required):
        return pd.DataFrame()
    keep = required + (["Volume"] if "Volume" in df.columns else [])
    df = df[keep].copy()
    dates = pd.to_datetime(df["Date"], errors="coerce")
    try:
        if getattr(dates.dt, "tz", None) is not None:
            dates = dates.dt.tz_localize(None)
    except Exception:
        pass
    df["Date"] = dates.dt.date
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Date", "Open", "High", "Low", "Close"])
    return df.sort_values("Date").reset_index(drop=True)


def select_actual_row(df: pd.DataFrame, target: date) -> pd.Series | None:
    """Pick the target-date daily bar, falling back to the next trading day after holidays."""
    if df is None or df.empty or "Date" not in df.columns:
        return None
    exact = df[df["Date"] == target].sort_values("Date")
    if not exact.empty:
        return exact.iloc[0]
    after = df[df["Date"] > target].sort_values("Date")
    if not after.empty:
        return after.iloc[0]
    return None


def fetch_kr_with_fdr(ticker: str, start: date, end: date) -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr
    except Exception:
        return pd.DataFrame()
    try:
        symbol = ticker.replace(".KS", "").replace(".KQ", "")
        return coerce_ohlc_frame(fdr.DataReader(symbol, start, end))
    except Exception:
        return pd.DataFrame()


def fetch_with_yfinance(symbols: list[str], start: date, end: date) -> tuple[pd.DataFrame, str]:
    try:
        import yfinance as yf
    except Exception:
        return pd.DataFrame(), ""
    for symbol in symbols:
        try:
            raw = yf.download(
                symbol,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1d",
                progress=False,
                auto_adjust=False,
            )
            df = coerce_ohlc_frame(raw)
            if not df.empty:
                return df, f"yfinance:{symbol}"
        except Exception:
            continue
    return pd.DataFrame(), ""


def fetch_actual_ohlc(ticker: Any, market: Any, target_date: Any) -> dict[str, Any] | None:
    """Return OHLC for the first trading day on or after target_date."""
    target_ts = pd.to_datetime(target_date, errors="coerce")
    if pd.isna(target_ts):
        return None
    target = target_ts.date()
    symbol = normalize_ticker(ticker, market)
    if not symbol:
        return None

    start = target - timedelta(days=1)
    end = target + timedelta(days=14)
    is_kr = is_kr_market(market, symbol)

    if is_kr:
        df = fetch_kr_with_fdr(symbol, start, end)
        source = "FinanceDataReader"
        if df.empty:
            base = symbol.replace(".KS", "").replace(".KQ", "")
            symbols = [symbol] if symbol.endswith((".KS", ".KQ")) else [f"{base}.KS", f"{base}.KQ"]
            df, source = fetch_with_yfinance(symbols, start, end)
    else:
        df, source = fetch_with_yfinance([symbol], start, end)

    if df.empty:
        return None
    row = select_actual_row(df, target)
    if row is None:
        return None
    return {
        "actual_date": str(row["Date"]),
        "actual_open": safe_float(row.get("Open")),
        "actual_high": safe_float(row.get("High")),
        "actual_low": safe_float(row.get("Low")),
        "actual_close": safe_float(row.get("Close")),
        "actual_volume": safe_float(row.get("Volume"), 0.0),
        "actual_source": source or ("FinanceDataReader" if is_kr else "yfinance"),
    }


def ensure_actual_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ACTUAL_OHLC_COLUMNS + ACTUAL_METADATA_COLUMNS + ACTUAL_REQUIRED_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    for col in ["actual_date", "actual_source", "actual_update_status", "actual_update_reason", "actual_updated_at"]:
        out[col] = out[col].astype("object")
    return out


def missing_ohlc_columns(row: pd.Series) -> list[str]:
    return [col for col in ACTUAL_OHLC_COLUMNS if col not in row.index or is_missing(row.get(col))]


def actual_ohlc_flat_suspect(row: pd.Series) -> bool:
    values = [safe_float(row.get(col)) for col in ACTUAL_OHLC_COLUMNS]
    if any(math.isnan(v) for v in values):
        return False
    first = values[0]
    if not all(math.isclose(v, first, rel_tol=0.0, abs_tol=max(abs(first) * 1e-10, 1e-8)) for v in values[1:]):
        return False
    return True


def set_update_status(out: pd.DataFrame, idx: Any, status: str, reason: str, updated_at: str | None = None) -> None:
    out.loc[idx, "actual_update_status"] = status
    out.loc[idx, "actual_update_reason"] = reason
    if updated_at is not None:
        out.loc[idx, "actual_updated_at"] = updated_at


def clear_actual_values(out: pd.DataFrame, idx: Any) -> None:
    for col in ACTUAL_OHLC_COLUMNS + ["actual_volume"]:
        out.loc[idx, col] = pd.NA
    for col in ["actual_date", "actual_source"]:
        out.loc[idx, col] = ""


def update_predictions_with_actuals(
    df: pd.DataFrame,
    *,
    today: date | None = None,
    max_rows: int | None = None,
    fetcher: FetchActualFn | None = None,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, ActualUpdateStats]:
    out = ensure_actual_columns(df)
    stats = ActualUpdateStats(scanned=len(out))
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    updated_at = now.astimezone(KST).isoformat(timespec="seconds")
    fetcher = fetcher or fetch_actual_ohlc

    for idx, row in out.iterrows():
        if max_rows is not None and stats.updated_rows >= max_rows:
            break

        ticker = row.get("ticker", "")
        target_raw = row.get("target_date", "")
        target_ts = pd.to_datetime(target_raw, errors="coerce")
        if is_missing(ticker) or pd.isna(target_ts):
            stats.invalid_rows += 1
            set_update_status(out, idx, "invalid_row", "missing ticker or invalid target_date")
            continue
        if target_ts.date() > today:
            stats.future_rows += 1
            set_update_status(out, idx, "pending_future", "target_date is in the future")
            continue

        missing_cols = missing_ohlc_columns(row)
        flat_suspect = actual_ohlc_flat_suspect(row)
        if (missing_cols or flat_suspect) and not market_actual_ready(row.get("market", ""), target_ts.date(), now):
            stats.pending_not_ready_rows += 1
            if flat_suspect:
                clear_actual_values(out, idx)
                stats.cleared_flat_rows += 1
            set_update_status(
                out,
                idx,
                "pending_session_not_closed",
                "target market session is not closed yet",
                updated_at if flat_suspect else None,
            )
            continue

        if not missing_cols and not flat_suspect:
            stats.skipped_existing += 1
            set_update_status(out, idx, "already_present", "actual OHLC already present")
            continue

        if flat_suspect:
            missing_cols = list(ACTUAL_OHLC_COLUMNS)
            stats.flat_suspect_rows += 1

        stats.eligible += 1
        actual = fetcher(ticker, row.get("market", ""), target_raw)
        if not actual:
            stats.fetch_failed += 1
            reason = (
                "flat actual OHLC suspected, but source returned no data"
                if flat_suspect
                else "actual OHLC source returned no data"
            )
            if flat_suspect:
                clear_actual_values(out, idx)
                stats.cleared_flat_rows += 1
            set_update_status(out, idx, "fetch_failed", reason, updated_at if flat_suspect else None)
            continue

        changed_cols: list[str] = []
        for col in missing_cols:
            value = actual.get(col)
            if is_missing(value):
                continue
            out.loc[idx, col] = value
            changed_cols.append(col)
            stats.filled_cells += 1

        for col in ACTUAL_METADATA_COLUMNS:
            if (flat_suspect or is_missing(out.loc[idx, col])) and not is_missing(actual.get(col)):
                out.loc[idx, col] = actual.get(col)

        if changed_cols:
            stats.updated_rows += 1
            if flat_suspect:
                set_update_status(out, idx, "refreshed_flat_ohlc", "replaced flat OHLC with daily Open/High/Low/Close", updated_at)
            else:
                set_update_status(out, idx, "updated", "filled " + ",".join(changed_cols), updated_at)
        else:
            stats.fetch_failed += 1
            if flat_suspect:
                clear_actual_values(out, idx)
                stats.cleared_flat_rows += 1
                set_update_status(out, idx, "fetch_failed", "flat actual OHLC suspected, but source data was incomplete", updated_at)
            else:
                set_update_status(out, idx, "fetch_failed", "source data did not include missing OHLC fields")

    stats.output_rows = len(out)
    return out, stats


def enrich_review_columns(df: pd.DataFrame) -> pd.DataFrame:
    from core.review_learning_engine import enrich_predictions_with_review

    return enrich_predictions_with_review(df)


def run_review_actual_update(
    path: Path = PREDICTIONS_FILE,
    *,
    dry_run: bool = False,
    max_rows: int | None = None,
) -> tuple[pd.DataFrame, ActualUpdateStats]:
    if not path.exists():
        raise FileNotFoundError(f"predictions file not found: {path}")

    original = read_predictions(path)
    missing_required = [c for c in ACTUAL_REQUIRED_COLUMNS if c not in original.columns]
    updated, stats = update_predictions_with_actuals(original, max_rows=max_rows)
    enriched = enrich_review_columns(updated)

    if not dry_run:
        if stats.updated_rows > 0 or missing_required:
            backup_predictions_file(path)
        enriched.to_csv(path, index=False, encoding="utf-8-sig")

    return enriched, stats
