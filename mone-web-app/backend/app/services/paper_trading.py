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
    """현재가를 OHLCV 최신 종가로 조회 (빠른 CSV 읽기)."""
    try:
        ohlcv_dir = _REPO_ROOT / "data" / "market" / "ohlcv"
        path = ohlcv_dir / f"{market}_{symbol}_daily.csv"
        if not path.exists():
            return None
        # 마지막 줄만 읽어 현재가 취득
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
