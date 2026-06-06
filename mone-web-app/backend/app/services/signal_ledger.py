"""Signal ledger — Phase 3/4

호라이즌별 자동 결과 검증:
  short  (단기): D+1, D+3, D+5
  swing  (스윙): D+3, D+5, D+10
  mid    (중기): D+5, D+10, D+20
"""
from __future__ import annotations

import csv
import uuid
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# Repo root: signal_ledger.py → services/ → app/ → backend/ → mone-web-app/ → ROOT
ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = ROOT / "data"
LEDGER_CSV = DATA_DIR / "signal_ledger.csv"
OUTCOMES_CSV = DATA_DIR / "signal_outcomes.csv"
OHLCV_DIR = DATA_DIR / "market" / "ohlcv"
REPORTS_DIR = ROOT / "reports"

HORIZON_WINDOWS: dict[str, list[int]] = {
    "short": [1, 3, 5],
    "swing": [3, 5, 10],
    "mid":   [5, 10, 20],
}
HORIZON_BADGE_WINDOW = {"short": 5, "swing": 10, "mid": 20}

LEDGER_COLS = [
    "id", "market", "symbol", "name", "mode", "horizon",
    "entry", "stop", "target", "ev", "probability", "score",
    "decision_bucket", "sector", "recorded_at", "recorded_date",
]
OUTCOME_COLS = [
    "signal_id", "window_days", "close_price",
    "return_pct", "hit_target", "hit_stop", "verified_at",
]


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LEDGER_CSV.exists():
        with open(LEDGER_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(LEDGER_COLS)
    if not OUTCOMES_CSV.exists():
        with open(OUTCOMES_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(OUTCOME_COLS)


def _read_ledger() -> pd.DataFrame:
    try:
        df = pd.read_csv(LEDGER_CSV, dtype=str)
        return df
    except Exception:
        return pd.DataFrame(columns=LEDGER_COLS)


def _read_outcomes() -> pd.DataFrame:
    try:
        df = pd.read_csv(OUTCOMES_CSV, dtype={"window_days": int, "return_pct": float,
                                               "hit_target": str, "hit_stop": str})
        return df
    except Exception:
        return pd.DataFrame(columns=OUTCOME_COLS)


# ── Record ─────────────────────────────────────────────────────────────────

def record(
    market: str, symbol: str, name: str,
    mode: str, horizon: str,
    entry: float, stop: float, target: float,
    ev: float, probability: float, score: float,
    decision_bucket: str, sector: str = "",
) -> dict:
    _ensure()
    today = date.today().isoformat()

    # Dedup: same symbol+mode+horizon already recorded today
    df = _read_ledger()
    if not df.empty:
        dup = df[
            (df["symbol"] == symbol) &
            (df["mode"] == mode) &
            (df["horizon"] == horizon) &
            (df["recorded_date"] == today)
        ]
        if not dup.empty:
            return {"ok": True, "duplicate": True, "id": str(dup.iloc[0]["id"])}

    sid = str(uuid.uuid4())[:12]
    with open(LEDGER_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            sid, market, symbol, name, mode, horizon,
            entry, stop, target, ev, probability, score,
            decision_bucket, sector,
            datetime.now().isoformat(), today,
        ])
    return {"ok": True, "duplicate": False, "id": sid}


# ── Verify ─────────────────────────────────────────────────────────────────

def verify() -> dict:
    """호라이즌별 OHLCV 기반 결과 검증."""
    _ensure()
    ledger = _read_ledger()
    outcomes = _read_outcomes()

    verified = skipped = 0

    for _, row in ledger.iterrows():
        sid = str(row["id"])
        horizon = str(row.get("horizon", "swing"))
        windows = HORIZON_WINDOWS.get(horizon, [3, 5, 10])
        entry = float(row.get("entry", 0) or 0)
        stop  = float(row.get("stop", 0) or 0)
        target = float(row.get("target", 0) or 0)
        recorded_date = str(row.get("recorded_date", ""))
        market = str(row.get("market", "kr"))
        symbol = str(row.get("symbol", ""))

        if not recorded_date or entry <= 0:
            continue

        ohlcv_path = OHLCV_DIR / f"{market}_{symbol}_daily.csv"
        if not ohlcv_path.exists():
            skipped += 1
            continue

        try:
            ohlcv = pd.read_csv(ohlcv_path, encoding="utf-8-sig")
            ohlcv.columns = [c.lstrip("﻿").strip() for c in ohlcv.columns]
            ohlcv["date"] = pd.to_datetime(ohlcv["date"])
            ohlcv = ohlcv.sort_values("date").reset_index(drop=True)

            rec_dt = pd.to_datetime(recorded_date)
            future = ohlcv[ohlcv["date"] > rec_dt].reset_index(drop=True)

            for w in windows:
                already = outcomes[
                    (outcomes["signal_id"] == sid) &
                    (outcomes["window_days"] == w)
                ]
                if not already.empty:
                    continue
                if len(future) < w:
                    continue  # 아직 데이터 없음

                w_row = future.iloc[w - 1]
                close_p = float(w_row.get("close", 0) or 0)
                slc = future.iloc[:w]
                high_max = float(slc["high"].max() or 0)
                low_min  = float(slc["low"].min() or 0)

                ret = round((close_p - entry) / entry * 100, 2) if entry > 0 and close_p > 0 else 0.0
                hit_t = bool(target > 0 and high_max >= target)
                hit_s = bool(stop > 0 and low_min <= stop)

                with open(OUTCOMES_CSV, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([
                        sid, w, close_p, ret,
                        str(hit_t), str(hit_s),
                        datetime.now().isoformat(),
                    ])
                verified += 1

        except Exception:
            skipped += 1

    return {"ok": True, "verified": verified, "skipped": skipped}


# ── Badge ──────────────────────────────────────────────────────────────────

def badge(symbol: str, horizon: str = "all", mode: str = "all") -> dict:
    """백테스트 뱃지 통계 — 호라이즌에 맞는 검증 윈도우 사용."""
    _ensure()
    ledger   = _read_ledger()
    outcomes = _read_outcomes()

    mask = ledger["symbol"] == symbol
    if horizon not in ("all", ""):
        mask &= ledger["horizon"] == horizon
    if mode not in ("all", ""):
        mask &= ledger["mode"] == mode

    matched = ledger[mask]
    if matched.empty:
        return {"sample": 0, "winRate": None, "avgReturn": None}

    target_window = HORIZON_BADGE_WINDOW.get(horizon, 10)
    sids = matched["id"].astype(str).tolist()

    try:
        outs = outcomes[
            (outcomes["signal_id"].astype(str).isin(sids)) &
            (outcomes["window_days"].astype(int) == target_window)
        ]
    except Exception:
        outs = pd.DataFrame()

    if outs.empty:
        return {
            "sample": len(matched),
            "winRate": None, "avgReturn": None,
            "windowDays": target_window, "pending": True,
        }

    returns = outs["return_pct"].astype(float)
    wins = (returns > 0).sum()

    return {
        "sample": len(outs),
        "totalRecorded": len(matched),
        "winRate": round(float(wins / len(outs) * 100), 1),
        "avgReturn": round(float(returns.mean()), 2),
        "windowDays": target_window,
        "pending": False,
    }


# ── Ledger list ────────────────────────────────────────────────────────────

def ledger_list(market: str = "all", limit: int = 100) -> dict:
    _ensure()
    ledger   = _read_ledger()
    outcomes = _read_outcomes()

    if market not in ("all", ""):
        ledger = ledger[ledger["market"] == market]

    ledger = ledger.sort_values("recorded_at", ascending=False).head(limit)

    items = []
    for _, row in ledger.iterrows():
        sid = str(row["id"])
        outs = outcomes[outcomes["signal_id"].astype(str) == sid]
        items.append({
            **{k: (None if (str(v) in ("nan", "")) else v) for k, v in row.to_dict().items()},
            "outcomes": outs.to_dict("records") if not outs.empty else [],
        })

    return {"items": items, "count": len(items)}


# ── Portfolio conflict ─────────────────────────────────────────────────────

def portfolio_conflict(symbol: str, market: str, sector: str = "") -> dict:
    """보유종목과의 섹터 충돌 검사."""
    holdings_path = ROOT / f"holdings_{market}.csv"
    if not holdings_path.exists():
        return {"ok": True, "conflicts": [], "score": 0, "message": "보유종목 없음"}

    try:
        holdings = pd.read_csv(holdings_path, encoding="utf-8-sig", dtype=str)
        holdings.columns = [c.lstrip("﻿").strip() for c in holdings.columns]
    except Exception as e:
        return {"ok": False, "error": str(e), "conflicts": [], "score": 0}

    # 추천 파일에서 섹터 정보 수집
    holding_sectors: dict[str, str] = {}
    for csv_file in REPORTS_DIR.glob("mone_v36_final_recommendations_*.csv"):
        try:
            df = pd.read_csv(csv_file, encoding="utf-8-sig", usecols=["symbol", "sector"], dtype=str)
            for _, r in df.iterrows():
                s = str(r.get("symbol", "")).strip()
                sec = str(r.get("sector", "")).strip()
                if s and sec and s not in holding_sectors:
                    holding_sectors[s] = sec
        except Exception:
            continue

    target_sector = sector.strip()
    conflicts = []

    for _, h in holdings.iterrows():
        h_sym = str(h.get("symbol", "")).strip()
        if h_sym == symbol:
            continue
        h_sector = holding_sectors.get(h_sym, "")
        if target_sector and h_sector and target_sector == h_sector:
            conflicts.append({
                "symbol": h_sym,
                "name": str(h.get("name", "")),
                "sector": h_sector,
                "type": "섹터 동일",
            })

    score = min(100, len(conflicts) * 35)
    msg = "충돌 없음" if not conflicts else f"{len(conflicts)}개 보유종목과 섹터({target_sector}) 겹침"

    return {
        "ok": True, "symbol": symbol,
        "sector": target_sector,
        "conflicts": conflicts,
        "score": score,
        "message": msg,
    }
