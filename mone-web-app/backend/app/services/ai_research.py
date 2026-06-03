"""
MONE AI 리서치 서비스
- 투자장부 분석 (journal_summary)
- 뉴스 영향도 태그 (news_tag)
- 밸류에이션 비교 (valuation_compare)
- 유사 조건 패턴 (pattern_match)
- 고급 종목 스크리너 (screener)
"""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ── 경로 설정 (data_loader.py 와 동일 패턴) ─────────────────────
import os
APP_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("MONE_REPO_ROOT", APP_DIR.parent)).resolve()
REPORT_DIR = REPO_ROOT / "reports"

_MARKETS = ["kr", "us"]
_MODES = ["conservative", "balanced", "aggressive"]
_HORIZONS = ["short", "swing", "mid"]
_MODE_KO = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
_HORIZON_KO = {"short": "단기", "swing": "스윙", "mid": "중기"}
_MARKET_KO = {"kr": "국장", "us": "미장"}

_TV_PATTERN = "mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv"
_REC_PATTERN = "mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"

# ── 공통 헬퍼 ─────────────────────────────────────────────────

def _sf(v: Any, default: float = float("nan")) -> float:
    try:
        if v is None:
            return default
        s = str(v).strip()
        if s in {"", "nan", "None", "-", "False", "True", "확인 필요"}:
            return default
        return float(s.replace(",", "").replace("%", "").replace("원", "").replace("배", ""))
    except Exception:
        return default

def _ss(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in {"nan", "none", "null"} else s

def _read(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except Exception:
            continue
    return pd.DataFrame()

def _load_current() -> pd.DataFrame:
    """날짜 스냅샷 제외 현재 CSV 로드. trade_validation 우선, 없으면 recommendations 사용."""
    frames: list[pd.DataFrame] = []
    for market in _MARKETS:
        for mode in _MODES:
            for horizon in _HORIZONS:
                # trade_validation 먼저, 없거나 비어있으면 recommendations 시도
                for pattern in (_TV_PATTERN, _REC_PATTERN):
                    path = REPORT_DIR / pattern.format(market=market, mode=mode, horizon=horizon)
                    df = _read(path)
                    if not df.empty:
                        df["_market"] = market
                        df["_mode"] = mode
                        df["_horizon"] = horizon
                        frames.append(df)
                        break  # 데이터 있으면 다음 패턴 시도 불필요
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False).fillna("")

def _load_all_snapshots() -> pd.DataFrame:
    """날짜 스냅샷 포함 전체 CSV 로드 (패턴 매칭용)."""
    frames: list[pd.DataFrame] = []
    for path in sorted(REPORT_DIR.glob("mone_v36_final_trade_validation_*.csv")):
        parts = path.stem.replace("mone_v36_final_trade_validation_", "").split("_")
        if len(parts) < 3:
            continue
        market, mode, horizon = parts[0], parts[1], parts[2]
        snapshot = parts[3] if len(parts) >= 4 else "latest"
        df = _read(path)
        if df.empty:
            continue
        df["_market"] = market
        df["_mode"] = mode
        df["_horizon"] = horizon
        df["_snapshot"] = snapshot
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False).fillna("")

def _nan_safe(v: Any) -> Any:
    """JSON 직렬화 불가 NaN/Inf 제거."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v

# ═══════════════════════════════════════════════════════════
# 1. 투자장부 분석
# ═══════════════════════════════════════════════════════════

def journal_summary() -> dict[str, Any]:
    """전략별 추천 현황, 섹터/태그 분포, 패턴 진단."""
    df = _load_current()
    if df.empty:
        return {"ok": False, "error": "trade_validation 데이터 없음", "strategy_grid": [], "sectors": [], "tags": [], "patterns": {}}

    # 전략 그리드
    grid = []
    for market in _MARKETS:
        for mode in _MODES:
            for horizon in _HORIZONS:
                sub = df[(df["_market"] == market) & (df["_mode"] == mode) & (df["_horizon"] == horizon)]
                if sub.empty:
                    continue
                total = len(sub)
                normal = int((sub.get("dataStatus", pd.Series(dtype=str)).apply(_ss) == "NORMAL").sum()) if "dataStatus" in sub.columns else 0
                priority = int(sub["decisionBucket"].apply(_ss).str.contains("우선", na=False).sum()) if "decisionBucket" in sub.columns else 0
                watch = int(sub["decisionBucket"].apply(_ss).str.contains("대기", na=False).sum()) if "decisionBucket" in sub.columns else 0
                avg_score = _nan_safe(sub["finalScore"].apply(_sf).replace(0.0, float("nan")).mean()) if "finalScore" in sub.columns else None
                uv = int((sub["isUndervaluedGrowth"].apply(_ss) == "True").sum()) if "isUndervaluedGrowth" in sub.columns else 0
                grid.append({
                    "market": _MARKET_KO[market],
                    "mode": _MODE_KO[mode],
                    "horizon": _HORIZON_KO[horizon],
                    "total": total,
                    "normal": normal,
                    "priority": priority,
                    "watch": watch,
                    "avgScore": round(avg_score, 1) if avg_score is not None else None,
                    "undervalued": uv,
                })

    # 섹터 분포
    sectors = []
    if "sector" in df.columns:
        df2 = df.copy()
        df2["_sec"] = df2["sector"].apply(_ss).replace("", "미분류")
        df2["_score"] = df2["finalScore"].apply(_sf) if "finalScore" in df2.columns else 0.0
        for sec, grp in df2.groupby("_sec"):
            avg = _nan_safe(grp["_score"].replace(0.0, float("nan")).mean())
            sectors.append({"sector": sec, "count": len(grp), "avgScore": round(avg, 1) if avg else None})
        sectors.sort(key=lambda x: x["count"], reverse=True)

    # surgeLabel 태그 분포
    tags = []
    if "surgeLabel" in df.columns:
        all_tags: list[str] = []
        for val in df["surgeLabel"].apply(_ss):
            for t in val.split("|"):
                t = t.strip()
                if t:
                    all_tags.append(t)
        counts = Counter(all_tags)
        tags = [{"tag": k, "count": v} for k, v in counts.most_common(15)]

    # 패턴 진단
    total = len(df)
    patterns: dict[str, Any] = {}
    if "timingLabel" in df.columns:
        timing = df["timingLabel"].apply(_ss)
        patterns["chasingCount"] = int(timing.str.contains("과열", na=False).sum())
        patterns["pullbackCount"] = int(timing.str.contains("눌림", na=False).sum())
        patterns["chasingPct"] = round(patterns["chasingCount"] / total * 100, 1) if total else 0
    if "rrActual" in df.columns:
        rr = df["rrActual"].apply(_sf)
        valid = rr[rr > 0]
        patterns["lowRrCount"] = int((valid < 1.5).sum())
        patterns["avgRr"] = _nan_safe(round(float(valid.mean()), 2)) if len(valid) else None
    if "dataStatus" in df.columns:
        patterns["statusDist"] = df["dataStatus"].value_counts().to_dict()
        patterns["normalPct"] = round(patterns["statusDist"].get("NORMAL", 0) / total * 100, 1) if total else 0

    # decisionBucket 분포
    bucket_dist = {}
    if "decisionBucket" in df.columns:
        bucket_dist = df["decisionBucket"].apply(_ss).replace("", "미분류").value_counts().to_dict()

    total_rows = len(df)
    kr_cnt = int((df["_market"] == "kr").sum())
    us_cnt = int((df["_market"] == "us").sum())

    return {
        "ok": True,
        "totalRows": total_rows,
        "krCount": kr_cnt,
        "usCount": us_cnt,
        "strategy_grid": grid,
        "sectors": sectors[:15],
        "tags": tags,
        "patterns": patterns,
        "bucketDist": bucket_dist,
    }


# ═══════════════════════════════════════════════════════════
# 2. 뉴스 영향도 태그
# ═══════════════════════════════════════════════════════════

_BULLISH = [
    "수주", "계약 체결", "계약체결", "신규 수주", "실적 호조", "어닝 서프라이즈",
    "매출 증가", "영업이익 증가", "자사주 매입", "배당 증가", "배당 확대", "특별 배당",
    "기술이전", "기술 수출", "FDA 승인", "임상 성공", "특허 취득", "허가",
    "흑자 전환", "흑자전환", "적자 축소", "턴어라운드",
    "목표가 상향", "투자의견 매수", "매수 의견",
    "수출 증가", "해외 수주", "MOU", "파트너십", "전략적 제휴",
    "증설", "신공장", "수주잔고",
]
_BEARISH = [
    "유상증자", "제3자배정", "CB 발행", "BW 발행", "전환사채",
    "횡령", "배임", "사기", "주가조작", "불공정거래",
    "소송", "법적 분쟁", "손해배상", "영업정지", "거래정지", "상장폐지", "관리종목",
    "적자", "영업손실", "당기순손실", "어닝 쇼크",
    "임직원 매도", "대주주 매도", "지분 처분",
    "규제 강화", "세무조사", "공정거래 제재",
    "목표가 하향", "투자의견 하향", "매도 의견",
    "계약 해지", "수주 취소", "부채 증가", "자본잠식",
    "화재", "리콜", "사고",
]
_CAUTION_PATTERNS = [
    "유상증자", "CB 발행", "BW 발행", "횡령", "배임", "소송",
    "영업정지", "상장폐지", "관리종목", "주가조작",
]
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("실적", ["실적", "어닝", "EPS", "매출", "영업이익", "흑자", "적자", "분기"]),
    ("공시", ["공시", "증자", "CB", "BW", "자사주", "배당", "주요사항"]),
    ("수급", ["외국인", "기관", "프로그램 매매", "순매수", "순매도", "수급"]),
    ("규제", ["규제", "소송", "조사", "제재", "금지", "과징금", "금감원"]),
    ("시장", ["FOMC", "금리", "달러", "물가", "CPI", "PPI", "연준", "Fed"]),
    ("섹터이슈", ["반도체", "AI", "배터리", "전기차", "바이오", "방산", "로봇"]),
]

def _count_kw(text: str, keywords: list[str]) -> int:
    tl = text.lower()
    return sum(1 for kw in keywords if kw.lower() in tl)

def news_tag(title: str, snippet: str = "") -> dict[str, Any]:
    """뉴스 제목+본문 → 호재/악재/중립 태그."""
    combined = f"{title} {snippet}"
    bull = _count_kw(combined, _BULLISH)
    bear = _count_kw(combined, _BEARISH)
    total = bull + bear
    if total == 0:
        sentiment, confidence = "중립", 40
    elif bull > bear:
        sentiment, confidence = "호재", min(95, 50 + bull * 12)
    elif bear > bull:
        sentiment, confidence = "악재", min(95, 50 + bear * 12)
    else:
        sentiment, confidence = "중립", 45

    categories = [cat for cat, kws in _CATEGORY_RULES if _count_kw(combined, kws) > 0]
    caution_reasons = [p for p in _CAUTION_PATTERNS if p.lower() in combined.lower()]
    is_caution = len(caution_reasons) > 0

    risk_penalty = -10 if (is_caution or bear >= 3) else (-5 if sentiment == "악재" else 0)
    confidence_adj = 10 if sentiment == "호재" and confidence >= 70 else 0

    return {
        "sentiment": sentiment,
        "confidence": confidence,
        "categories": categories,
        "isСaution": is_caution,
        "cautionReasons": caution_reasons,
        "bullishScore": bull,
        "bearishScore": bear,
        "riskPenalty": risk_penalty,
        "confidenceAdj": confidence_adj,
    }

def news_tag_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """뉴스 아이템 리스트에 태그 일괄 적용."""
    results = []
    for item in items:
        title = str(item.get("title") or item.get("headline") or "")
        snippet = str(item.get("summary") or item.get("content") or item.get("description") or "")
        tag = news_tag(title, snippet)
        merged = dict(item)
        merged["impact"] = tag
        results.append(merged)
    return results


# ═══════════════════════════════════════════════════════════
# 3. 밸류에이션 비교
# ═══════════════════════════════════════════════════════════

_FIN_COLS = ["per", "pbr", "roe", "operatingMargin", "debtRatio", "revenueGrowth", "epsGrowth"]
_FIN_LABELS = {
    "per": "PER", "pbr": "PBR", "roe": "ROE (%)",
    "operatingMargin": "영업이익률 (%)", "debtRatio": "부채비율 (%)",
    "revenueGrowth": "매출 성장률 (%)", "epsGrowth": "EPS 성장률 (%)",
}
_LOWER_BETTER = {"per", "pbr", "debtRatio"}
_HIGHER_BETTER = {"roe", "operatingMargin", "revenueGrowth", "epsGrowth"}

def _sector_averages(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """섹터별 재무 지표 중앙값 계산."""
    result: dict[str, dict[str, float]] = {}
    if "sector" not in df.columns:
        return result
    df2 = df.copy()
    df2["_sec"] = df2["sector"].apply(_ss).replace("", "미분류")
    for col in _FIN_COLS:
        if col in df2.columns:
            df2[col] = df2[col].apply(_sf)
    for sec, grp in df2.groupby("_sec"):
        result[sec] = {}
        for col in _FIN_COLS:
            if col in grp.columns:
                vals = grp[col].dropna()
                vals = vals[vals > -9999]
                result[sec][col] = _nan_safe(float(vals.median())) if len(vals) else None
    return result

def valuation_compare(symbol: str, market: str = "kr") -> dict[str, Any]:
    """종목 밸류에이션 vs 섹터 중앙값 비교."""
    df = _load_current()
    if df.empty:
        return {"ok": False, "error": "데이터 없음"}

    # 종목 찾기
    sym_up = symbol.upper().strip()
    sym_rows = df[df.get("symbol", pd.Series(dtype=str)).apply(lambda x: str(x).upper().strip()) == sym_up]
    if sym_rows.empty and "name" in df.columns:
        sym_rows = df[df["name"].apply(_ss).str.contains(symbol, case=False, na=False)]
    if sym_rows.empty:
        return {"ok": False, "symbol": symbol, "error": "유니버스에 없는 종목"}

    row = sym_rows.iloc[0]
    name = _ss(row.get("name", symbol))
    sector = _ss(row.get("sector", "")) or "미분류"

    # 섹터 평균
    avgs = _sector_averages(df)
    sec_avg = avgs.get(sector, {})

    metrics = []
    undervalued_signals: list[str] = []
    growth_signals: list[str] = []

    for col in _FIN_COLS:
        label = _FIN_LABELS[col]
        sym_val = _sf(row.get(col, float("nan")))
        sec_val = sec_avg.get(col)

        verdict = "데이터 없음"
        if not math.isnan(sym_val) and sec_val is not None and sec_val != 0:
            ratio = sym_val / sec_val
            if col in _LOWER_BETTER:
                if ratio < 0.8:
                    verdict = "섹터 대비 낮음 (우호)"
                    if col == "per":
                        undervalued_signals.append(f"PER {sym_val:.1f} < 섹터 {sec_val:.1f}")
                    if col == "pbr":
                        undervalued_signals.append(f"PBR {sym_val:.1f} < 섹터 {sec_val:.1f}")
                elif ratio > 1.2:
                    verdict = "섹터 대비 높음 (부담)"
                else:
                    verdict = "섹터 평균 수준"
            elif col in _HIGHER_BETTER:
                if ratio > 1.2:
                    verdict = "섹터 대비 높음 (우호)"
                    if col == "roe":
                        undervalued_signals.append(f"ROE {sym_val:.1f}% > 섹터 {sec_val:.1f}%")
                    if col in {"revenueGrowth", "epsGrowth"}:
                        growth_signals.append(f"{label} {sym_val:.1f}% > 섹터 {sec_val:.1f}%")
                elif ratio < 0.8:
                    verdict = "섹터 대비 낮음 (부담)"
                else:
                    verdict = "섹터 평균 수준"
        elif not math.isnan(sym_val):
            verdict = "섹터 비교 데이터 없음"

        metrics.append({
            "label": label,
            "symbolValue": _nan_safe(sym_val),
            "sectorMedian": _nan_safe(sec_val),
            "verdict": verdict,
        })

    uv = len(undervalued_signals)
    gr = len(growth_signals)
    if uv >= 2 and gr >= 1:
        verdict_overall = "저평가 성장주 가능성 높음"
    elif uv >= 1 and gr >= 1:
        verdict_overall = "저평가 성장주 후보"
    elif uv >= 2:
        verdict_overall = "저평가 (성장성 확인 필요)"
    elif gr >= 2:
        verdict_overall = "성장주 (밸류에이션 확인 필요)"
    else:
        verdict_overall = "판단 보류 (데이터 부족 또는 평균 수준)"

    return {
        "ok": True,
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "metrics": metrics,
        "undervaluedSignals": undervalued_signals,
        "growthSignals": growth_signals,
        "verdictOverall": verdict_overall,
        "sectorAverages": {k: _nan_safe(v) for k, v in sec_avg.items()},
    }


# ═══════════════════════════════════════════════════════════
# 4. 유사 조건 패턴
# ═══════════════════════════════════════════════════════════

def pattern_match(
    market: str = "",
    mode: str = "",
    horizon: str = "",
    surge_tag: str = "",
    timing: str = "",
    decision_bucket: str = "",
    sector: str = "",
    min_score: float = 0.0,
) -> dict[str, Any]:
    """조건 기반 유사 이력 분포 분석."""
    df = _load_all_snapshots()
    if df.empty:
        return {"ok": False, "error": "이력 데이터 없음", "total": 0}

    sub = df.copy()
    if market:
        sub = sub[sub["_market"].apply(_ss) == market]
    if mode:
        sub = sub[sub["_mode"].apply(_ss) == mode]
    if horizon:
        sub = sub[sub["_horizon"].apply(_ss) == horizon]
    if surge_tag and "surgeLabel" in sub.columns:
        sub = sub[sub["surgeLabel"].apply(_ss).str.contains(surge_tag, case=False, na=False)]
    if timing and "timingLabel" in sub.columns:
        sub = sub[sub["timingLabel"].apply(_ss).str.contains(timing, case=False, na=False)]
    if decision_bucket and "decisionBucket" in sub.columns:
        sub = sub[sub["decisionBucket"].apply(_ss).str.contains(decision_bucket, case=False, na=False)]
    if sector and "sector" in sub.columns:
        sub = sub[sub["sector"].apply(_ss).str.contains(sector, case=False, na=False)]
    if min_score > 0 and "finalScore" in sub.columns:
        scores = sub["finalScore"].apply(_sf)
        sub = sub[scores.isna() | (scores >= min_score)]

    total = len(sub)
    if total == 0:
        return {"ok": True, "total": 0, "message": "조건에 맞는 이력 없음"}

    result: dict[str, Any] = {"ok": True, "total": total}

    if "finalScore" in sub.columns:
        scores = sub["finalScore"].apply(_sf).replace(0.0, float("nan"))
        result["scoreMean"] = _nan_safe(round(float(scores.mean()), 1)) if scores.notna().any() else None
        result["scoreP25"] = _nan_safe(round(float(scores.quantile(0.25)), 1)) if scores.notna().any() else None
        result["scoreP75"] = _nan_safe(round(float(scores.quantile(0.75)), 1)) if scores.notna().any() else None

    if "probability" in sub.columns:
        probs = sub["probability"].apply(_sf).replace(0.0, float("nan"))
        result["probMean"] = _nan_safe(round(float(probs.mean()), 1)) if probs.notna().any() else None

    if "rrActual" in sub.columns:
        rr = sub["rrActual"].apply(_sf).replace(0.0, float("nan"))
        result["rrMean"] = _nan_safe(round(float(rr.mean()), 2)) if rr.notna().any() else None

    if "decisionBucket" in sub.columns:
        result["bucketDist"] = sub["decisionBucket"].apply(_ss).replace("", "미분류").value_counts().to_dict()

    if "dataStatus" in sub.columns:
        result["statusDist"] = sub["dataStatus"].value_counts().to_dict()

    if "_market" in sub.columns:
        result["marketDist"] = {_MARKET_KO.get(k, k): int(v) for k, v in sub["_market"].value_counts().items()}
    if "_mode" in sub.columns:
        result["modeDist"] = {_MODE_KO.get(k, k): int(v) for k, v in sub["_mode"].value_counts().items()}
    if "_horizon" in sub.columns:
        result["horizonDist"] = {_HORIZON_KO.get(k, k): int(v) for k, v in sub["_horizon"].value_counts().items()}

    if "sector" in sub.columns:
        result["topSectors"] = [
            {"sector": k, "count": int(v)}
            for k, v in sub["sector"].apply(_ss).replace("", "미분류").value_counts().head(8).items()
        ]

    if "surgeLabel" in sub.columns:
        all_tags: list[str] = []
        for val in sub["surgeLabel"].apply(_ss):
            for t in val.split("|"):
                t = t.strip()
                if t:
                    all_tags.append(t)
        counts = Counter(all_tags)
        result["topTags"] = [{"tag": k, "count": int(v)} for k, v in counts.most_common(10)]

    # 샘플 (최대 20건)
    display_cols = [c for c in ["_snapshot", "symbol", "name", "sector", "_mode", "_horizon",
                                 "decisionBucket", "finalScore", "probability", "surgeLabel", "dataStatus"]
                    if c in sub.columns]
    result["samples"] = sub[display_cols].head(20).to_dict(orient="records")

    return result


# ═══════════════════════════════════════════════════════════
# 5. 고급 종목 스크리너
# ═══════════════════════════════════════════════════════════

def screener(
    market: str = "",
    mode: str = "",
    horizon: str = "",
    decision_bucket: str = "",
    data_status: str = "",
    sector: str = "",
    surge_tag: str = "",
    only_normal: bool = False,
    only_undervalued: bool = False,
    only_priority: bool = False,
    min_score: float = 0.0,
    max_score: float = 100.0,
    min_rr: float = 0.0,
    max_per: float = 9999.0,
    min_roe: float = -9999.0,
    sort_by: str = "finalScore",
    limit: int = 50,
) -> dict[str, Any]:
    """다중 필터 종목 스크리너."""
    df = _load_current()
    if df.empty:
        return {"ok": False, "error": "데이터 없음", "items": [], "total": 0}

    sub = df.copy()

    if market:
        sub = sub[sub["_market"] == market]
    if mode:
        sub = sub[sub["_mode"] == mode]
    if horizon:
        sub = sub[sub["_horizon"] == horizon]
    if decision_bucket and "decisionBucket" in sub.columns:
        sub = sub[sub["decisionBucket"].apply(_ss).str.contains(decision_bucket, case=False, na=False)]
    if data_status and "dataStatus" in sub.columns:
        sub = sub[sub["dataStatus"].apply(_ss) == data_status]
    if only_normal and "dataStatus" in sub.columns:
        sub = sub[sub["dataStatus"].apply(_ss) == "NORMAL"]
    if sector and "sector" in sub.columns:
        sub = sub[sub["sector"].apply(_ss).str.contains(sector, case=False, na=False)]
    if surge_tag and "surgeLabel" in sub.columns:
        sub = sub[sub["surgeLabel"].apply(_ss).str.contains(surge_tag, case=False, na=False)]
    if only_undervalued and "isUndervaluedGrowth" in sub.columns:
        sub = sub[sub["isUndervaluedGrowth"].apply(_ss) == "True"]
    if only_priority and "decisionBucket" in sub.columns:
        sub = sub[sub["decisionBucket"].apply(_ss).str.contains("우선", na=False)]

    if min_score > 0 or max_score < 100:
        if "finalScore" in sub.columns:
            scores = sub["finalScore"].apply(_sf)
            sub = sub[scores.isna() | ((scores >= min_score) & (scores <= max_score))]
    if min_rr > 0 and "rrActual" in sub.columns:
        rr = sub["rrActual"].apply(_sf)
        sub = sub[rr.isna() | (rr >= min_rr)]
    if max_per < 9999 and "per" in sub.columns:
        per = sub["per"].apply(_sf)
        sub = sub[per.isna() | ((per > 0) & (per <= max_per))]
    if min_roe > -9999 and "roe" in sub.columns:
        roe = sub["roe"].apply(_sf)
        sub = sub[roe.isna() | (roe >= min_roe)]

    # 정렬
    if sort_by in sub.columns:
        ascending = sort_by == "per"
        sub["_sort"] = sub[sort_by].apply(_sf)
        sub = sub.sort_values("_sort", ascending=ascending, na_position="last").drop(columns=["_sort"])

    total = len(sub)
    items_raw = sub.head(limit)

    def _fmt_price(v: Any, mkt: str) -> str:
        f = _sf(v)
        if math.isnan(f) or f == 0:
            return "-"
        if mkt == "kr":
            return f"{f:,.0f}원"
        return f"${f:.2f}"

    def _fmt_pct(v: Any) -> str:
        f = _sf(v)
        return f"{f:.1f}%" if not math.isnan(f) and f != 0 else "-"

    def _fmt_v(v: Any, d: int = 1) -> str:
        f = _sf(v)
        return f"{f:.{d}f}" if not math.isnan(f) and f != 0 else "-"

    items = []
    for _, row in items_raw.iterrows():
        mkt = _ss(row.get("_market", ""))
        items.append({
            "market": _MARKET_KO.get(mkt, mkt),
            "symbol": _ss(row.get("symbol", "")),
            "name": _ss(row.get("name", "")),
            "sector": _ss(row.get("sector", "")) or "-",
            "mode": _MODE_KO.get(_ss(row.get("_mode", "")), "-"),
            "horizon": _HORIZON_KO.get(_ss(row.get("_horizon", "")), "-"),
            "decisionBucket": _ss(row.get("decisionBucket", "")) or "-",
            "timingLabel": _ss(row.get("timingLabel", "")) or "-",
            "entry": _fmt_price(row.get("entry"), mkt),
            "stop": _fmt_price(row.get("stop"), mkt),
            "target": _fmt_price(row.get("target"), mkt),
            "probability": _fmt_pct(row.get("probability")),
            "finalScore": _fmt_v(row.get("finalScore")),
            "rrActual": _fmt_v(row.get("rrActual"), 2),
            "surgeLabel": _ss(row.get("surgeLabel", "")) or "-",
            "isUndervalued": _ss(row.get("isUndervaluedGrowth", "")) == "True",
            "dataStatus": _ss(row.get("dataStatus", "")) or "-",
            "per": _fmt_v(row.get("per")),
            "pbr": _fmt_v(row.get("pbr")),
            "roe": _fmt_pct(row.get("roe")),
        })

    # 요약
    summary = {
        "total": total,
        "shown": len(items),
        "undervalued": int((items_raw.get("isUndervaluedGrowth", pd.Series(dtype=str)).apply(_ss) == "True").sum()) if "isUndervaluedGrowth" in items_raw.columns else 0,
        "priority": int(items_raw.get("decisionBucket", pd.Series(dtype=str)).apply(_ss).str.contains("우선", na=False).sum()) if "decisionBucket" in items_raw.columns else 0,
        "normal": int((items_raw.get("dataStatus", pd.Series(dtype=str)).apply(_ss) == "NORMAL").sum()) if "dataStatus" in items_raw.columns else 0,
    }

    # 필터 옵션 (전체 유니버스 기준)
    all_df = _load_current()
    opts = {
        "sectors": sorted({_ss(v) for v in all_df.get("sector", pd.Series(dtype=str)) if _ss(v)}),
        "surgeTags": [],
    }
    if "surgeLabel" in all_df.columns:
        all_tags: list[str] = []
        for val in all_df["surgeLabel"].apply(_ss):
            for t in val.split("|"):
                t = t.strip()
                if t:
                    all_tags.append(t)
        opts["surgeTags"] = [k for k, _ in Counter(all_tags).most_common(20)]

    return {"ok": True, "total": total, "summary": summary, "items": items, "filterOptions": opts}
