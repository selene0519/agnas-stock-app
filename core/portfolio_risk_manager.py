from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


RISK_LOW = "\ub0ae\uc74c"
RISK_NORMAL = "\ubcf4\ud1b5"
RISK_HIGH = "\ub192\uc74c"
RISK_VERY_HIGH = "\ub9e4\uc6b0 \ub192\uc74c"
MODE_RISK = "\uc704\ud5d8\uc7a5"
GRADE_FORBIDDEN = "\uae08\uc9c0"
REPORT_DIR = Path("reports")
PORTFOLIO_RISK_SUMMARY_JSON = REPORT_DIR / "portfolio_risk_summary.json"
UNCLASSIFIED_SECTOR = "미분류"
SECTOR_MAPPING_CSV = Path("data") / "sector_mapping.csv"
DEFAULT_LOSS_PCT = 7.0
DEFENSIVE_LOSS_PCT = 5.0
HIGH_BETA_LOSS_PCT = 10.0
RISK_MARKET_LOSS_ADD_PCT = 2.0
PORTFOLIO_RISK_COLUMNS = [
    "portfolio_risk_level",
    "total_exposure_pct",
    "sector_concentration_warning",
    "portfolio_expected_return",
    "max_expected_loss_pct",
    "portfolio_action",
    "portfolio_warnings",
]
DEFAULT_CANDIDATE_FILES = [
    REPORT_DIR / "swing_candidates_us_A_top3.csv",
    REPORT_DIR / "swing_candidates_us_B_watch.csv",
    REPORT_DIR / "swing_candidates_us_C_excluded.csv",
    REPORT_DIR / "swing_candidates_kr_A_top3.csv",
    REPORT_DIR / "swing_candidates_kr_B_watch.csv",
    REPORT_DIR / "swing_candidates_kr_C_excluded.csv",
]
DEFAULT_METADATA_FILES = [
    Path("candidate_universe_us.csv"),
    Path("candidate_universe_kr.csv"),
    Path("watchlist_us_growth.csv"),
    Path("watchlist_us.csv"),
    Path("watchlist_kr_growth.csv"),
    Path("watchlist_kr.csv"),
    Path("data") / "watchlist.csv",
]
HOLDINGS_PATHS = {
    "미국주식": [Path("holdings_us.csv"), Path("data/holdings_us.csv")],
    "한국주식": [Path("holdings_kr.csv"), Path("data/holdings_kr.csv")],
}


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").replace("$", "").strip()
            if value in {"", "-", "nan", "None"}:
                return default
        return float(value)
    except Exception:
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_str(value).lower()
    if text in {"1", "1.0", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "0.0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _first_value(row: dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if _safe_str(value):
            return value
    return default


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_unclassified_sector(value: Any) -> bool:
    text = _safe_str(value)
    return not text or text.lower() in {"nan", "none", "null", "-", "미분류", "unclassified", "unknown"}


def _sector(row: dict[str, Any]) -> str:
    return _safe_str(_first_value(row, ["sector", "sector_proxy", "theme", "group", "업종", "섹터", "테마"], UNCLASSIFIED_SECTOR)) or UNCLASSIFIED_SECTOR


def _symbol(row: dict[str, Any]) -> str:
    return _safe_str(_first_value(row, ["symbol", "ticker", "종목", "종목코드"], ""))


def _normalized_symbol_keys(symbol: Any) -> list[str]:
    raw = _safe_str(symbol).upper()
    if not raw:
        return []
    base = raw.split(".")[0]
    compact = "".join(ch for ch in base if ch.isalnum())
    keys = [raw, base, compact]
    if compact.isdigit():
        keys.extend([compact.lstrip("0") or "0", compact.zfill(6)])
    return list(dict.fromkeys([key for key in keys if key]))


def _resolve_path(base_dir: str | Path, path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else Path(base_dir) / p


def _metadata_from_row(row: dict[str, Any], source: str = "") -> dict[str, str]:
    symbol = _symbol(row)
    sector = _safe_str(
        _first_value(
            row,
            ["sector", "sector_proxy", "업종", "섹터", "theme", "테마", "group"],
            "",
        )
    )
    theme = _safe_str(_first_value(row, ["theme", "테마", "group"], ""))
    return {
        "symbol": symbol,
        "sector": "" if _is_unclassified_sector(sector) else sector,
        "theme": theme,
        "type": _safe_str(row.get("type") or row.get("holding_type")),
        "risk_level": _safe_str(row.get("risk_level")),
        "source": source,
    }


def _merge_metadata(target: dict[str, dict[str, str]], metadata: dict[str, str]) -> None:
    if not metadata.get("symbol") or not metadata.get("sector"):
        return
    for key in _normalized_symbol_keys(metadata["symbol"]):
        if key not in target:
            target[key] = dict(metadata)


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


def build_sector_metadata_map(
    base_dir: str | Path = ".",
    candidates_df: pd.DataFrame | None = None,
    candidate_files: list[str | Path] | None = None,
) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}

    frames: list[tuple[str, pd.DataFrame]] = []
    if candidates_df is not None and not candidates_df.empty:
        frames.append(("candidates_df", candidates_df))
    for path in candidate_files or DEFAULT_CANDIDATE_FILES:
        frames.append(("candidate_file", _read_csv_if_exists(_resolve_path(base_dir, path))))
    for path in DEFAULT_METADATA_FILES:
        frames.append(("metadata_file", _read_csv_if_exists(_resolve_path(base_dir, path))))
    frames.append(("sector_mapping", _read_csv_if_exists(_resolve_path(base_dir, SECTOR_MAPPING_CSV))))

    for source, df in frames:
        if df is None or df.empty:
            continue
        for row in df.to_dict(orient="records"):
            _merge_metadata(metadata, _metadata_from_row(row, source))
    return metadata


def _lookup_metadata(symbol: Any, metadata_map: dict[str, dict[str, str]] | None) -> dict[str, str]:
    if not metadata_map:
        return {}
    for key in _normalized_symbol_keys(symbol):
        if key in metadata_map:
            return metadata_map[key]
    return {}


def _enrich_sector(row: dict[str, Any], metadata_map: dict[str, dict[str, str]] | None) -> tuple[str, str, str, str]:
    current_sector = _sector(row)
    current_theme = _safe_str(_first_value(row, ["theme", "테마"], ""))
    current_type = _safe_str(row.get("type") or row.get("holding_type"))
    current_risk = _safe_str(row.get("risk_level"))
    if not _is_unclassified_sector(current_sector):
        return current_sector, current_theme, current_type, current_risk
    metadata = _lookup_metadata(_symbol(row), metadata_map)
    sector = metadata.get("sector") or current_sector or UNCLASSIFIED_SECTOR
    theme = current_theme or metadata.get("theme", "")
    stock_type = current_type or metadata.get("type", "")
    risk_level = current_risk or metadata.get("risk_level", "")
    return sector, theme, stock_type, risk_level


def enrich_positions_with_sector_metadata(
    df: pd.DataFrame,
    metadata_map: dict[str, dict[str, str]] | None,
) -> pd.DataFrame:
    out = df.copy() if df is not None else pd.DataFrame()
    if out.empty:
        return out
    for idx, raw in out.to_dict(orient="index").items():
        sector, theme, stock_type, risk_level = _enrich_sector(raw, metadata_map)
        out.loc[idx, "sector"] = sector
        if theme:
            out.loc[idx, "theme"] = theme
        if stock_type:
            out.loc[idx, "type"] = stock_type
        if risk_level:
            out.loc[idx, "risk_level"] = risk_level
    return out


def _default_loss_pct(row: dict[str, Any]) -> float:
    joined = " ".join(
        _safe_str(row.get(key)).lower()
        for key in ["symbol", "sector", "theme", "type", "risk_level", "name", "holding_type"]
    )
    if any(token in joined for token in ["etf", "bond", "dividend", "defensive", "low_vol", "방어", "배당", "채권"]):
        return DEFENSIVE_LOSS_PCT
    if any(
        token in joined
        for token in [
            "high_beta",
            "speculative",
            "growth",
            "crypto",
            "bitcoin",
            "coin",
            "가상자산",
            "비트코인",
            "코인",
            "성장주",
            "매우 높음",
        ]
    ):
        return HIGH_BETA_LOSS_PCT
    return DEFAULT_LOSS_PCT


def _row_loss_pct(row: dict[str, Any], risk_market: bool = False) -> float:
    entry = _safe_float(row.get("entry"), 0.0)
    stop = _safe_float(row.get("stop"), 0.0)
    if entry > 0 and stop > 0 and stop < entry:
        return max(0.0, (entry - stop) / entry * 100)
    loss_pct = _safe_float(row.get("default_loss_pct"), 0.0) or _default_loss_pct(row)
    if risk_market:
        loss_pct += RISK_MARKET_LOSS_ADD_PCT
    return max(0.0, loss_pct)


def _enrich_dataframe_for_risk(df: pd.DataFrame, metadata_map: dict[str, dict[str, str]] | None) -> pd.DataFrame:
    out = enrich_positions_with_sector_metadata(df, metadata_map)
    if out.empty:
        return out
    defaults = []
    for row in out.to_dict(orient="records"):
        defaults.append(_default_loss_pct(row))
    out["default_loss_pct"] = defaults
    return out


def _candidate_forbidden(row: dict[str, Any]) -> bool:
    grade = _safe_str(row.get("strategy_adjusted_grade") or row.get("grade")).upper()
    action = _safe_str(row.get("position_action") or row.get("hold_or_sell_decision"))
    if grade in {"C", GRADE_FORBIDDEN}:
        return True
    if _safe_bool(row.get("strategy_trade_allowed"), True) is False:
        return True
    if "금지" in action or "관망" in action:
        return True
    return False


def _row_exposure(row: dict[str, Any], total_value: float = 0.0) -> float:
    for key in ["position_size_pct", "current_weight_pct", "weight_pct", "portfolio_weight_pct", "비중"]:
        if _safe_str(row.get(key)):
            return max(0.0, _safe_float(row.get(key), 0.0))
    value = 0.0
    for key in ["evaluation_amount", "current_value", "buy_amount", "amount", "평가금액"]:
        value = _safe_float(row.get(key), 0.0)
        if value > 0:
            break
    if total_value > 0 and value > 0:
        return max(0.0, value / total_value * 100)
    return 0.0


def _position_rows(df: pd.DataFrame, source: str, total_value: float = 0.0, candidates: bool = False) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        exposure = _row_exposure(row, total_value)
        forbidden = _candidate_forbidden(row) if candidates else False
        sector = _sector(row)
        rows.append(
            {
                "source": source,
                "symbol": _symbol(row),
                "sector": sector,
                "theme": _safe_str(row.get("theme") or row.get("테마")),
                "type": _safe_str(row.get("type") or row.get("holding_type")),
                "risk_level": _safe_str(row.get("risk_level")),
                "exposure_pct": exposure,
                "forbidden": forbidden,
                "strategy_mode": _safe_str(row.get("strategy_mode")),
                "market_risk_level": _safe_str(row.get("market_risk_level")),
                "new_buy_blocked": _safe_bool(row.get("new_buy_blocked"), False),
                "entry": _safe_float(row.get("entry") or row.get("avg_price") or row.get("current_price") or row.get("preferred_entry"), 0.0),
                "stop": _safe_float(row.get("stop") or row.get("stop_loss"), 0.0),
                "default_loss_pct": _safe_float(row.get("default_loss_pct"), 0.0) or _default_loss_pct(row),
                "expected_return_5d": _safe_float(row.get("expected_return_5d"), 0.0),
            }
        )
    return rows


def _positions_total_value(df: pd.DataFrame) -> float:
    if df is None or df.empty:
        return 0.0
    total = 0.0
    for row in df.to_dict(orient="records"):
        for key in ["evaluation_amount", "current_value", "buy_amount", "amount", "평가금액"]:
            value = _safe_float(row.get(key), 0.0)
            if value > 0:
                total += value
                break
    return total


def normalize_holdings_df(
    df: pd.DataFrame,
    market: str = "",
    metadata_map: dict[str, dict[str, str]] | None = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "market",
                "name",
                "avg_price",
                "quantity",
                "current_price",
                "position_value",
                "sector",
                "memo",
                "holding_type",
            ]
        )
    rows: list[dict[str, Any]] = []
    for raw in df.to_dict(orient="records"):
        ticker = _safe_str(_first_value(raw, ["ticker", "symbol", "종목", "종목코드"], ""))
        quantity = _safe_float(_first_value(raw, ["quantity", "shares", "qty", "수량", "보유수량"], 0), 0.0)
        avg_price = _safe_float(_first_value(raw, ["avg_price", "average_price", "평균단가"], 0), 0.0)
        current_price = _safe_float(_first_value(raw, ["current_price", "last_price", "현재가"], 0), 0.0)
        price = current_price if current_price > 0 else avg_price
        position_value = _safe_float(_first_value(raw, ["position_value", "evaluation_amount", "current_value", "buy_amount", "amount", "평가금액"], 0), 0.0)
        if position_value <= 0 and price > 0 and quantity > 0:
            position_value = price * quantity
        rows.append(
            {
                "ticker": ticker,
                "symbol": ticker,
                "market": _safe_str(raw.get("market")) or market,
                "name": _safe_str(_first_value(raw, ["name", "종목명"], "")),
                "avg_price": avg_price,
                "quantity": quantity,
                "current_price": price,
                "position_value": position_value,
                "evaluation_amount": position_value,
                "sector": _sector(raw),
                "theme": _safe_str(raw.get("theme") or raw.get("테마")),
                "type": _safe_str(raw.get("type")),
                "risk_level": _safe_str(raw.get("risk_level")),
                "stop_loss": _safe_float(_first_value(raw, ["stop_loss", "stop", "손절가"], 0), 0.0),
                "memo": _safe_str(raw.get("memo")),
                "holding_type": _safe_str(raw.get("holding_type")),
            }
        )
    out = pd.DataFrame(rows)
    return _enrich_dataframe_for_risk(out, metadata_map)


def load_holdings_for_market(
    market: str,
    base_dir: str | Path = ".",
    metadata_map: dict[str, dict[str, str]] | None = None,
) -> pd.DataFrame:
    base = Path(base_dir)
    metadata_map = metadata_map if metadata_map is not None else build_sector_metadata_map(base_dir)
    paths = HOLDINGS_PATHS.get(market, [])
    for rel in paths:
        path = base / rel
        if not path.exists() or path.stat().st_size <= 0:
            continue
        try:
            df = pd.read_csv(path, dtype=str).fillna("")
            return normalize_holdings_df(df, market, metadata_map)
        except Exception:
            continue
    return normalize_holdings_df(pd.DataFrame(), market, metadata_map)


def load_all_holdings(
    base_dir: str | Path = ".",
    metadata_map: dict[str, dict[str, str]] | None = None,
) -> pd.DataFrame:
    metadata_map = metadata_map if metadata_map is not None else build_sector_metadata_map(base_dir)
    frames = [load_holdings_for_market("미국주식", base_dir, metadata_map), load_holdings_for_market("한국주식", base_dir, metadata_map)]
    frames = [df for df in frames if df is not None and not df.empty]
    if not frames:
        return normalize_holdings_df(pd.DataFrame(), metadata_map=metadata_map)
    return pd.concat(frames, ignore_index=True, sort=False)


def _read_candidate_files(candidate_files: list[str | Path] | None = None, base_dir: str | Path = ".") -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in candidate_files or DEFAULT_CANDIDATE_FILES:
        p = _resolve_path(base_dir, path)
        if not p.exists() or p.stat().st_size <= 0:
            continue
        try:
            frames.append(pd.read_csv(p, dtype=str).fillna(""))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _risk_level(score: int) -> str:
    if score >= 80:
        return RISK_VERY_HIGH
    if score >= 55:
        return RISK_HIGH
    if score >= 30:
        return RISK_NORMAL
    return RISK_LOW


def calculate_portfolio_risk(positions_df: pd.DataFrame, candidates_df: pd.DataFrame) -> dict[str, Any]:
    positions_df = positions_df if positions_df is not None else pd.DataFrame()
    candidates_df = candidates_df if candidates_df is not None else pd.DataFrame()
    metadata_map = build_sector_metadata_map(candidates_df=candidates_df)
    positions_df = _enrich_dataframe_for_risk(positions_df, metadata_map)
    candidates_df = _enrich_dataframe_for_risk(candidates_df, metadata_map)
    total_value = _positions_total_value(positions_df)
    position_rows = _position_rows(positions_df, "position", total_value, candidates=False)
    candidate_rows = _position_rows(candidates_df, "candidate", 0.0, candidates=True)

    warnings: list[str] = []
    actions: list[str] = []
    risk_score = 0

    forbidden_candidates = [row for row in candidate_rows if row["forbidden"]]
    if forbidden_candidates:
        warnings.append(f"C/금지 후보 {len(forbidden_candidates)}개는 포트폴리오 편입 불가")
        actions.append("C/금지 후보는 신규 편입 목록에서 제외")
        risk_score += 20

    allowed_candidates = [row for row in candidate_rows if not row["forbidden"]]
    combined_rows = position_rows + allowed_candidates
    total_exposure = round(sum(row["exposure_pct"] for row in combined_rows), 4)
    candidate_exposure = sum(row["exposure_pct"] for row in allowed_candidates)

    if total_exposure > 100:
        warnings.append("총 포지션 노출 100% 초과")
        actions.append("신규 편입 축소 또는 기존 포지션 일부 정리")
        risk_score += 35
    elif total_exposure > 80:
        warnings.append("총 포지션 노출 80% 초과")
        actions.append("추가 편입 전 현금 비중 확인")
        risk_score += 18

    risk_market = any(
        row["strategy_mode"] == MODE_RISK
        or row["market_risk_level"] == RISK_VERY_HIGH
        or row["new_buy_blocked"]
        for row in candidate_rows
    )
    if risk_market and candidate_exposure > 0:
        warnings.append("위험장 총 신규 포지션 제한 필요")
        actions.append("위험장에서는 신규 포지션을 최소화")
        risk_score += 30

    sector_map: dict[str, dict[str, Any]] = {}
    for row in combined_rows:
        sector = row["sector"] or UNCLASSIFIED_SECTOR
        sector_map.setdefault(sector, {"count": 0, "exposure_pct": 0.0, "symbols": []})
        if row["exposure_pct"] > 0 or row["symbol"]:
            sector_map[sector]["count"] += 1
        sector_map[sector]["exposure_pct"] += row["exposure_pct"]
        if row["symbol"]:
            sector_map[sector]["symbols"].append(row["symbol"])
    sector_concentration = {
        sector: {
            "count": int(data["count"]),
            "exposure_pct": round(float(data["exposure_pct"]), 4),
            "symbols": list(dict.fromkeys(data["symbols"])),
        }
        for sector, data in sector_map.items()
    }
    for sector, data in sector_concentration.items():
        if data["count"] >= 3 or data["exposure_pct"] >= 40:
            warnings.append(f"{sector} 섹터 과집중")
            actions.append(f"{sector} 섹터 신규 편입 제한")
            risk_score += 25 if data["exposure_pct"] >= 40 else 15

    max_loss = 0.0
    expected_return = 0.0
    for row in combined_rows:
        exposure = row["exposure_pct"]
        if exposure > 0:
            max_loss += exposure * (_row_loss_pct(row, risk_market) / 100)
        if exposure > 0:
            expected_return += exposure * row["expected_return_5d"] / 100
    max_loss = round(max_loss, 4)
    expected_return = round(expected_return, 4)
    if max_loss >= 6:
        warnings.append("예상 최대 손실 6% 이상")
        actions.append("손절 기준 재점검 및 포지션 축소")
        risk_score += 20
    if expected_return < 0:
        warnings.append("포트폴리오 기대값 음수")
        actions.append("기대값 낮은 후보 제외")
        risk_score += 15

    if not warnings:
        warnings.append("포트폴리오 위험 특이사항 없음")
    if not actions:
        actions.append("현재 노출 유지 가능, 신규 편입은 후보별 리스크 확인")

    return {
        "portfolio_risk_level": _risk_level(risk_score),
        "total_exposure_pct": total_exposure,
        "sector_concentration": sector_concentration,
        "max_expected_loss_pct": max_loss,
        "portfolio_expected_return": expected_return,
        "market_exposure_level": "과다" if total_exposure > 100 else ("높음" if total_exposure > 80 else ("보통" if total_exposure > 40 else "낮음")),
        "risk_mode": bool(risk_market),
        "position_count": int(len(position_rows)),
        "blocked_candidate_count": int(len(forbidden_candidates)),
        "portfolio_warnings": list(dict.fromkeys(warnings)),
        "portfolio_actions": list(dict.fromkeys(actions)),
    }


def build_portfolio_risk_summary(
    positions_df: pd.DataFrame | None = None,
    candidates_df: pd.DataFrame | None = None,
    base_dir: str | Path = ".",
    candidate_files: list[str | Path] | None = None,
) -> dict[str, Any]:
    candidates = candidates_df if candidates_df is not None else _read_candidate_files(candidate_files, base_dir)
    metadata_map = build_sector_metadata_map(base_dir, candidates, candidate_files)
    positions = positions_df if positions_df is not None else load_all_holdings(base_dir, metadata_map)
    positions = _enrich_dataframe_for_risk(positions, metadata_map)
    candidates = _enrich_dataframe_for_risk(candidates, metadata_map)
    if positions is None or positions.empty:
        blocked = int(len([row for row in _position_rows(candidates, "candidate", candidates=True) if row["forbidden"]])) if candidates is not None and not candidates.empty else 0
        return {
            "portfolio_risk_level": "포트폴리오 없음",
            "total_exposure_pct": 0.0,
            "sector_concentration": {},
            "max_expected_loss_pct": 0.0,
            "portfolio_expected_return": 0.0,
            "market_exposure_level": "없음",
            "risk_mode": False,
            "position_count": 0,
            "blocked_candidate_count": blocked,
            "portfolio_warnings": ["등록된 보유 포트폴리오 없음"],
            "portfolio_actions": ["holdings_us.csv 또는 data/holdings_kr.csv에 보유종목 등록"],
            "updated_at": _now(),
        }
    summary = calculate_portfolio_risk(positions, candidates)
    summary["updated_at"] = _now()
    return summary


def save_portfolio_risk_summary(
    path: str | Path = PORTFOLIO_RISK_SUMMARY_JSON,
    positions_df: pd.DataFrame | None = None,
    candidates_df: pd.DataFrame | None = None,
    base_dir: str | Path = ".",
    candidate_files: list[str | Path] | None = None,
) -> dict[str, Any]:
    summary = build_portfolio_risk_summary(positions_df, candidates_df, base_dir, candidate_files)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def _sector_warning(summary: dict[str, Any]) -> str:
    sector_map = summary.get("sector_concentration") or {}
    warnings: list[str] = []
    for sector, data in sector_map.items():
        count = int(data.get("count", 0) or 0)
        exposure = _safe_float(data.get("exposure_pct"), 0)
        if count >= 3 or exposure >= 40:
            warnings.append(f"{sector}: {count}개/{exposure:g}%")
    return " / ".join(warnings) if warnings else "섹터 과집중 특이사항 없음"


def apply_portfolio_risk_to_candidates(candidate_df: pd.DataFrame, summary: dict[str, Any]) -> pd.DataFrame:
    out = candidate_df.copy() if candidate_df is not None else pd.DataFrame()
    defaults = {
        "portfolio_risk_level": summary.get("portfolio_risk_level", ""),
        "total_exposure_pct": summary.get("total_exposure_pct", 0.0),
        "sector_concentration_warning": _sector_warning(summary),
        "portfolio_expected_return": summary.get("portfolio_expected_return", 0.0),
        "max_expected_loss_pct": summary.get("max_expected_loss_pct", 0.0),
        "portfolio_action": " / ".join(map(str, summary.get("portfolio_actions") or [])) or "포트폴리오 조치 없음",
        "portfolio_warnings": " / ".join(map(str, summary.get("portfolio_warnings") or [])) or "포트폴리오 경고 없음",
    }
    for col, value in defaults.items():
        out[col] = value
    return out


def backfill_portfolio_risk_candidate_files(
    candidate_files: list[str | Path] | None = None,
    summary_path: str | Path = PORTFOLIO_RISK_SUMMARY_JSON,
    base_dir: str | Path = ".",
) -> dict[str, Any]:
    files = [Path(p) for p in (candidate_files or DEFAULT_CANDIDATE_FILES)]
    # Do not create a stale root-level no-portfolio summary when the backfill is
    # only being used to guarantee candidate CSV schema. Real holdings summaries
    # are still saved when positions exist or an explicit output path/base_dir is
    # provided by the caller.
    summary = build_portfolio_risk_summary(base_dir=base_dir, candidate_files=files)
    should_write_summary = not (
        Path(summary_path) == PORTFOLIO_RISK_SUMMARY_JSON
        and str(base_dir) in {".", ""}
        and summary.get("portfolio_risk_level") == "포트폴리오 없음"
    )
    if should_write_summary:
        target = Path(summary_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    result: dict[str, Any] = {"summary_path": str(summary_path), "updated_files": [], "errors": {}}
    for path in files:
        try:
            if path.exists() and path.stat().st_size > 0:
                df = pd.read_csv(path, dtype=str).fillna("")
            else:
                df = pd.DataFrame()
            out = apply_portfolio_risk_to_candidates(df, summary)
            path.parent.mkdir(parents=True, exist_ok=True)
            out.to_csv(path, index=False, encoding="utf-8-sig")
            result["updated_files"].append(str(path))
        except Exception as exc:
            result["errors"][str(path)] = str(exc)
    return result


def main() -> None:
    result = backfill_portfolio_risk_candidate_files()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
