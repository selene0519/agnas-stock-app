"""
페이퍼 트레이딩 서비스.

CSV 기반 가상 매매 원장:
  data/paper/paper_trades.csv   — 체결 내역 (BUY/SELL)
  data/paper/paper_balance.json — 시드 / 현금 잔고

기본 시드:
  KR 5,000,000원 / US $5,000 (PAPER_SEED_KR / PAPER_SEED_US 환경변수로 변경 가능)
"""
from __future__ import annotations

import csv
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DATA_DIR = _REPO_ROOT / "data" / "paper"
_TRADES_CSV = _DATA_DIR / "paper_trades.csv"
_BALANCE_JSON = _DATA_DIR / "paper_balance.json"
_STOPS_JSON = _DATA_DIR / "paper_stops.json"  # {market}:{symbol} → {stopPrice, targetPrice, note}

SEED_KR = float(os.getenv("PAPER_SEED_KR", "5000000"))
SEED_US = float(os.getenv("PAPER_SEED_US", "5000"))

_LOCK = threading.Lock()

_TRADE_FIELDS = [
    "id", "createdAt", "market", "symbol", "name",
    "action", "price", "quantity", "totalValue", "memo",
]


def _ensure_dirs() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── 잔고 관리 ──────────────────────────────────────────────────────────────

def _load_balance() -> dict[str, float]:
    _ensure_dirs()
    if _BALANCE_JSON.exists():
        try:
            return json.loads(_BALANCE_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    default = {"kr": SEED_KR, "us": SEED_US}
    _BALANCE_JSON.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
    return default


def _save_balance(balance: dict[str, float]) -> None:
    _ensure_dirs()
    _BALANCE_JSON.write_text(json.dumps(balance, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 체결 내역 ──────────────────────────────────────────────────────────────

def _load_trades() -> list[dict]:
    _ensure_dirs()
    if not _TRADES_CSV.exists():
        return []
    rows: list[dict] = []
    for enc in ("utf-8-sig", "utf-8"):
        try:
            with _TRADES_CSV.open("r", encoding=enc) as f:
                rows = list(csv.DictReader(f))
            break
        except Exception:
            continue
    return rows


def _append_trade(trade: dict) -> None:
    _ensure_dirs()
    write_header = not _TRADES_CSV.exists() or _TRADES_CSV.stat().st_size == 0
    with _TRADES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_TRADE_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({k: trade.get(k, "") for k in _TRADE_FIELDS})


# ── 포지션 계산 ────────────────────────────────────────────────────────────

def _compute_positions(trades: list[dict]) -> dict[str, dict]:
    """체결 내역에서 현재 보유 포지션을 계산."""
    positions: dict[str, dict] = {}  # key = f"{market}:{symbol}"
    for t in trades:
        mk = str(t.get("market", "")).lower()
        sym = str(t.get("symbol", "")).strip()
        key = f"{mk}:{sym}"
        price = float(t.get("price") or 0)
        qty = float(t.get("quantity") or 0)
        action = str(t.get("action", "")).upper()

        if key not in positions:
            positions[key] = {
                "market": mk,
                "symbol": sym,
                "name": str(t.get("name", sym)),
                "quantity": 0.0,
                "totalCost": 0.0,
            }

        if action == "BUY":
            positions[key]["quantity"] += qty
            positions[key]["totalCost"] += price * qty
        elif action == "SELL":
            # 비례 원가 차감
            prev_qty = positions[key]["quantity"]
            if prev_qty > 0:
                cost_per = positions[key]["totalCost"] / prev_qty
                positions[key]["totalCost"] -= cost_per * min(qty, prev_qty)
            positions[key]["quantity"] -= qty
            if positions[key]["quantity"] < 0:
                positions[key]["quantity"] = 0.0
            if positions[key]["totalCost"] < 0:
                positions[key]["totalCost"] = 0.0

    # 수량 0인 항목 제거
    return {k: v for k, v in positions.items() if v["quantity"] > 0.0001}


def _enrich_positions(positions: dict[str, dict]) -> list[dict]:
    """현재가 조회 후 P&L 계산."""
    result = []
    for key, pos in positions.items():
        qty = pos["quantity"]
        avg_price = pos["totalCost"] / qty if qty > 0 else 0
        # 현재가 조회 시도
        current_price = _get_current_price(pos["symbol"], pos["market"])
        valuation = current_price * qty if current_price else 0
        cost = pos["totalCost"]
        pnl = valuation - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0
        result.append({
            "market": pos["market"],
            "symbol": pos["symbol"],
            "name": pos["name"],
            "quantity": round(qty, 4),
            "avgPrice": round(avg_price, 2),
            "currentPrice": round(current_price, 2) if current_price else None,
            "cost": round(cost, 2),
            "valuation": round(valuation, 2),
            "pnl": round(pnl, 2),
            "pnlPct": round(pnl_pct, 2),
        })
    return sorted(result, key=lambda x: abs(x.get("pnl") or 0), reverse=True)


def _get_current_price(symbol: str, market: str) -> float | None:
    """현재가 조회. KIS quote cache → OHLCV 최신 close 순서로 fallback."""
    # 1) KIS 현재가 CSV (가장 최신, 장중 실시간에 근접)
    for quote_file in (
        _REPO_ROOT / "data" / "stockapp" / f"kis_current_price_{market}.csv",
        _REPO_ROOT / "data" / "stockapp" / f"current_price_{market}.csv",
        _REPO_ROOT / "data" / f"kis_current_price_{market}.csv",
    ):
        if not quote_file.exists():
            continue
        try:
            with quote_file.open("r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    sym = (row.get("symbol") or row.get("ticker") or row.get("code") or "").strip()
                    if sym == symbol:
                        for key in ("currentPrice", "current_price", "stck_prpr", "close", "price"):
                            v = row.get(key)
                            if v:
                                try:
                                    return float(str(v).replace(",", ""))
                                except ValueError:
                                    pass
        except Exception:
            continue

    # 2) OHLCV 최신 종가 fallback
    try:
        path = _REPO_ROOT / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return None
        last = rows[-1]
        val = last.get("close") or last.get("Close") or last.get("currentPrice")
        return float(val) if val else None
    except Exception:
        return None


# ── 공개 API ──────────────────────────────────────────────────────────────

def buy(
    symbol: str,
    market: str,
    quantity: float,
    price: float | None = None,
    name: str = "",
    memo: str = "",
) -> dict[str, Any]:
    """가상 매수."""
    with _LOCK:
        mk = market.lower()
        balance = _load_balance()
        cash = balance.get(mk, 0.0)

        if price is None:
            price = _get_current_price(symbol, mk)
            if price is None:
                return {"ok": False, "error": f"{symbol} 현재가를 조회할 수 없습니다."}

        total = price * quantity
        if total > cash:
            return {
                "ok": False,
                "error": f"잔고 부족 (필요: {total:,.0f} / 보유: {cash:,.0f})",
                "cash": round(cash, 2),
                "required": round(total, 2),
            }

        trade: dict = {
            "id": str(uuid.uuid4())[:8],
            "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "market": mk,
            "symbol": symbol,
            "name": name or symbol,
            "action": "BUY",
            "price": round(price, 2),
            "quantity": round(quantity, 4),
            "totalValue": round(total, 2),
            "memo": memo,
        }
        _append_trade(trade)
        balance[mk] = round(cash - total, 2)
        _save_balance(balance)

        return {
            "ok": True,
            "trade": trade,
            "remainingCash": balance[mk],
            "message": f"{name or symbol} {quantity:g}주 매수 완료 (체결가 {price:,.0f})",
        }


def sell(
    symbol: str,
    market: str,
    quantity: float,
    price: float | None = None,
    memo: str = "",
) -> dict[str, Any]:
    """가상 매도."""
    with _LOCK:
        mk = market.lower()
        trades = _load_trades()
        positions = _compute_positions(trades)
        key = f"{mk}:{symbol}"

        if key not in positions:
            return {"ok": False, "error": f"{symbol} 보유 포지션 없음"}

        held_qty = positions[key]["quantity"]
        if quantity > held_qty + 0.0001:
            return {
                "ok": False,
                "error": f"보유 수량 초과 (보유: {held_qty:g} / 매도 요청: {quantity:g})",
            }

        if price is None:
            price = _get_current_price(symbol, mk)
            if price is None:
                return {"ok": False, "error": f"{symbol} 현재가를 조회할 수 없습니다."}

        total = price * quantity
        avg = positions[key]["totalCost"] / held_qty if held_qty > 0 else 0
        pnl = (price - avg) * quantity
        pnl_pct = (price / avg - 1) * 100 if avg > 0 else 0
        name = positions[key]["name"]

        trade: dict = {
            "id": str(uuid.uuid4())[:8],
            "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "market": mk,
            "symbol": symbol,
            "name": name,
            "action": "SELL",
            "price": round(price, 2),
            "quantity": round(quantity, 4),
            "totalValue": round(total, 2),
            "memo": memo,
        }
        _append_trade(trade)

        balance = _load_balance()
        balance[mk] = round(balance.get(mk, 0.0) + total, 2)
        _save_balance(balance)

        return {
            "ok": True,
            "trade": trade,
            "pnl": round(pnl, 2),
            "pnlPct": round(pnl_pct, 2),
            "remainingCash": balance[mk],
            "message": f"{name} {quantity:g}주 매도 완료 (손익 {pnl:+,.0f} / {pnl_pct:+.1f}%)",
        }


def get_positions(market: str = "all") -> dict[str, Any]:
    """현재 보유 포지션 목록."""
    trades = _load_trades()
    if market != "all":
        mk = market.lower()
        trades = [t for t in trades if str(t.get("market", "")).lower() == mk]
    positions = _compute_positions(trades)
    enriched = _enrich_positions(positions)
    balance = _load_balance()
    return {
        "status": "OK",
        "market": market,
        "cash": {k: round(v, 2) for k, v in balance.items()},
        "count": len(enriched),
        "items": enriched,
    }


def get_history(market: str = "all", limit: int = 100) -> dict[str, Any]:
    """체결 내역 (최신순)."""
    trades = _load_trades()
    if market != "all":
        mk = market.lower()
        trades = [t for t in trades if str(t.get("market", "")).lower() == mk]
    trades_sorted = list(reversed(trades))[:limit]
    for t in trades_sorted:
        for f in ("price", "quantity", "totalValue"):
            try:
                t[f] = float(t[f])
            except Exception:
                pass
    return {"status": "OK", "market": market, "count": len(trades_sorted), "items": trades_sorted}


def get_summary(market: str = "all") -> dict[str, Any]:
    """포트폴리오 요약 (잔고 + 평가금액 + 총 손익)."""
    trades = _load_trades()
    balance = _load_balance()
    seeds = {"kr": SEED_KR, "us": SEED_US}

    markets = ["kr", "us"] if market == "all" else [market.lower()]
    result: dict[str, Any] = {"status": "OK", "market": market, "markets": {}}

    total_seed = 0.0
    total_portfolio = 0.0

    for mk in markets:
        mk_trades = [t for t in trades if str(t.get("market", "")).lower() == mk]
        positions = _compute_positions(mk_trades)
        enriched = _enrich_positions(positions)

        cash = balance.get(mk, seeds.get(mk, 0.0))
        seed = seeds.get(mk, cash)
        invested = sum(p.get("cost") or 0 for p in enriched)
        valuation = sum(p.get("valuation") or p.get("cost") or 0 for p in enriched)
        unrealized_pnl = sum(p.get("pnl") or 0 for p in enriched)

        # 실현 손익 계산
        realized_pnl = 0.0
        for t in mk_trades:
            if str(t.get("action", "")).upper() == "SELL":
                total_val = float(t.get("totalValue") or 0)
                qty = float(t.get("quantity") or 0)
                sell_price = float(t.get("price") or 0)
                # 실현 손익 근사 (매도 시 기록된 값 사용)
                realized_pnl += total_val  # 매도 수령액 누적

        portfolio_value = cash + valuation
        total_pnl = portfolio_value - seed
        total_return_pct = (portfolio_value / seed - 1) * 100 if seed > 0 else 0

        result["markets"][mk] = {
            "seed": round(seed, 2),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "valuation": round(valuation, 2),
            "portfolioValue": round(portfolio_value, 2),
            "unrealizedPnl": round(unrealized_pnl, 2),
            "totalPnl": round(total_pnl, 2),
            "totalReturnPct": round(total_return_pct, 2),
            "positionCount": len(enriched),
            "tradeCount": len(mk_trades),
        }
        total_seed += seed
        total_portfolio += portfolio_value

    if market == "all":
        total_pnl = total_portfolio - total_seed
        result["composite"] = {
            "totalReturnPct": round((total_portfolio / total_seed - 1) * 100, 2) if total_seed > 0 else 0,
            "totalPnl": round(total_pnl, 2),
        }

    return result


def reset(market: str = "all", seed_kr: float | None = None, seed_us: float | None = None) -> dict[str, Any]:
    """페이퍼 트레이딩 초기화 (전체 또는 특정 시장). seed_kr/seed_us 미전달 시 환경변수 기본값 사용."""
    sk = seed_kr if seed_kr and seed_kr > 0 else SEED_KR
    su = seed_us if seed_us and seed_us > 0 else SEED_US
    with _LOCK:
        if market == "all":
            if _TRADES_CSV.exists():
                _TRADES_CSV.unlink()
            _save_balance({"kr": sk, "us": su})
            return {"ok": True, "message": "전체 페이퍼 트레이딩 초기화 완료"}
        else:
            mk = market.lower()
            trades = _load_trades()
            remaining = [t for t in trades if str(t.get("market", "")).lower() != mk]
            _ensure_dirs()
            with _TRADES_CSV.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_TRADE_FIELDS)
                writer.writeheader()
                writer.writerows(remaining)
            balance = _load_balance()
            balance[mk] = sk if mk == "kr" else su
            _save_balance(balance)
            return {"ok": True, "message": f"{mk.upper()} 페이퍼 트레이딩 초기화 완료"}


def drawdown_summary(market: str = "all") -> dict[str, Any]:
    """현재 포트폴리오 드로다운 계산.

    peak = 시드(초기금액)와 현재 포트폴리오 중 최고값 기준
    drawdown = (peak - current) / peak * 100
    alert level: GREEN <5% / YELLOW 5~15% / RED >15%
    """
    summary = get_summary(market)
    markets_data = summary.get("markets", {})
    result: dict[str, Any] = {"status": "OK", "market": market, "markets": {}}

    for mk, data in markets_data.items():
        seed = float(data.get("seed") or 0)
        portfolio_value = float(data.get("portfolioValue") or 0)
        if seed <= 0:
            result["markets"][mk] = {"drawdownPct": None, "alertLevel": "UNKNOWN", "portfolioValue": portfolio_value, "seed": seed}
            continue
        # Peak = max of seed and current portfolio (no historical max tracking — approximate from trade history)
        trades = _load_trades()
        mk_trades = [t for t in trades if str(t.get("market", "")).lower() == mk]
        # Compute peak portfolio value from trade history snapshots
        # Approximate: each BUY reduces cash but adds positions; we track running portfolio value
        # Simpler: peak = max(seed, current portfolio value) since we don't have time series
        peak = max(seed, portfolio_value)
        drawdown_pct = round((peak - portfolio_value) / peak * 100, 2) if peak > 0 else 0.0
        total_return_pct = float(data.get("totalReturnPct") or 0)
        alert_level = "GREEN"
        if drawdown_pct >= 15:
            alert_level = "RED"
        elif drawdown_pct >= 5:
            alert_level = "YELLOW"
        result["markets"][mk] = {
            "seed": round(seed, 2),
            "portfolioValue": round(portfolio_value, 2),
            "peakValue": round(peak, 2),
            "drawdownPct": drawdown_pct,
            "totalReturnPct": total_return_pct,
            "alertLevel": alert_level,
            "positionCount": data.get("positionCount", 0),
            "cash": round(float(data.get("cash") or 0), 2),
        }

    return result


# ──────────────────────────────────────────────────────────────────
# 스탑/타겟 관리 (보유중 관리)
# ──────────────────────────────────────────────────────────────────

def _load_stops() -> dict[str, Any]:
    _ensure_dirs()
    if _STOPS_JSON.exists():
        try:
            return json.loads(_STOPS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_stops(stops: dict[str, Any]) -> None:
    _ensure_dirs()
    _STOPS_JSON.write_text(json.dumps(stops, ensure_ascii=False, indent=2), encoding="utf-8")


def update_stop(
    market: str,
    symbol: str,
    stop_price: float | None = None,
    target_price: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    """포지션별 스탑/타겟 가격 업데이트."""
    key = f"{market.lower()}:{symbol.upper()}"
    with _LOCK:
        stops = _load_stops()
        entry = stops.get(key, {})
        if stop_price is not None:
            entry["stopPrice"] = round(float(stop_price), 2)
        if target_price is not None:
            entry["targetPrice"] = round(float(target_price), 2)
        if note:
            entry["note"] = note
        entry["updatedAt"] = datetime.utcnow().isoformat()
        stops[key] = entry
        _save_stops(stops)
    return {"ok": True, "key": key, "stop": entry}


def get_stops(market: str = "all") -> dict[str, Any]:
    """저장된 스탑/타겟 가격 조회."""
    stops = _load_stops()
    if market == "all":
        return {"status": "OK", "stops": stops}
    mk = market.lower()
    filtered = {k: v for k, v in stops.items() if k.startswith(f"{mk}:")}
    return {"status": "OK", "stops": filtered}


def check_stops(market: str = "all") -> dict[str, Any]:
    """현재가 vs 스탑/타겟 비교 — 경보 목록 반환.

    alertLevel:
      STOP_HIT    현재가 ≤ stopPrice
      STOP_NEAR   현재가 < stopPrice × 1.05 (5% 이내)
      TARGET_HIT  현재가 ≥ targetPrice
      TARGET_NEAR 현재가 > targetPrice × 0.95 (5% 이내)
    """
    pos_res = get_positions(market)
    stops = _load_stops()
    alerts = []

    for pos in pos_res.get("items", []):
        mk = str(pos.get("market", "")).lower()
        sym = str(pos.get("symbol", "")).upper()
        key = f"{mk}:{sym}"
        current = pos.get("currentPrice")
        stop_entry = stops.get(key, {})
        stop_price = stop_entry.get("stopPrice")
        target_price = stop_entry.get("targetPrice")
        avg_price = pos.get("avgPrice")

        if current is None:
            continue

        alert_level = None
        if stop_price and current <= stop_price:
            alert_level = "STOP_HIT"
        elif stop_price and current < stop_price * 1.05:
            alert_level = "STOP_NEAR"
        elif target_price and current >= target_price:
            alert_level = "TARGET_HIT"
        elif target_price and current > target_price * 0.95:
            alert_level = "TARGET_NEAR"

        stop_dist_pct = round((current - stop_price) / stop_price * 100, 2) if stop_price else None
        target_dist_pct = round((target_price - current) / current * 100, 2) if target_price else None

        alerts.append({
            "market": mk,
            "symbol": sym,
            "name": pos.get("name", sym),
            "currentPrice": current,
            "avgPrice": avg_price,
            "pnlPct": pos.get("pnlPct"),
            "stopPrice": stop_price,
            "targetPrice": target_price,
            "stopDistPct": stop_dist_pct,
            "targetDistPct": target_dist_pct,
            "alertLevel": alert_level,
            "note": stop_entry.get("note", ""),
        })

    # 경보 순서: STOP_HIT > STOP_NEAR > TARGET_HIT > TARGET_NEAR > None
    _order = {"STOP_HIT": 0, "STOP_NEAR": 1, "TARGET_HIT": 2, "TARGET_NEAR": 3}
    alerts.sort(key=lambda a: _order.get(a["alertLevel"] or "", 9))

    hit_count = sum(1 for a in alerts if a["alertLevel"] in {"STOP_HIT", "TARGET_HIT"})
    near_count = sum(1 for a in alerts if a["alertLevel"] in {"STOP_NEAR", "TARGET_NEAR"})

    return {
        "status": "OK",
        "hitCount": hit_count,
        "nearCount": near_count,
        "alerts": alerts,
    }
