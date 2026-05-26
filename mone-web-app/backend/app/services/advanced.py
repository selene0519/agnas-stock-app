from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.services import data_loader as data


def _num(value: Any, default: float = 0.0) -> float:
    out = data._safe_float(value)
    return default if out is None else float(out)


def _pct(value: float | None, missing: str = "데이터 부족") -> str:
    if value is None or not math.isfinite(value):
        return missing
    return f"{value:.2f}%"


def _market_text(market: str) -> str:
    return "한국주식" if market == "kr" else "미국주식"


def _read_any_csv(path: Path) -> pd.DataFrame:
    try:
        return data.read_csv(path)
    except Exception:
        return pd.DataFrame()


def advanced_backtest(market: str) -> dict[str, Any]:
    summary_json = data.read_json(data.REPORT_DIR / "backtest_beta_summary.json")
    beta = _read_any_csv(data.REPORT_DIR / "backtest_beta_summary.csv")
    quant, quant_source = data.read_report("quant_backtest", market)
    outcome = data.outcome_history()
    predictions = data.read_predictions_csv(market)

    items = []
    for row in data.dataframe_records(beta):
        status = data.first_value(row, ["status"], "데이터 부족")
        days = _num(row.get("days"))
        total = _num(row.get("total_return_pct"))
        win = _num(row.get("win_rate_pct"))
        mdd = _num(row.get("mdd_pct"))
        sharpe = None
        if days > 1:
            avg_daily = _num(row.get("avg_daily_return_pct"))
            sharpe = (avg_daily / max(abs(mdd), 1.0)) * math.sqrt(252)
        items.append({
            "strategy": data.first_value(row, ["전략", "strategy"], "전략명 없음"),
            "status": status,
            "totalReturn": _pct(total),
            "winRate": _pct(win),
            "mdd": _pct(mdd),
            "sharpe": f"{sharpe:.2f}" if sharpe is not None else "데이터 부족",
            "trades": data.first_value(row, ["trades", "symbols"], "거래 수 데이터 부족"),
            "recentResult": "데이터 부족 사유: 30일 이상 OHLC가 있는 종목 부족" if status != "OK" else "최근 결과 확인",
        })

    if not items and not quant.empty:
        for row in data.dataframe_records(quant):
            items.append({
                "strategy": data.first_value(row, ["항목"], "전략명 없음"),
                "status": "기록 축적 중",
                "totalReturn": "데이터 부족",
                "winRate": "데이터 부족",
                "mdd": "데이터 부족",
                "sharpe": "데이터 부족",
                "trades": data.first_value(row, ["값"], "거래 수 데이터 부족"),
                "recentResult": data.first_value(row, ["해석"], "데이터 부족 사유 없음"),
            })

    warnings = summary_json.get("warnings", []) if isinstance(summary_json.get("warnings"), list) else []
    return {
        "market": market,
        "count": len(items),
        "status": summary_json.get("status", "DATA_SHORT" if items else "NO_DATA"),
        "warnings": warnings if warnings else ([] if items else ["백테스트 계산 데이터 부족"]),
        "sources": ["reports/backtest_beta_summary.csv", "reports/backtest_beta_summary.json", quant_source, "data/history/outcome_history.csv", "predictions.csv"],
        "predictionRows": len(predictions),
        "outcomeRows": outcome["count"],
        "items": items,
        "recentOutcomes": outcome["items"][:30],
    }


def _scanner_source_rows(market: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base_files = [
        data.REPO_ROOT / f"candidate_universe_{market}.csv",
        data.REPO_ROOT / f"watchlist_{market}_growth.csv",
    ]
    for path in base_files:
        for row in data.dataframe_records(_read_any_csv(path)):
            item = data.normalize_security_row(data.apply_quote_cache(row, market), market)
            item.update({
                "bucket": "전체",
                "theme": data.first_value(row, ["theme", "테마"], "테마 없음"),
                "group": data.first_value(row, ["group", "그룹"], "그룹 없음"),
                "riskLevel": data.first_value(row, ["risk_level", "위험도"], "위험도 없음"),
                "score": data.first_value(row, ["score", "신뢰도점수"], "점수 없음"),
                "reason": data.first_value(row, ["why_watch", "watch_trigger", "핵심근거", "근거1"], "근거 없음"),
                "watchlistAction": "관심종목 편입 준비 중",
            })
            rows.append(item)

    for kind, bucket in (("action", "BUY"), ("pullback", "눌림목"), ("flow", "수급"), ("risk", "주의")):
        for item in data.candidate_rows(market, kind).get("items", []):
            item = dict(item)
            item.update({
                "bucket": bucket,
                "theme": item.get("category") or bucket,
                "group": bucket,
                "riskLevel": item.get("warning", "주의사항 없음"),
                "score": str(item.get("confidence") or item.get("scores", {}).get("supply") or "점수 없음"),
                "reason": item.get("reason") or item.get("warning") or "근거 없음",
                "watchlistAction": "관심종목 편입 준비 중",
            })
            rows.append(item)

    seen: set[tuple[str, str]] = set()
    unique = []
    for item in rows:
        key = (str(item.get("bucket", "")), data.normalize_symbol(item.get("symbol"), market))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def advanced_scanner(market: str) -> dict[str, Any]:
    rows = _scanner_source_rows(market)
    positions = {data.normalize_symbol(item.get("symbol"), market) for item in data.positions(market).get("items", [])}
    for row in rows:
        row["isHolding"] = data.normalize_symbol(row.get("symbol"), market) in positions
    return {
        "market": market,
        "count": len(rows),
        "filters": ["전체", "BUY", "주의", "눌림목", "수급", "저평가", "보유 제외"],
        "sources": [
            f"candidate_universe_{market}.csv",
            f"watchlist_{market}_growth.csv",
            f"reports/v92_action_cards_{market}.csv",
            f"reports/v92_pullback_cards_{market}.csv",
            f"reports/v92_flow_cards_{market}.csv",
            f"reports/v92_risk_cards_{market}.csv",
        ],
        "items": rows,
    }


def kelly(payload: dict[str, Any]) -> dict[str, Any]:
    win_rate = _num(payload.get("winRate"), 55.0) / 100
    payoff = max(_num(payload.get("payoffRatio"), 1.5), 0.01)
    capital = _num(payload.get("capital"), 10_000_000)
    fraction = max(0.0, win_rate - ((1 - win_rate) / payoff))
    half = fraction / 2
    return {
        "kellyFraction": fraction,
        "kellyText": _pct(fraction * 100),
        "halfKellyText": _pct(half * 100),
        "positionAmount": capital * half,
        "positionAmountText": f"{capital * half:,.0f}",
        "note": "계산 결과만 표시합니다. 자동주문은 지원하지 않습니다.",
    }


def var_cvar(payload: dict[str, Any]) -> dict[str, Any]:
    returns = payload.get("returns")
    if isinstance(returns, list) and returns:
        arr = np.array([_num(x) / 100 for x in returns], dtype=float)
    else:
        mean = _num(payload.get("expectedReturn"), 8.0) / 100 / 252
        vol = _num(payload.get("volatility"), 25.0) / 100 / math.sqrt(252)
        rng = np.random.default_rng(42)
        arr = rng.normal(mean, vol, 5000)
    confidence = min(max(_num(payload.get("confidence"), 95.0), 50), 99.9)
    alpha = 100 - confidence
    var = float(np.percentile(arr, alpha))
    tail = arr[arr <= var]
    cvar = float(tail.mean()) if len(tail) else var
    amount = _num(payload.get("portfolioValue"), 10_000_000)
    return {
        "varPct": _pct(var * 100),
        "cvarPct": _pct(cvar * 100),
        "varAmountText": f"{amount * abs(var):,.0f}",
        "cvarAmountText": f"{amount * abs(cvar):,.0f}",
        "confidenceText": _pct(confidence),
    }


def risk_reward(payload: dict[str, Any]) -> dict[str, Any]:
    entry = _num(payload.get("entry"), 100)
    stop = _num(payload.get("stop"), 90)
    target = _num(payload.get("target"), 120)
    risk = max(entry - stop, 0)
    reward = max(target - entry, 0)
    ratio = reward / risk if risk > 0 else None
    return {
        "risk": risk,
        "reward": reward,
        "ratio": ratio,
        "ratioText": f"1:{ratio:.2f}" if ratio is not None else "손절가/진입가 확인 필요",
        "riskPct": _pct((risk / entry * 100) if entry else None),
        "rewardPct": _pct((reward / entry * 100) if entry else None),
    }


def monte_carlo(payload: dict[str, Any]) -> dict[str, Any]:
    current = max(_num(payload.get("currentPrice"), 100), 0.01)
    expected = _num(payload.get("expectedReturn"), 8.0) / 100
    volatility = max(_num(payload.get("volatility"), 25.0) / 100, 0.0001)
    days = int(min(max(_num(payload.get("days"), 60), 1), 756))
    simulations = int(min(max(_num(payload.get("simulations"), 1000), 100), 5000))
    rng = np.random.default_rng(42)
    dt = 1 / 252
    drift = (expected - 0.5 * volatility * volatility) * dt
    shock_scale = volatility * math.sqrt(dt)
    shocks = rng.normal(drift, shock_scale, (simulations, days))
    paths = current * np.exp(np.cumsum(shocks, axis=1))
    paths = np.column_stack([np.full(simulations, current), paths])
    terminal = paths[:, -1]
    p5, p50, p95 = np.percentile(terminal, [5, 50, 95])
    gains = terminal / current - 1
    var = np.percentile(gains, 5)
    cvar = gains[gains <= var].mean() if np.any(gains <= var) else var
    chart = []
    for idx in range(days + 1):
        col = paths[:, idx]
        chart.append({
            "day": idx,
            "p5": round(float(np.percentile(col, 5)), 4),
            "p50": round(float(np.percentile(col, 50)), 4),
            "p95": round(float(np.percentile(col, 95)), 4),
        })
    return {
        "inputs": {"currentPrice": current, "expectedReturn": expected * 100, "volatility": volatility * 100, "days": days, "simulations": simulations},
        "p5": round(float(p5), 4),
        "p50": round(float(p50), 4),
        "p95": round(float(p95), 4),
        "upProbability": _pct(float((terminal > current).mean() * 100)),
        "expectedFinalPrice": round(float(terminal.mean()), 4),
        "varText": _pct(float(var * 100)),
        "cvarText": _pct(float(cvar * 100)),
        "chart": chart,
    }


def correlation(market: str) -> dict[str, Any]:
    bench = _read_any_csv(data.DATA_DIR / "market" / "benchmark_daily.csv")
    if bench.empty or not {"date", "benchmark", "daily_return"}.issubset(set(bench.columns)):
        return {
            "market": market,
            "status": "NO_DATA",
            "reason": "상관관계 계산 데이터 부족",
            "items": [],
            "matrix": [],
            "sources": ["data/market/benchmark_daily.csv", "data/portfolio"],
        }
    work = bench.copy()
    if market == "kr":
        work = work[work["benchmark"].astype(str).str.contains("KOSPI|KOSDAQ|KR", case=False, regex=True, na=False)]
    else:
        work = work[work["benchmark"].astype(str).str.contains("NASDAQ|S&P|SP500|DOW|US|SOXX|SMH", case=False, regex=True, na=False)]
    if work.empty:
        work = bench.copy()
    work["daily_return"] = pd.to_numeric(work["daily_return"], errors="coerce")
    pivot = work.pivot_table(index="date", columns="benchmark", values="daily_return", aggfunc="last").dropna(axis=1, thresh=20)
    if pivot.shape[1] < 2 or pivot.shape[0] < 20:
        return {
            "market": market,
            "status": "DATA_SHORT",
            "reason": "상관관계 계산 데이터 부족",
            "items": [],
            "matrix": [],
            "sources": ["data/market/benchmark_daily.csv"],
        }
    corr = pivot.corr().round(3)
    matrix = []
    for row_name in corr.index:
        row = {"asset": str(row_name)}
        for col in corr.columns:
            row[str(col)] = float(corr.loc[row_name, col])
        matrix.append(row)
    items = []
    cols = list(corr.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            items.append({"pair": f"{a} / {b}", "correlation": float(corr.loc[a, b]), "interpretation": "낮을수록 분산 효과가 큼" if corr.loc[a, b] < 0.7 else "높은 동행성"})
    return {
        "market": market,
        "status": "OK",
        "reason": "벤치마크 일간 수익률 기준",
        "assets": cols,
        "items": items,
        "matrix": matrix,
        "sources": ["data/market/benchmark_daily.csv"],
        "diversificationNote": "상관계수가 낮은 자산을 섞으면 포트폴리오 변동성 완화에 도움이 됩니다.",
    }
