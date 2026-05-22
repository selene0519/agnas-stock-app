from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.swing_candidate_io import SWING_CANDIDATE_FILES, read_swing_candidate_csv


REPORT_DIR = Path("reports")
SECTOR_REPORT_PATH = REPORT_DIR / "intraday_sector_flow_report.csv"
SECTOR_SUMMARY_PATH = REPORT_DIR / "intraday_sector_flow_summary.json"
REALTIME_SNAPSHOT_PATH = REPORT_DIR / "intraday_realtime_snapshot.csv"

SECTOR_COLUMNS = [
    "sector",
    "sector_target_count",
    "sector_up_ratio",
    "sector_avg_intraday_change_pct",
    "sector_median_intraday_change_pct",
    "sector_avg_trading_value_ratio",
    "sector_money_flow_score",
    "sector_breadth_score",
    "sector_intraday_strength_score",
    "sector_flow_label",
    "sector_flow_warning",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat", "-"}:
        return default
    for token in ["$", "원", ",", "배", "%"]:
        text = text.replace(token, "")
    try:
        return float(text)
    except Exception:
        return default


def _clamp(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _sector_lookup_from_candidates() -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for path in SWING_CANDIDATE_FILES:
        df = read_swing_candidate_csv(path)
        if df.empty:
            continue
        for _, row in df.iterrows():
            symbol = str(row.get("symbol", "") or row.get("ticker", "")).strip().upper()
            market = str(row.get("market", "")).strip()
            sector = str(row.get("sector", "") or row.get("industry", "") or "").strip()
            if symbol and sector:
                lookup[(symbol, market)] = sector
                lookup[(symbol, "")] = sector
    return lookup


def load_sector_targets() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    sector_lookup = _sector_lookup_from_candidates()
    for path in SWING_CANDIDATE_FILES:
        df = read_swing_candidate_csv(path)
        if df.empty:
            continue
        for _, row in df.iterrows():
            sector = str(row.get("sector", "") or row.get("industry", "") or "").strip()
            symbol = str(row.get("symbol", "") or row.get("ticker", "")).strip()
            if not symbol:
                continue
            rows.append({
                "symbol": symbol,
                "market": str(row.get("market", "")).strip(),
                "sector": sector or "미분류",
                "intraday_change_pct": _num(row.get("intraday_price_change_pct", row.get("intraday_change_pct"))),
                "intraday_trading_value_ratio": _num(row.get("intraday_trading_value_ratio")),
            })
    if REALTIME_SNAPSHOT_PATH.exists() and REALTIME_SNAPSHOT_PATH.stat().st_size > 0:
        snap = pd.read_csv(REALTIME_SNAPSHOT_PATH, low_memory=False)
        if not snap.empty and "symbol" in snap.columns:
            for _, row in snap.iterrows():
                symbol = str(row.get("symbol", "")).strip()
                if not symbol:
                    continue
                market = str(row.get("market", "")).strip()
                key = (symbol.upper(), market)
                sector = sector_lookup.get(key, sector_lookup.get((symbol.upper(), ""), "미분류"))
                rows.append({
                    "symbol": symbol,
                    "market": market,
                    "sector": sector or "미분류",
                    "intraday_change_pct": _num(row.get("intraday_change_pct")),
                    "intraday_trading_value_ratio": _num(row.get("intraday_trading_value_ratio")),
                })
    if not rows:
        return pd.DataFrame(columns=["symbol", "market", "sector", "intraday_change_pct", "intraday_trading_value_ratio"])
    out = pd.DataFrame(rows)
    out["_sym"] = out["symbol"].astype(str).str.upper()
    out["_mkt"] = out["market"].astype(str).str.strip()
    out = out.drop_duplicates(subset=["_sym", "_mkt"], keep="first").drop(columns=["_sym", "_mkt"], errors="ignore")
    return out


def _merge_intraday_snapshot(candidate_df: pd.DataFrame, intraday_df: pd.DataFrame | None) -> pd.DataFrame:
    work = candidate_df.copy()
    if intraday_df is None or intraday_df.empty:
        if REALTIME_SNAPSHOT_PATH.exists() and REALTIME_SNAPSHOT_PATH.stat().st_size > 0:
            intraday_df = pd.read_csv(REALTIME_SNAPSHOT_PATH, low_memory=False)
        else:
            return work
    if intraday_df is None or intraday_df.empty or "symbol" not in intraday_df.columns:
        return work
    quote_map: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in intraday_df.iterrows():
        sym = str(row.get("symbol", "")).strip().upper()
        market = str(row.get("market", "")).strip()
        if sym:
            quote_map[(sym, market)] = row.to_dict()
    updated: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        item = row.to_dict()
        sym = str(item.get("symbol", "")).strip().upper()
        market = str(item.get("market", "")).strip()
        quote = quote_map.get((sym, market), quote_map.get((sym, ""), {}))
        if quote:
            item["intraday_change_pct"] = _num(quote.get("intraday_change_pct", item.get("intraday_change_pct")))
            item["intraday_trading_value_ratio"] = _num(
                quote.get("intraday_trading_value_ratio", item.get("intraday_trading_value_ratio"))
            )
        updated.append(item)
    return pd.DataFrame(updated)


def calculate_sector_intraday_strength(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df.empty or "sector" not in candidate_df.columns:
        return pd.DataFrame(columns=SECTOR_COLUMNS)
    rows: list[dict[str, Any]] = []
    for sector, group in candidate_df.groupby("sector"):
        sector_name = str(sector or "미분류").strip() or "미분류"
        count = int(len(group))
        changes = pd.to_numeric(group.get("intraday_change_pct", 0), errors="coerce").fillna(0)
        value_ratios = pd.to_numeric(group.get("intraday_trading_value_ratio", 0), errors="coerce").fillna(0)
        up_ratio = float((changes > 0).mean()) if count else 0.0
        avg_change = float(changes.mean()) if count else 0.0
        median_change = float(changes.median()) if count else 0.0
        avg_value_ratio = float(value_ratios.mean()) if count else 0.0
        down_mask = changes < 0
        risky_value = float(value_ratios[down_mask].mean()) if down_mask.any() else 0.0

        money_flow_score = _clamp(50 + avg_change * 4 + (avg_value_ratio - 1.0) * 12)
        breadth_score = _clamp(up_ratio * 100)
        strength_score = _clamp(money_flow_score * 0.55 + breadth_score * 0.45)

        label = "섹터 장중 중립"
        warning = ""
        if count < 3:
            label = "표본 부족"
            warning = "업종 후보 수 부족"
        elif up_ratio >= 0.6 and avg_change > 0 and avg_value_ratio >= 1.0:
            label = "섹터 장중 강세"
        elif up_ratio <= 0.35 and avg_change < 0:
            label = "섹터 장중 약세"
        elif risky_value >= 1.2 and avg_change < 0:
            label = "위험 거래대금"
            warning = "하락 종목 거래대금 집중"

        rows.append({
            "sector": sector_name,
            "sector_target_count": count,
            "sector_up_ratio": round(up_ratio, 4),
            "sector_avg_intraday_change_pct": round(avg_change, 4),
            "sector_median_intraday_change_pct": round(median_change, 4),
            "sector_avg_trading_value_ratio": round(avg_value_ratio, 4),
            "sector_money_flow_score": money_flow_score,
            "sector_breadth_score": breadth_score,
            "sector_intraday_strength_score": strength_score,
            "sector_flow_label": label,
            "sector_flow_warning": warning,
        })
    return pd.DataFrame(rows, columns=SECTOR_COLUMNS)


def build_intraday_sector_flow(
    candidate_df: pd.DataFrame | None = None,
    intraday_df: pd.DataFrame | None = None,
    flow_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    del flow_df
    base = candidate_df if candidate_df is not None else load_sector_targets()
    merged = _merge_intraday_snapshot(base, intraday_df)
    return calculate_sector_intraday_strength(merged)


def save_intraday_sector_flow_report(path: str | Path = SECTOR_REPORT_PATH) -> dict[str, Any]:
    target = Path(path)
    try:
        df = build_intraday_sector_flow()
        target.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(target, index=False, encoding="utf-8-sig")
        return {"path": str(target), "rows": int(len(df)), "status": "OK"}
    except Exception as exc:
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=SECTOR_COLUMNS).to_csv(target, index=False, encoding="utf-8-sig")
        return {"path": str(target), "rows": 0, "status": "ERROR", "error": str(exc)}


def _summary_from_report(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "updated_at": _now(),
            "sector_count": 0,
            "strong_sector_count": 0,
            "weak_sector_count": 0,
            "top_intraday_sectors": [],
            "weak_intraday_sectors": [],
            "sector_flow_warning_count": 0,
            "overall_status": "NO_TARGETS",
            "warnings": ["업종 대상 없음"],
            "errors": [],
        }
    labels = df.get("sector_flow_label", pd.Series("", index=df.index)).astype(str)
    warnings = df.get("sector_flow_warning", pd.Series("", index=df.index)).astype(str).str.strip()
    strength = pd.to_numeric(df.get("sector_intraday_strength_score", 0), errors="coerce").fillna(0)
    strong_count = int(labels.str.contains("강세", na=False).sum())
    weak_count = int(labels.str.contains("약세", na=False).sum())
    top_sectors = df.sort_values("sector_intraday_strength_score", ascending=False).head(5)["sector"].astype(str).tolist()
    weak_sectors = df.sort_values("sector_intraday_strength_score", ascending=True).head(5)["sector"].astype(str).tolist()
    warning_count = int(warnings.ne("").sum())
    overall = "OK" if warning_count == 0 else "WARNING"
    if int((strength <= 0).sum()) == len(df):
        overall = "NO_TARGETS"
    return {
        "updated_at": _now(),
        "sector_count": int(len(df)),
        "strong_sector_count": strong_count,
        "weak_sector_count": weak_count,
        "top_intraday_sectors": top_sectors,
        "weak_intraday_sectors": weak_sectors,
        "sector_flow_warning_count": warning_count,
        "overall_status": overall,
        "warnings": ["일부 업종 표본 부족"] if warning_count else [],
        "errors": [],
    }


def save_intraday_sector_flow_summary(path: str | Path = SECTOR_SUMMARY_PATH) -> dict[str, Any]:
    target = Path(path)
    try:
        if SECTOR_REPORT_PATH.exists() and SECTOR_REPORT_PATH.stat().st_size > 0:
            df = pd.read_csv(SECTOR_REPORT_PATH, low_memory=False)
        else:
            df = build_intraday_sector_flow()
        summary = _summary_from_report(df)
    except Exception as exc:
        summary = {
            "updated_at": _now(),
            "sector_count": 0,
            "overall_status": "ERROR",
            "warnings": [],
            "errors": [str(exc)],
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"path": str(target), **summary}


def main() -> int:
    report = save_intraday_sector_flow_report()
    summary = save_intraday_sector_flow_summary()
    result = {"report": report, "summary": summary}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if summary.get("overall_status") == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
