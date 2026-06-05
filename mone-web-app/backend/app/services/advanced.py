from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.engine import quant_scanner
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


DATE_ALIASES = ["date", "Date", "날짜", "stck_bsop_date", "xymd", "time", "timestamp"]
OPEN_ALIASES = ["open", "Open", "시가", "stck_oprc", "ovrs_nmix_oprc", "open_price"]
HIGH_ALIASES = ["high", "High", "고가", "stck_hgpr", "ovrs_nmix_hgpr", "high_price"]
LOW_ALIASES = ["low", "Low", "저가", "stck_lwpr", "ovrs_nmix_lwpr", "low_price"]
CLOSE_ALIASES = ["close", "Close", "종가", "stck_clpr", "ovrs_nmix_prpr", "last", "adj_close", "Adj Close", "close_price"]
VOLUME_ALIASES = ["volume", "Volume", "거래량", "acml_vol", "tvol", "vol"]


def _first_col(df: pd.DataFrame, aliases: list[str]) -> str | None:
    exact = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        key = alias.strip().lower()
        if key in exact:
            return exact[key]
    # 느슨한 fallback: 공백/언더바 제거 후 비교
    compact = {str(c).strip().lower().replace("_", "").replace(" ", ""): c for c in df.columns}
    for alias in aliases:
        key = alias.strip().lower().replace("_", "").replace(" ", "")
        if key in compact:
            return compact[key]
    return None


def _to_number_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.replace("$", "", regex=False).str.replace("원", "", regex=False).str.strip(),
        errors="coerce",
    )


def _parse_date_series(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    parsed = pd.to_datetime(text, errors="coerce")
    compact = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    parsed = parsed.fillna(compact)
    return parsed


def _symbol_from_ohlcv_path(path: Path, market: str) -> str:
    name = path.stem
    prefix = f"{market}_"
    if name.lower().startswith(prefix):
        name = name[len(prefix):]
    if name.lower().endswith("_daily"):
        name = name[:-6]
    return data.normalize_symbol(name, market)


def _ohlcv_files(market: str) -> list[Path]:
    base = data.DATA_DIR / "market" / "ohlcv"
    if not base.exists():
        return []
    return sorted(base.glob(f"{market}_*_daily.csv"))


def _normalize_ohlcv_frame(path: Path, market: str) -> tuple[pd.DataFrame, str]:
    raw = _read_any_csv(path)
    if raw.empty:
        return pd.DataFrame(), "파일이 비어 있음"

    date_col = _first_col(raw, DATE_ALIASES)
    close_col = _first_col(raw, CLOSE_ALIASES)
    open_col = _first_col(raw, OPEN_ALIASES) or close_col
    high_col = _first_col(raw, HIGH_ALIASES) or close_col
    low_col = _first_col(raw, LOW_ALIASES) or close_col
    volume_col = _first_col(raw, VOLUME_ALIASES)

    if not date_col or not close_col:
        return pd.DataFrame(), f"필수 컬럼 부족(date={date_col}, close={close_col})"

    work = pd.DataFrame({
        "date": _parse_date_series(raw[date_col]),
        "open": _to_number_series(raw[open_col]),
        "high": _to_number_series(raw[high_col]),
        "low": _to_number_series(raw[low_col]),
        "close": _to_number_series(raw[close_col]),
    })
    work["volume"] = _to_number_series(raw[volume_col]) if volume_col else 0
    work = work.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

    # open/high/low가 없는 fallback 파일은 close로 보강해서 백테스트가 깨지지 않게 함.
    for col in ["open", "high", "low"]:
        work[col] = work[col].fillna(work["close"])
    work = work[(work["close"] > 0)].reset_index(drop=True)
    return work, "OK" if not work.empty else "정상 가격 row 없음"


def _eligible_ohlcv_universe(market: str, min_days: int = 30) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []
    schema_errors: list[dict[str, Any]] = []
    paths = _ohlcv_files(market)

    for path in paths:
        symbol = _symbol_from_ohlcv_path(path, market)
        if not symbol:
            continue
        frame, status = _normalize_ohlcv_frame(path, market)
        if frame.empty or status != "OK":
            schema_errors.append({"symbol": symbol, "file": path.name, "reason": status})
            continue
        if len(frame) <= min_days:
            insufficient.append({"symbol": symbol, "file": path.name, "rows": len(frame), "reason": f"{min_days} bars or fewer"})
            continue

        latest = frame.iloc[-1]
        latest_close = float(latest["close"])
        latest_date = latest["date"].strftime("%Y-%m-%d") if pd.notna(latest["date"]) else ""
        item = data.normalize_security_row({
            "symbol": symbol,
            "ticker": symbol,
            "code": symbol,
            "current_price": latest_close,
            "basis_ohlc_date": latest_date,
            "sourceFile": path.relative_to(data.REPO_ROOT).as_posix(),
            "sourceDate": latest_date,
        }, market)
        item.update({
            "bucket": "OHLCV_30_PLUS",
            "theme": "OHLCV",
            "group": "OHLCV",
            "riskLevel": "QUANT_READY",
            "score": "quant pending",
            "reason": f"OHLCV {len(frame)} bars available",
            "watchlistAction": "quant score from OHLCV",
            "ohlcvRows": len(frame),
            "ohlcvLatestDate": latest_date,
        })
        rows.append(item)

    return rows, {
        "files": len(paths),
        "eligibleSymbols": len(rows),
        "minDaysRequired": min_days + 1,
        "insufficient": insufficient[:30],
        "schemaErrors": schema_errors[:30],
    }


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _max_drawdown_from_returns(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    equity = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(equity)
    dd = equity / np.where(peak == 0, 1, peak) - 1
    return float(dd.min())


def _strategy_returns(frame: pd.DataFrame, symbol: str) -> dict[str, list[dict[str, Any]]]:
    work = frame.copy()
    work["ret_next"] = work["close"].shift(-1) / work["close"] - 1
    work["ma10"] = work["close"].rolling(10).mean()
    work["ma20"] = work["close"].rolling(20).mean()
    work["high20"] = work["high"].rolling(20).max().shift(1)
    work["rsi14"] = _rsi(work["close"], 14)

    strategy_signals = {
        "20일 고점 돌파": work["close"] > work["high20"],
        "MA10 > MA20 추세": work["ma10"] > work["ma20"],
        "RSI 저점 반등": (work["rsi14"] < 35) & (work["close"] > work["close"].shift(1)),
        "20일선 눌림목": (work["close"] > work["ma20"]) & ((work["close"] / work["ma20"] - 1).abs() <= 0.03),
    }

    out: dict[str, list[dict[str, Any]]] = {name: [] for name in strategy_signals}
    for name, signal in strategy_signals.items():
        selected = work[signal.fillna(False) & work["ret_next"].notna()].copy()
        for _, row in selected.iterrows():
            out[name].append({
                "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else "",
                "symbol": symbol,
                "return": float(row["ret_next"]),
                "close": float(row["close"]),
            })
    return out


def _metrics_for_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "totalReturn": "0.00%",
            "winRate": "0.00%",
            "mdd": "0.00%",
            "sharpe": "데이터 부족",
            "trades": "0",
            "status": "DATA_SHORT",
            "recentResult": "신호 또는 OHLC 데이터 부족",
        }
    arr = np.array([float(t["return"]) for t in trades if math.isfinite(float(t["return"]))], dtype=float)
    if arr.size == 0:
        return {
            "totalReturn": "0.00%",
            "winRate": "0.00%",
            "mdd": "0.00%",
            "sharpe": "데이터 부족",
            "trades": "0",
            "status": "DATA_SHORT",
            "recentResult": "유효 수익률 데이터 부족",
        }
    avg_return = float(arr.mean() * 100)
    win = float((arr > 0).mean() * 100)
    mdd = _max_drawdown_from_returns(arr) * 100
    sharpe = None
    if arr.size > 2 and float(arr.std()) > 0:
        sharpe = float(arr.mean() / arr.std() * math.sqrt(252))
    recent = sorted(trades, key=lambda x: str(x.get("date", "")), reverse=True)[:5]
    recent_avg = np.array([float(t["return"]) for t in recent], dtype=float).mean() * 100 if recent else 0
    return {
        "totalReturn": _pct(avg_return),
        "winRate": _pct(win),
        "mdd": _pct(mdd),
        "sharpe": f"{sharpe:.2f}" if sharpe is not None else "데이터 부족",
        "trades": str(int(arr.size)),
        "status": "OK",
        "recentResult": f"최근 {len(recent)}건 평균 {recent_avg:.2f}% · 실제 OHLCV 기반",
    }


def advanced_backtest(market: str) -> dict[str, Any]:
    outcome = data.outcome_history()
    predictions_all = data.read_predictions_csv(None)
    predictions = data.read_predictions_csv(market)

    ohlcv_paths = _ohlcv_files(market)
    min_days = 30
    eligible_frames: dict[str, pd.DataFrame] = {}
    insufficient: list[dict[str, Any]] = []
    schema_errors: list[dict[str, Any]] = []

    for path in ohlcv_paths:
        symbol = _symbol_from_ohlcv_path(path, market)
        frame, status = _normalize_ohlcv_frame(path, market)
        if frame.empty or status != "OK":
            schema_errors.append({"symbol": symbol, "file": path.name, "reason": status})
            continue
        if len(frame) < min_days:
            insufficient.append({"symbol": symbol, "file": path.name, "rows": len(frame), "reason": f"{min_days}일 미만 OHLCV"})
            continue
        eligible_frames[symbol] = frame

    prediction_symbols = {data.normalize_symbol(data.first_value(row, data.SYMBOL_ALIASES), market) for row in predictions}
    prediction_symbols = {s for s in prediction_symbols if s}
    eligible_symbols = set(eligible_frames)
    matched_prediction_symbols = prediction_symbols & eligible_symbols

    strategy_trades: dict[str, list[dict[str, Any]]] = {
        "20일 고점 돌파": [],
        "MA10 > MA20 추세": [],
        "RSI 저점 반등": [],
        "20일선 눌림목": [],
    }
    for symbol, frame in eligible_frames.items():
        result = _strategy_returns(frame, symbol)
        for strategy, trades in result.items():
            strategy_trades.setdefault(strategy, []).extend(trades)

    items: list[dict[str, Any]] = []
    for strategy, trades in strategy_trades.items():
        metrics = _metrics_for_trades(trades)
        items.append({
            "strategy": strategy,
            "status": metrics["status"],
            "totalReturn": metrics["totalReturn"],
            "winRate": metrics["winRate"],
            "mdd": metrics["mdd"],
            "sharpe": metrics["sharpe"],
            "trades": metrics["trades"],
            "recentResult": metrics["recentResult"],
        })

    total_trades = sum(int(item["trades"]) for item in items if str(item.get("trades", "0")).isdigit())
    status = "OK" if eligible_frames and total_trades > 0 else "DATA_SHORT"
    warnings: list[str] = []
    if not ohlcv_paths:
        warnings.append("data/market/ohlcv에 OHLCV 파일이 없습니다")
    if not eligible_frames:
        warnings.append("30일 이상 OHLCV가 있는 종목이 없습니다")
    if prediction_symbols and not matched_prediction_symbols:
        warnings.append("예측 종목과 OHLCV 보유 종목이 매칭되지 않습니다")
    if status == "OK":
        warnings.append("data/market/ohlcv 실제 OHLCV 기반 백테스트")

    diagnostics = [
        {"항목": "전체 predictions.csv rows", "값": len(predictions_all), "해석": "전체 예측 원장"},
        {"항목": "현재 시장 필터 rows", "값": len(predictions), "해석": _market_text(market)},
        {"항목": "OHLCV 파일 수", "값": len(ohlcv_paths), "해석": "data/market/ohlcv/*_daily.csv"},
        {"항목": "30일 이상 OHLCV 종목 수", "값": len(eligible_frames), "해석": f"최소 기준 {min_days}일"},
        {"항목": "예측+OHLCV 매칭 종목 수", "값": len(matched_prediction_symbols), "해석": "예측 기록과 가격 데이터가 모두 있는 종목"},
        {"항목": "OHLCV 부족 종목 수", "값": len(insufficient), "해석": "30일 미만"},
        {"항목": "OHLCV 컬럼/파싱 오류 수", "값": len(schema_errors), "해석": "date/close 등 필수값 문제"},
        {"항목": "전체 거래 신호 수", "값": total_trades, "해석": "4개 전략 합산"},
    ]

    recent_trades = []
    for strategy, trades in strategy_trades.items():
        for trade in sorted(trades, key=lambda x: str(x.get("date", "")), reverse=True)[:10]:
            recent_trades.append({
                "date": trade.get("date", ""),
                "strategy": strategy,
                "symbol": trade.get("symbol", ""),
                "return": _pct(float(trade.get("return", 0)) * 100),
                "close": data.format_price(float(trade.get("close", 0)), market),
            })
    recent_trades = sorted(recent_trades, key=lambda x: str(x.get("date", "")), reverse=True)[:30]

    return {
        "market": market,
        "count": len(items),
        "status": status,
        "warnings": warnings,
        "sources": [
            "data/market/ohlcv/*_daily.csv",
            "predictions.csv",
            "data/history/outcome_history.csv",
        ],
        "predictionRows": len(predictions),
        "totalPredictionRows": len(predictions_all),
        "outcomeRows": outcome["count"],
        "items": items,
        "recentOutcomes": outcome["items"][:30],
        "recentTrades": recent_trades,
        "diagnostics": diagnostics,
        "ohlcv": {
            "files": len(ohlcv_paths),
            "eligibleSymbols": len(eligible_frames),
            "minDaysRequired": min_days,
            "predictionMatchedSymbols": len(matched_prediction_symbols),
            "insufficient": insufficient[:30],
            "schemaErrors": schema_errors[:30],
        },
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


def _number_sort_key(value: Any) -> float:
    num = data._safe_float(value)
    return float(num) if num is not None and math.isfinite(float(num)) else -1.0


def advanced_scanner(market: str, mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    rows = _scanner_source_rows(market)
    ohlcv_rows, ohlcv_summary = _eligible_ohlcv_universe(market, min_days=30)
    seen_symbols = {data.normalize_symbol(item.get("symbol"), market) for item in rows}
    rows.extend([item for item in ohlcv_rows if data.normalize_symbol(item.get("symbol"), market) not in seen_symbols])
    positions = {data.normalize_symbol(item.get("symbol"), market) for item in data.positions(market).get("items", [])}
    for row in rows:
        row["isHolding"] = data.normalize_symbol(row.get("symbol"), market) in positions
        scored = quant_scanner.apply_quant_overlay(row, data.REPO_ROOT, mode, horizon)
        if scored.get("finalScore") is not None:
            scored["score"] = scored.get("finalScore")
        row.clear()
        row.update(scored)
    rows.sort(key=lambda item: (_number_sort_key(item.get("finalScore")), _number_sort_key(item.get("quantScore"))), reverse=True)
    quant_ready_count = sum(1 for item in rows if item.get("quantScore") is not None and item.get("quantDataStatus") != "DATA_PENDING")
    quote_ready_count = sum(1 for item in rows if data._safe_float(item.get("currentPrice")) is not None)
    quote_coverage_pct = (quote_ready_count / len(rows) * 100) if rows else 0.0
    return {
        "market": market,
        "mode": quant_scanner.normalize_mode(mode),
        "horizon": quant_scanner.normalize_horizon(horizon),
        "count": len(rows),
        "filters": ["전체", "BUY", "주의", "눌림목", "수급", "저평가", "보유 제외"],
        "sources": [
            f"candidate_universe_{market}.csv",
            f"watchlist_{market}_growth.csv",
            f"reports/v92_action_cards_{market}.csv",
            f"reports/v92_pullback_cards_{market}.csv",
            f"reports/v92_flow_cards_{market}.csv",
            f"reports/v92_risk_cards_{market}.csv",
            "data/market/ohlcv/*_daily.csv",
        ],
        "scanCoverage": {
            "universeScope": "OHLCV_30_PLUS",
            "isFullMarket": False,
            "localScanUniverseCount": len(rows),
            "ohlcvSymbolCount": ohlcv_summary["eligibleSymbols"],
            "quoteCoveragePct": round(quote_coverage_pct, 1),
            "quantReadyCount": quant_ready_count,
            "quoteReadyCount": quote_ready_count,
            "minOhlcvRowsRequired": ohlcv_summary["minDaysRequired"],
            "ohlcvFiles": ohlcv_summary["files"],
            "insufficient": ohlcv_summary["insufficient"],
            "schemaErrors": ohlcv_summary["schemaErrors"],
        },
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
