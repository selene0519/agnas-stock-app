"""candidate_universe를 '시총 상위 + 거래대금 상위 소형주'로 확장한다.

발굴 렌즈/스크리너가 대형 주도주부터 '유동성 있는' 소형 발굴주까지 다루도록,
FinanceDataReader StockListing 에서 시가총액(Marcap)·거래대금(Amount)을 받아
  1) 시총 상위 TOP_CAP (대·중형주 — 주도주/눌림주/회복주용)
  2) (시총 상위 밖) 최소 거래대금 이상 & 거래대금 상위 소·중형주 TOP_LIQUID (발굴주용)
를 뽑아 candidate_universe_{market}.csv 에 병합한다.

안전장치:
- 기존 큐레이션 종목(테마/그룹 등)은 그대로 보존하고, 신규 종목만 추가한다.
- ETF/ETN/스팩/우선주는 이름 기준으로 제외한다.
- FDR 조회가 실패하거나 결과가 비정상적으로 적으면(< MIN_FETCH) 파일을 건드리지 않는다.

사용:
  python scripts/build_universe.py            # kr, us 모두
  python scripts/build_universe.py --market kr
  python scripts/build_universe.py --dry-run  # 파일 안 쓰고 요약만
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

# 규모 파라미터 (스코어링 상한 500·수집 부하 고려한 스윗스팟)
TOP_CAP = {"kr": 200, "us": 150}          # 시총 상위
TOP_LIQUID = {"kr": 250, "us": 150}       # 거래대금 상위 소형주
MIN_AMOUNT = {"kr": 1_000_000_000.0, "us": 3_000_000.0}  # 최소 일 거래대금 (KR 10억원 / US $3M)
MAX_TOTAL = {"kr": 500, "us": 350}
MIN_FETCH = 100                            # 이보다 적게 받아오면 비정상으로 보고 중단

CANDIDATE_COLUMNS = [
    "symbol", "name", "theme", "group", "type", "sector_proxy", "risk_level",
    "current_price", "last_price", "현재가", "quote_fallback_price", "실시간현재가",
    "quote_source", "quote_source_label", "data_status", "price_data_status",
    "current_price_source",
]

_EXCLUDE_NAME = re.compile(
    r"(ETF|ETN|리츠|REIT|스팩|SPAC|우$|우B$|\d우$|우선주|인버스|레버리지|2X|3X|곱버스)",
    re.IGNORECASE,
)


def _num(value: Any) -> float:
    try:
        text = re.sub(r"[^0-9.\-]", "", str(value or ""))
        return float(text) if text not in ("", "-", ".") else 0.0
    except Exception:
        return 0.0


def _norm_symbol(value: Any, market: str) -> str:
    text = str(value or "").strip().upper().replace(".KS", "").replace(".KQ", "")
    if market == "kr":
        digits = re.sub(r"\D", "", text)
        return digits.zfill(6) if 0 < len(digits) <= 6 else ""
    return text if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,12}", text) else ""


def select_universe(rows: list[dict[str, Any]], market: str) -> list[dict[str, str]]:
    """정규화된 리스팅 rows(symbol,name,marcap,amount)에서 최종 유니버스를 뽑는다.

    반환: [{symbol, name, type}] — type은 'core'(시총상위) 또는 'discovery'(유동성 소형주).
    이 함수는 네트워크 없이 순수 로직만 수행해 단위 검증이 가능하다.
    """
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        sym = _norm_symbol(r.get("symbol"), market)
        name = str(r.get("name") or "").strip()
        if not sym or not name or sym in seen:
            continue
        if _EXCLUDE_NAME.search(name):
            continue
        marcap = _num(r.get("marcap"))
        amount = _num(r.get("amount"))
        if marcap <= 0:
            continue
        seen.add(sym)
        clean.append({"symbol": sym, "name": name, "marcap": marcap, "amount": amount})

    by_cap = sorted(clean, key=lambda x: x["marcap"], reverse=True)
    top_cap = by_cap[: TOP_CAP.get(market, 200)]
    top_cap_syms = {x["symbol"] for x in top_cap}

    liquid_pool = [
        x for x in clean
        if x["symbol"] not in top_cap_syms and x["amount"] >= MIN_AMOUNT.get(market, 0.0)
    ]
    liquid = sorted(liquid_pool, key=lambda x: x["amount"], reverse=True)[: TOP_LIQUID.get(market, 250)]

    out: list[dict[str, str]] = []
    for x in top_cap:
        out.append({"symbol": x["symbol"], "name": x["name"], "type": "core"})
    for x in liquid:
        out.append({"symbol": x["symbol"], "name": x["name"], "type": "discovery"})
    return out[: MAX_TOTAL.get(market, 500)]


def _read_existing(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [dict(row) for row in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _fetch_krx() -> list[dict[str, Any]]:
    import FinanceDataReader as fdr  # type: ignore

    frame = fdr.StockListing("KRX")
    out: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        out.append({
            "symbol": row.get("Code") or row.get("Symbol") or row.get("Ticker"),
            "name": row.get("Name") or row.get("MarketName"),
            "marcap": row.get("Marcap") or row.get("MarketCap"),
            "amount": row.get("Amount") or row.get("TradingValue"),
        })
    return out


def _fetch_us() -> list[dict[str, Any]]:
    import FinanceDataReader as fdr  # type: ignore

    out: list[dict[str, Any]] = []
    for board in ("NASDAQ", "NYSE"):
        try:
            frame = fdr.StockListing(board)
        except Exception:
            continue
        for _, row in frame.iterrows():
            out.append({
                "symbol": row.get("Symbol") or row.get("Code") or row.get("Ticker"),
                "name": row.get("Name"),
                "marcap": row.get("MarketCap") or row.get("Marcap"),
                # US 리스팅엔 일 거래대금이 없어 시총을 유동성 대리값으로 사용
                "amount": row.get("MarketCap") or row.get("Marcap"),
            })
    return out


def build_market(market: str, dry_run: bool = False) -> dict[str, Any]:
    path = REPO / f"candidate_universe_{market}.csv"
    existing = _read_existing(path)
    existing_syms = {_norm_symbol(r.get("symbol"), market) for r in existing}
    existing_syms.discard("")

    raw = _fetch_krx() if market == "kr" else _fetch_us()
    if len(raw) < MIN_FETCH:
        return {"market": market, "status": "SKIP_LOW_FETCH", "fetched": len(raw),
                "kept_existing": len(existing)}

    selected = select_universe(raw, market)
    selected_map = {s["symbol"]: s for s in selected}

    # 기존 큐레이션 행은 그대로 보존, 선별된 신규 종목만 추가
    merged = list(existing)
    added = 0
    for sym, meta in selected_map.items():
        if sym in existing_syms:
            continue
        row = {col: "" for col in CANDIDATE_COLUMNS}
        row["symbol"] = sym
        row["name"] = meta["name"]
        row["type"] = meta["type"]
        row["risk_level"] = "중"
        row["theme"] = "자동선별"
        row["group"] = "발굴 후보" if meta["type"] == "discovery" else "대형 핵심"
        merged.append(row)
        added += 1

    result = {"market": market, "status": "OK", "fetched": len(raw),
              "selected": len(selected), "existing": len(existing),
              "added": added, "total": len(merged)}
    if dry_run:
        result["status"] = "DRY_RUN"
        return result

    # 안전장치: 병합 결과가 기존보다 적으면 쓰지 않음
    if len(merged) < len(existing):
        result["status"] = "SKIP_SHRINK"
        return result

    fields = list(dict.fromkeys(CANDIDATE_COLUMNS + [k for r in merged for k in r.keys()]))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in merged:
            writer.writerow({**{c: "" for c in fields}, **r})
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["kr", "us", "all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    markets = ["kr", "us"] if args.market == "all" else [args.market]
    for mk in markets:
        try:
            res = build_market(mk, dry_run=args.dry_run)
        except Exception as exc:
            res = {"market": mk, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        print(f"[build_universe] {datetime.now():%Y-%m-%d %H:%M} {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
