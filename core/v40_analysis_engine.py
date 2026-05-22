"""v40 local analysis engines.

These functions are intentionally UI-independent so the same logic can later be
served through FastAPI/Next.js without rewriting the calculation layer.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPORT_DIR = Path("reports")
DATA_DIR = Path("data")
V40_SUMMARY_JSON = REPORT_DIR / "v40_analysis_summary.json"
V40_VALUATION_CSV = REPORT_DIR / "v40_valuation_kpi_summary.csv"
V40_MACRO_CSV = REPORT_DIR / "v40_macro_regime_summary.csv"
V40_QUANT_CSV = REPORT_DIR / "v40_quant_backtest_summary.csv"
V40_MONTE_CARLO_CSV = REPORT_DIR / "v40_monte_carlo_summary.csv"
V40_OPTION_CSV = REPORT_DIR / "v40_option_pricing_sample.csv"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        if isinstance(value, str):
            text = value.replace(",", "").replace("%", "").replace("$", "").replace("원", "").strip()
            if text.lower() in {"", "nan", "none", "null", "-", "미수신"}:
                return default
            value = text
        return float(value)
    except Exception:
        return default


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None or pd.isna(value):
            return default
    except Exception:
        if value is None:
            return default
    text = str(value).strip()
    return default if text.lower() in {"", "nan", "none", "null", "nat"} else text


def _read_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _market_suffix(market: str) -> str:
    return "kr" if "한국" in str(market) or "국" in str(market) else "us"


def _candidate_paths(market: str) -> list[Path]:
    suffix = _market_suffix(market)
    return [
        REPORT_DIR / f"swing_candidates_{suffix}_A_top3.csv",
        REPORT_DIR / f"swing_candidates_{suffix}_B_watch.csv",
        REPORT_DIR / f"swing_candidates_{suffix}_C_excluded.csv",
    ]


def load_candidate_pool(market: str) -> pd.DataFrame:
    frames = []
    for p in _candidate_paths(market):
        df = _read_csv(p)
        if df.empty:
            continue
        df = df.copy()
        if "source_file" not in df.columns:
            df["source_file"] = p.name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False).fillna("")
    if "symbol" not in out.columns and "ticker" in out.columns:
        out["symbol"] = out["ticker"]
    if "name" not in out.columns and "종목명" in out.columns:
        out["name"] = out["종목명"]
    return out


def _first(row: pd.Series | dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for k in keys:
        if k in row:
            val = row.get(k) if isinstance(row, dict) else row[k]
            if _safe_str(val):
                return val
    return default


def _valuation_label(per: float, pbr: float, roe: float, growth: float) -> tuple[str, str, float]:
    score = 50.0
    reasons: list[str] = []
    if not math.isnan(per):
        if per <= 12:
            score += 14; reasons.append("PER 낮음")
        elif per >= 40:
            score -= 12; reasons.append("PER 부담")
    if not math.isnan(pbr):
        if pbr <= 1.2:
            score += 8; reasons.append("PBR 낮음")
        elif pbr >= 6:
            score -= 8; reasons.append("PBR 높음")
    if not math.isnan(roe):
        if roe >= 15:
            score += 12; reasons.append("ROE 우수")
        elif roe <= 3:
            score -= 10; reasons.append("ROE 약함")
    if not math.isnan(growth):
        if growth >= 10:
            score += 10; reasons.append("성장률 양호")
        elif growth < 0:
            score -= 10; reasons.append("역성장")
    score = max(0, min(100, score))
    if not reasons:
        return "데이터 필요", "PER/PBR/ROE/성장률 캐시 부족", score
    if score >= 72:
        return "우호", " / ".join(reasons), score
    if score <= 42:
        return "주의", " / ".join(reasons), score
    return "중립", " / ".join(reasons), score


def build_valuation_kpi_table(market: str = "미국주식", limit: int = 120) -> pd.DataFrame:
    candidates = load_candidate_pool(market)
    cached = _read_csv(REPORT_DIR / f"operational_financial_kpi_{_market_suffix(market)}.csv")
    if candidates.empty and not cached.empty:
        candidates = cached.copy()
    if candidates.empty:
        return pd.DataFrame(columns=["종목코드", "종목명", "가치평가", "가치점수", "핵심 KPI", "판단근거"])
    rows: list[dict[str, Any]] = []
    for _, row in candidates.head(limit).iterrows():
        symbol = _safe_str(_first(row, ["symbol", "ticker", "종목코드"]))
        name = _safe_str(_first(row, ["name", "종목명", "company_name"], symbol))
        per = _safe_float(_first(row, ["per", "PER", "trailing_pe", "forward_pe"]))
        pbr = _safe_float(_first(row, ["pbr", "PBR", "price_to_book"]))
        roe = _safe_float(_first(row, ["roe", "ROE", "return_on_equity"]))
        growth = _safe_float(_first(row, ["revenue_growth", "sales_growth", "growth_score", "매출성장률"]))
        debt = _safe_float(_first(row, ["debt_ratio", "부채비율"]))
        margin = _safe_float(_first(row, ["operating_margin", "net_margin", "영업이익률"]))
        label, reason, score = _valuation_label(per, pbr, roe, growth)
        kpis = []
        for label_name, val, suffix in [("PER", per, ""), ("PBR", pbr, ""), ("ROE", roe, "%"), ("성장", growth, "%"), ("부채", debt, "%"), ("마진", margin, "%")]:
            if not math.isnan(val):
                kpis.append(f"{label_name} {val:.2f}{suffix}")
        rows.append({
            "종목코드": symbol,
            "종목명": name,
            "시장": market,
            "가치평가": label,
            "가치점수": round(score, 1),
            "핵심 KPI": " · ".join(kpis) if kpis else "재무 캐시 필요",
            "판단근거": reason,
        })
    return pd.DataFrame(rows).drop_duplicates(subset=["종목코드"], keep="first")


def build_macro_regime_table(market: str = "미국주식") -> pd.DataFrame:
    suffix = _market_suffix(market)
    macro = _read_csv(REPORT_DIR / f"operational_macro_{suffix}.csv")
    api = _read_csv(REPORT_DIR / "api_data_status_center.csv")
    bench = _read_csv(DATA_DIR / "market" / "benchmark_daily.csv")
    rows: list[dict[str, Any]] = []
    if not macro.empty:
        for _, r in macro.head(30).iterrows():
            rows.append({
                "구분": _safe_str(_first(r, ["구분", "category", "항목"], "시장 국면")),
                "지표": _safe_str(_first(r, ["지표", "metric", "name"], "-")),
                "값": _safe_str(_first(r, ["값", "value", "score", "status"], "-")),
                "해석": _safe_str(_first(r, ["해석", "comment", "reason"], "-")),
                "출처": f"operational_macro_{suffix}.csv",
            })
    if not api.empty:
        stale = int(api.astype(str).apply(lambda col: col.str.contains("오래됨|없음|비어", regex=True, na=False)).any(axis=1).sum())
        rows.append({"구분": "데이터 상태", "지표": "확인 필요 데이터", "값": stale, "해석": "값이 크면 후보 판단 신뢰도를 낮춰야 함", "출처": "api_data_status_center.csv"})
    if not bench.empty:
        rows.append({"구분": "시장 기준", "지표": "benchmark 누적 rows", "값": len(bench), "해석": "benchmark_daily가 쌓일수록 베타/알파 신뢰도 상승", "출처": "data/market/benchmark_daily.csv"})
    if not rows:
        rows.append({"구분": "시장 국면", "지표": "상태", "값": "데이터 필요", "해석": "장중/벤치마크/거시 데이터가 쌓이면 시장 확신도 보정 가능", "출처": "local"})
    return pd.DataFrame(rows)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_price(S: float, K: float, r: float, sigma: float, T: float, option_type: str = "call", q: float = 0.0) -> dict[str, float]:
    S = max(float(S), 1e-9); K = max(float(K), 1e-9); sigma = max(float(sigma), 1e-9); T = max(float(T), 1e-9)
    r = float(r); q = float(q)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    disc_q = math.exp(-q * T)
    disc_r = math.exp(-r * T)
    if str(option_type).lower().startswith("p"):
        price = K * disc_r * norm_cdf(-d2) - S * disc_q * norm_cdf(-d1)
        delta = -disc_q * norm_cdf(-d1)
    else:
        price = S * disc_q * norm_cdf(d1) - K * disc_r * norm_cdf(d2)
        delta = disc_q * norm_cdf(d1)
    gamma = disc_q * math.exp(-0.5 * d1 * d1) / (S * sigma * math.sqrt(2 * math.pi * T))
    vega = S * disc_q * math.exp(-0.5 * d1 * d1) * math.sqrt(T) / math.sqrt(2 * math.pi) / 100.0
    return {"이론가": round(price, 4), "Delta": round(delta, 4), "Gamma": round(gamma, 6), "Vega(1%)": round(vega, 4), "d1": round(d1, 4), "d2": round(d2, 4)}


def build_option_pricing_table(S: float = 100.0, K: float = 100.0, r_pct: float = 4.0, sigma_pct: float = 30.0, days: int = 30, q_pct: float = 0.0) -> pd.DataFrame:
    T = max(days, 1) / 365.0
    rows = []
    for opt in ("call", "put"):
        result = black_scholes_price(S, K, r_pct / 100.0, sigma_pct / 100.0, T, opt, q_pct / 100.0)
        rows.append({"옵션": "콜" if opt == "call" else "풋", "기초자산": S, "행사가": K, "만기일수": days, "IV%": sigma_pct, "금리%": r_pct, **result})
    return pd.DataFrame(rows)


def monte_carlo_summary(current_price: float, expected_return_pct: float = 8.0, volatility_pct: float = 30.0, days: int = 60, simulations: int = 1000, seed: int = 42) -> pd.DataFrame:
    S0 = max(float(current_price), 1e-9)
    mu = expected_return_pct / 100.0
    sigma = volatility_pct / 100.0
    T = max(days, 1) / 252.0
    n = max(int(simulations), 100)
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(n)
    terminal = S0 * np.exp((mu - 0.5 * sigma * sigma) * T + sigma * math.sqrt(T) * z)
    returns = terminal / S0 - 1.0
    q = np.quantile(returns, [0.01, 0.05, 0.25, 0.5, 0.75, 0.95])
    rows = [
        {"지표": "현재가", "값": round(S0, 4), "해석": "입력 기준가"},
        {"지표": "중앙 예상가", "값": round(float(np.median(terminal)), 4), "해석": "시뮬레이션 중앙값"},
        {"지표": "5% 하단 가격", "값": round(float(np.quantile(terminal, 0.05)), 4), "해석": "보수적 하방 기준"},
        {"지표": "95% 상단 가격", "값": round(float(np.quantile(terminal, 0.95)), 4), "해석": "낙관 상방 기준"},
        {"지표": "VaR 95%", "값": f"{q[1]*100:.2f}%", "해석": "하위 5% 손실률 기준"},
        {"지표": "상승 확률", "값": f"{float((returns>0).mean())*100:.2f}%", "해석": "만기 기준 플러스 확률"},
    ]
    return pd.DataFrame(rows)


def build_quant_backtest_table() -> pd.DataFrame:
    bt = _read_csv(REPORT_DIR / "backtest_beta_summary.csv")
    learning = _read_json(REPORT_DIR / "prediction_learning_summary.json")
    risk = _read_json(REPORT_DIR / "portfolio_risk_metrics.json")
    rows: list[dict[str, Any]] = []
    if not bt.empty:
        for _, r in bt.head(50).iterrows():
            rows.append({
                "구분": "백테스트",
                "항목": _safe_str(_first(r, ["strategy", "전략", "name", "metric"], "beta summary")),
                "값": _safe_str(_first(r, ["win_rate", "승률", "return", "수익률", "value"], "-")),
                "해석": _safe_str(_first(r, ["comment", "해석", "reason"], "저장된 beta 리포트 기준")),
            })
    if learning:
        rows.append({"구분": "복기학습", "항목": "status", "값": learning.get("status", "OK"), "해석": "prediction_learning_summary.json"})
    if risk:
        for key in ("sharpe", "sharpe_ratio", "mdd", "max_drawdown", "beta", "alpha", "var_95", "cvar_95"):
            if key in risk:
                rows.append({"구분": "리스크", "항목": key, "값": risk.get(key), "해석": "portfolio_risk_metrics.json"})
    if not rows:
        rows.append({"구분": "백테스트", "항목": "상태", "값": "데이터 필요", "해석": "가격/예측/실제 결과 CSV가 쌓이면 자동 계산 가능"})
    return pd.DataFrame(rows)


def save_v40_reports() -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, int] = {}
    for market, suffix in [("미국주식", "us"), ("한국주식", "kr")]:
        val = build_valuation_kpi_table(market)
        val.to_csv(REPORT_DIR / f"v40_valuation_kpi_{suffix}.csv", index=False, encoding="utf-8-sig")
        outputs[f"valuation_{suffix}"] = len(val)
        macro = build_macro_regime_table(market)
        macro.to_csv(REPORT_DIR / f"v40_macro_regime_{suffix}.csv", index=False, encoding="utf-8-sig")
        outputs[f"macro_{suffix}"] = len(macro)
    quant = build_quant_backtest_table()
    quant.to_csv(V40_QUANT_CSV, index=False, encoding="utf-8-sig")
    outputs["quant"] = len(quant)
    option = build_option_pricing_table()
    option.to_csv(V40_OPTION_CSV, index=False, encoding="utf-8-sig")
    outputs["option_sample"] = len(option)
    mc = monte_carlo_summary(100.0)
    mc.to_csv(V40_MONTE_CARLO_CSV, index=False, encoding="utf-8-sig")
    outputs["monte_carlo_sample"] = len(mc)
    summary = {"status": "OK", "updated_at": _now(), "outputs": outputs}
    V40_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(save_v40_reports(), ensure_ascii=False, indent=2))
