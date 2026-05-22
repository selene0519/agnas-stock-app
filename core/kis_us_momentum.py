from __future__ import annotations

import math
from typing import Any

from core.kis_us_client import first_num, kis_us_request, payload_outputs, row_symbol
from core.kis_us_quote import fetch_kis_us_quote_api, kis_us_exchange_candidates, normalize_us_ticker

US_CCNL_PATH = "/uapi/overseas-price/v1/quotations/inquire-ccnl"
US_CCNL_TR_ID = "HHDFS76200300"
US_PRICE_PATH = "/uapi/overseas-price/v1/quotations/price"
US_PRICE_TR_ID = "HHDFS00000300"

RANK_VOLUME_SURGE = ("/uapi/overseas-stock/v1/ranking/volume-surge", "HHDFS76270000", {"MINX": "0", "VOL_RANG": "0"})
RANK_TRADE_PBMN = ("/uapi/overseas-stock/v1/ranking/trade-pbmn", "HHDFS76320010", {"NDAY": "0", "VOL_RANG": "0"})
RANK_TRADE_GROWTH = ("/uapi/overseas-stock/v1/ranking/trade-growth", "HHDFS76330000", {"NDAY": "0", "VOL_RANG": "0"})
RANK_VOLUME_POWER = ("/uapi/overseas-stock/v1/ranking/volume-power", "HHDFS76280000", {"NDAY": "0", "VOL_RANG": "0"})


def _merge_rank_metrics(target: dict[str, Any], row: dict[str, Any], *, source: str) -> None:
    sym = row_symbol(row)
    if not sym:
        return
    entry = target.setdefault(sym, {})
    entry["ranking_sources"] = sorted(set(entry.get("ranking_sources", [])) | {source})
    for field, keys in (
        ("volume_growth_pct", ("vol_inrt", "vol_incr_rate", "inrt", "rate", "growth_rate", "vol_grate")),
        ("trading_value_growth_pct", ("tamt_inrt", "pbmn_inrt", "tr_inrt", "growth_rate", "rate")),
        ("execution_strength", ("buy_pwr", "buy_strn", "strn", "power", "buy_strength", "vol_pwr")),
        ("intraday_volume", ("tvol", "acml_vol", "volume", "vol")),
        ("intraday_trading_value", ("tamt", "tr_pbmn", "acml_tr_pbmn", "evol_amt", "pbmn")),
        ("last_price", ("last", "stck_prpr", "last_price", "prpr")),
        ("intraday_change_pct", ("rate", "prdy_ctrt", "chg_rate")),
    ):
        value = first_num(row, *keys)
        if not math.isnan(value) and field not in entry:
            entry[field] = value


class UsMomentumRankingCache:
    """거래소별 KIS 순위 API를 1회 조회해 심볼별 보조 지표를 캐시한다."""

    def __init__(self) -> None:
        self._loaded: set[str] = set()
        self._by_symbol: dict[str, dict[str, Any]] = {}

    def _fetch_ranking(self, excd: str, path: str, tr_id: str, extra: dict[str, str], source: str) -> None:
        params = {"AUTH": "", "EXCD": excd, "KEYB": "", **extra}
        result = kis_us_request(path, tr_id, params)
        if not result.get("ok"):
            return
        payload = result.get("payload") or {}
        for key in ("output2", "output1", "output"):
            block = payload.get(key)
            if isinstance(block, list):
                for row in block:
                    if isinstance(row, dict):
                        _merge_rank_metrics(self._by_symbol, row, source=source)
            elif isinstance(block, dict):
                _merge_rank_metrics(self._by_symbol, block, source=source)

    def ensure_exchange(self, excd: str) -> None:
        if excd in self._loaded:
            return
        self._loaded.add(excd)
        self._fetch_ranking(excd, *RANK_VOLUME_SURGE, source="kis_volume_surge")
        self._fetch_ranking(excd, *RANK_TRADE_PBMN, source="kis_trade_pbmn")
        self._fetch_ranking(excd, *RANK_TRADE_GROWTH, source="kis_trade_growth")
        self._fetch_ranking(excd, *RANK_VOLUME_POWER, source="kis_volume_power")

    def lookup(self, symbol: str, excd: str) -> dict[str, Any]:
        self.ensure_exchange(excd)
        return dict(self._by_symbol.get(normalize_us_ticker(symbol), {}))


def _execution_strength_from_ccnl(rows: list[dict[str, Any]]) -> float:
    buy_qty = 0.0
    sell_qty = 0.0
    for row in rows:
        qty = first_num(row, "tvol", "ccld_qty", "qty", "exec_qty", "vol", default=0.0)
        if math.isnan(qty) or qty <= 0:
            continue
        side = str(row.get("ttyp") or row.get("trad_dvsn") or row.get("buy_sell") or row.get("sll_buy_dvsn") or "").strip().upper()
        if side in {"1", "B", "BUY", "02", "매수"}:
            buy_qty += qty
        elif side in {"2", "S", "SELL", "01", "매도"}:
            sell_qty += qty
    total = buy_qty + sell_qty
    if total <= 0:
        return math.nan
    return buy_qty / total * 100.0


def fetch_kis_us_ccnl_metrics(symbol: str, excd: str) -> dict[str, Any]:
    sym = normalize_us_ticker(symbol)
    result = kis_us_request(
        US_CCNL_PATH,
        US_CCNL_TR_ID,
        {"EXCD": excd, "TDAY": "1", "SYMB": sym, "AUTH": "", "KEYB": ""},
    )
    if not result.get("ok"):
        return {"execution_strength": math.nan, "flow_data_source": "kis_us_ccnl"}
    payload = result.get("payload") or {}
    rows = payload.get("output1")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        rows = payload_outputs(payload)
    strength = _execution_strength_from_ccnl(rows if isinstance(rows, list) else [])
    return {
        "execution_strength": strength,
        "flow_data_source": "kis_us_ccnl",
    }


def _optional_num(value: Any) -> float:
    if value is None:
        return math.nan
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "nat", "-"}:
        return math.nan
    return first_num({"v": value}, "v")


def _quote_from_realtime_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    out: dict[str, Any] = {}
    for src_key, dst in (
        ("last_price", "last_price"),
        ("intraday_change_pct", "intraday_change_pct"),
        ("intraday_volume", "intraday_volume"),
        ("intraday_trading_value", "intraday_trading_value"),
        ("quote_source", "quote_source"),
    ):
        if src_key in row and str(row.get(src_key, "")).strip() not in {"", "nan", "None"}:
            out[dst] = row.get(src_key)
    return out


def _orderbook_pressure(orderbook: dict[str, Any] | None) -> float:
    if not orderbook:
        return math.nan
    imbalance = first_num(orderbook, "orderbook_imbalance")
    if not math.isnan(imbalance):
        return imbalance
    bid = first_num(orderbook, "bid_total_volume", default=0.0)
    ask = first_num(orderbook, "ask_total_volume", default=0.0)
    total = bid + ask
    if total <= 0:
        return math.nan
    return (bid - ask) / total


def _momentum_score(
    *,
    change_pct: float,
    volume_growth: float,
    trading_value_growth: float,
    execution_strength: float,
    orderbook_pressure: float,
) -> float:
    parts: list[float] = []
    if not math.isnan(change_pct):
        parts.append(max(-15.0, min(15.0, change_pct)))
    if not math.isnan(volume_growth):
        parts.append(max(-20.0, min(20.0, volume_growth / 5.0)))
    if not math.isnan(trading_value_growth):
        parts.append(max(-20.0, min(20.0, trading_value_growth / 5.0)))
    if not math.isnan(execution_strength):
        parts.append(max(-15.0, min(15.0, (execution_strength - 50.0) / 3.0)))
    if not math.isnan(orderbook_pressure):
        parts.append(max(-10.0, min(10.0, orderbook_pressure * 20.0)))
    if not parts:
        return math.nan
    return max(0.0, min(100.0, 50.0 + sum(parts)))


def fetch_intraday_us_momentum_flow(
    symbol: str,
    market: str,
    *,
    target_row: dict[str, Any] | None = None,
    ranking_cache: UsMomentumRankingCache | None = None,
    realtime_row: dict[str, Any] | None = None,
    orderbook_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sym = normalize_us_ticker(symbol)
    base: dict[str, Any] = {
        "flow_mode": "us_momentum",
        "foreign_net_buy": None,
        "institution_net_buy": None,
        "individual_net_buy": None,
        "program_net_buy": None,
        "flow_fetch_status": "no_data",
        "flow_failure_reason": "no_data",
        "flow_data_source": "kis_us_momentum",
        "last_price": None,
        "intraday_change_pct": None,
        "intraday_volume": None,
        "intraday_trading_value": None,
        "volume_growth_pct": None,
        "trading_value_growth_pct": None,
        "execution_strength": None,
        "orderbook_pressure": None,
        "intraday_momentum_score": None,
    }
    if not sym:
        base.update({"flow_fetch_status": "invalid_symbol", "flow_failure_reason": "invalid_symbol"})
        return base

    cache = ranking_cache or UsMomentumRankingCache()
    quote = _quote_from_realtime_row(realtime_row)
    quote_source = str(quote.get("quote_source", "") or "")
    if not quote.get("last_price"):
        api_quote = fetch_kis_us_quote_api(sym, target_row=target_row)
        if api_quote.get("ok"):
            quote = {
                "last_price": api_quote.get("last_price"),
                "intraday_change_pct": api_quote.get("intraday_change_pct"),
                "intraday_volume": api_quote.get("intraday_volume"),
                "intraday_trading_value": api_quote.get("intraday_trading_value"),
                "quote_source": api_quote.get("quote_source", "kis_us_quote"),
            }
            quote_source = str(quote.get("quote_source", ""))

    rank_metrics: dict[str, Any] = {}
    ccnl_strength = math.nan
    used_excd = ""
    for excd in kis_us_exchange_candidates(sym, target_row):
        used_excd = excd
        rank_metrics = cache.lookup(sym, excd)
        ccnl = fetch_kis_us_ccnl_metrics(sym, excd)
        ccnl_strength = first_num(ccnl, "execution_strength")
        if rank_metrics or not math.isnan(ccnl_strength):
            break

    last_price = _optional_num(quote.get("last_price")) if quote else math.nan
    change_pct = _optional_num(quote.get("intraday_change_pct")) if quote else math.nan
    volume = _optional_num(quote.get("intraday_volume")) if quote else math.nan
    trading_value = _optional_num(quote.get("intraday_trading_value")) if quote else math.nan
    if math.isnan(volume):
        volume = first_num(rank_metrics, "intraday_volume")
    if math.isnan(trading_value):
        trading_value = first_num(rank_metrics, "intraday_trading_value")
    if math.isnan(last_price):
        last_price = first_num(rank_metrics, "last_price")
    if math.isnan(change_pct):
        change_pct = first_num(rank_metrics, "intraday_change_pct")

    volume_growth = first_num(rank_metrics, "volume_growth_pct")
    trading_value_growth = first_num(rank_metrics, "trading_value_growth_pct")
    execution = first_num(rank_metrics, "execution_strength")
    if math.isnan(execution):
        execution = ccnl_strength
    pressure = _orderbook_pressure(orderbook_row)
    momentum = _momentum_score(
        change_pct=change_pct,
        volume_growth=volume_growth,
        trading_value_growth=trading_value_growth,
        execution_strength=execution,
        orderbook_pressure=pressure,
    )

    sources: list[str] = []
    if quote_source:
        sources.append(quote_source)
    if orderbook_row and _truthy_orderbook(orderbook_row):
        sources.append(str(orderbook_row.get("orderbook_data_source", "kis_us_orderbook")))
    for src in rank_metrics.get("ranking_sources", []):
        sources.append(str(src))
    if not math.isnan(ccnl_strength):
        sources.append("kis_us_ccnl")
    flow_source = "+".join(dict.fromkeys(s for s in sources if s)) or "kis_us_momentum"

    def _present(value: float) -> bool:
        return value is not None and not (isinstance(value, float) and math.isnan(value))

    has_any = any(
        _present(x)
        for x in (last_price, change_pct, volume, trading_value, volume_growth, trading_value_growth, execution, pressure, momentum)
    )
    if has_any:
        base.update({
            "flow_fetch_status": "success",
            "flow_failure_reason": "",
            "flow_data_source": flow_source,
            "last_price": None if math.isnan(last_price) else last_price,
            "intraday_change_pct": None if math.isnan(change_pct) else change_pct,
            "intraday_volume": None if math.isnan(volume) else volume,
            "intraday_trading_value": None if math.isnan(trading_value) else trading_value,
            "volume_growth_pct": None if math.isnan(volume_growth) else volume_growth,
            "trading_value_growth_pct": None if math.isnan(trading_value_growth) else trading_value_growth,
            "execution_strength": None if math.isnan(execution) else execution,
            "orderbook_pressure": None if math.isnan(pressure) else pressure,
            "intraday_momentum_score": None if math.isnan(momentum) else momentum,
            "kis_exchange_code": used_excd,
        })
        return base

    base.update({
        "flow_fetch_status": "no_data",
        "flow_failure_reason": "api_response_empty",
        "flow_data_source": flow_source,
    })
    return base


def _truthy_orderbook(row: dict[str, Any]) -> bool:
    return str(row.get("orderbook_data_available", "")).strip().lower() in {"true", "1", "1.0", "yes", "y"}
