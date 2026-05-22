"""v34 risk-first decision support engine.

Creates a local risk-priority table from prediction files. It is a decision aid
only and never sends orders.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPORT_DIR = Path("reports")
PREDICTION_FILE = Path("predictions.csv")
OUT_CSV = REPORT_DIR / "risk_priority_candidates.csv"
OUT_JSON = REPORT_DIR / "risk_priority_summary.json"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def _pick_col(df: pd.DataFrame, names: list[str]) -> str | None:
    low = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        if name in df.columns:
            return name
        key = name.strip().lower()
        if key in low:
            return low[key]
    return None


def _num(x: Any, default: float = math.nan) -> float:
    s = str(x or "").strip().replace(",", "").replace("%", "")
    if not s or s.lower() in {"nan", "none", "nat", "-", "미수신"}:
        return default
    try:
        return float(s)
    except Exception:
        return default


def _market_from_symbol(sym: Any) -> str:
    s = str(sym or "").strip().upper()
    return "한국주식" if s.isdigit() or s.endswith((".KS", ".KQ")) else "미국주식"


def _latest_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    tcol = _pick_col(out, ["ticker", "symbol", "종목코드", "종목", "티커"])
    if tcol and tcol != "ticker":
        out["ticker"] = out[tcol].astype(str).str.strip()
    elif "ticker" not in out.columns:
        out["ticker"] = ""
    dcol = _pick_col(out, ["target_date", "예측대상일", "date", "날짜", "created_at", "prediction_date"])
    if dcol:
        out["_date"] = pd.to_datetime(out[dcol], errors="coerce")
        out = out.sort_values("_date")
    return out.drop_duplicates(subset=["ticker"], keep="last")


def _risk_row(row: pd.Series, cols: dict[str, str | None]) -> dict[str, Any]:
    ticker = str(row.get("ticker", "")).strip()
    market = str(row.get(cols.get("market") or "", "") or "").strip() if cols.get("market") else _market_from_symbol(ticker)
    entry = _num(row.get(cols.get("entry") or "")) if cols.get("entry") else math.nan
    stop = _num(row.get(cols.get("stop") or "")) if cols.get("stop") else math.nan
    tp = _num(row.get(cols.get("tp") or "")) if cols.get("tp") else math.nan
    current = _num(row.get(cols.get("current") or "")) if cols.get("current") else math.nan
    conf = _num(row.get(cols.get("confidence") or ""), 50) if cols.get("confidence") else 50
    no_buy_score = _num(row.get(cols.get("no_buy_score") or ""), 50) if cols.get("no_buy_score") else 50
    no_buy_level = str(row.get(cols.get("no_buy_level") or "", "") or "") if cols.get("no_buy_level") else ""
    final_decision = str(row.get(cols.get("decision") or "", "") or "") if cols.get("decision") else ""

    rr = math.nan
    if not any(math.isnan(v) for v in [entry, stop, tp]) and entry != stop:
        rr = abs((tp - entry) / (entry - stop))
    chase_pct = math.nan
    if not any(math.isnan(v) for v in [current, entry]) and entry:
        chase_pct = (current / entry - 1) * 100

    flags: list[str] = []
    if not math.isnan(rr) and rr < 2:
        flags.append("손익비 1:2 미만")
    if not math.isnan(chase_pct) and chase_pct > 3:
        flags.append("우선진입가 대비 추격 위험")
    if conf < 55:
        flags.append("확신도 낮음")
    if no_buy_level in {"매수금지", "강한 매수금지", "데이터 부족"} or no_buy_score >= 75:
        flags.append("매수금지/데이터 위험")
    if any(word in final_decision for word in ["관망", "금지", "보류"]):
        flags.append("최종판단 관망/보류")
    if not flags:
        action = "조건부 매수 검토"
    elif any("매수금지" in f or "데이터" in f for f in flags):
        action = "신규매수 제외"
    elif any("추격" in f for f in flags):
        action = "진입가 대기"
    else:
        action = "소액/분할만"

    risk_score = 0
    if not math.isnan(rr):
        risk_score += max(0, int((2.0 - rr) * 20))
    if not math.isnan(chase_pct):
        risk_score += max(0, int(chase_pct * 2))
    risk_score += max(0, int((60 - conf) * 0.8))
    risk_score += max(0, int((no_buy_score - 50) * 0.8))
    if no_buy_level in {"매수금지", "강한 매수금지"}:
        risk_score += 40

    return {
        "ticker": ticker,
        "market": market,
        "현재가": current if not math.isnan(current) else "",
        "우선진입가": entry if not math.isnan(entry) else "",
        "손절가": stop if not math.isnan(stop) else "",
        "1차목표": tp if not math.isnan(tp) else "",
        "손익비": round(rr, 2) if not math.isnan(rr) else "",
        "진입가대비괴리율%": round(chase_pct, 2) if not math.isnan(chase_pct) else "",
        "확신도": round(conf, 1),
        "매수금지점수": round(no_buy_score, 1),
        "매수금지등급": no_buy_level,
        "추천행동": action,
        "리스크점수": int(max(0, min(100, risk_score))),
        "리스크사유": " / ".join(flags) if flags else "큰 차단 사유 없음",
        "기존판단": final_decision,
    }


def save_risk_priority_candidates() -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df = _latest_rows(_read_csv(PREDICTION_FILE))
    if df.empty:
        result = {"status": "NO_DATA", "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "message": "predictions.csv가 없거나 비어 있습니다."}
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    cols = {
        "market": _pick_col(df, ["market", "시장"]),
        "entry": _pick_col(df, ["preferred_entry", "우선진입가", "entry_price", "진입가"]),
        "stop": _pick_col(df, ["stop_loss", "손절가", "stop"]),
        "tp": _pick_col(df, ["take_profit1", "1차목표", "target_price", "익절가"]),
        "current": _pick_col(df, ["current_price", "현재가", "last", "close", "price"]),
        "confidence": _pick_col(df, ["confidence_score", "confidence", "신뢰도", "확신도", "score"]),
        "no_buy_score": _pick_col(df, ["no_buy_score", "매수금지점수", "risk_score"]),
        "no_buy_level": _pick_col(df, ["no_buy_level", "매수금지등급", "no_buy_label"]),
        "decision": _pick_col(df, ["final_decision", "최종판단", "decision"]),
    }
    rows = [_risk_row(r, cols) for _, r in df.iterrows()]
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["리스크점수", "확신도"], ascending=[True, False])
        out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    action_counts = out["추천행동"].value_counts().to_dict() if not out.empty and "추천행동" in out.columns else {}
    result = {
        "status": "OK",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(out)),
        "action_counts": action_counts,
        "csv": str(OUT_CSV),
        "note": "좋은 종목보다 좋은 가격 원칙에 맞춰 손익비·추격위험·매수금지 점수를 우선 반영했습니다.",
    }
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def read_risk_priority_summary() -> dict[str, Any]:
    if not OUT_JSON.exists():
        return save_risk_priority_candidates()
    try:
        return json.loads(OUT_JSON.read_text(encoding="utf-8"))
    except Exception:
        return save_risk_priority_candidates()


if __name__ == "__main__":
    print(json.dumps(save_risk_priority_candidates(), ensure_ascii=False, indent=2, default=str))
