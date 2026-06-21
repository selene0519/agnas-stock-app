"""
KR 종목 재무 데이터 보강 (yfinance .info)
sector_map_kr.csv 102종목 → reports/dart_financial_data_kr.csv

fetch_dart_financials.py(DART 공시 데이터, 더 신뢰도 높음)와 동일한 CSV를 공유한다.
DART가 이미 채운 필드는 보존하고, 비어 있는 필드만 yfinance 값으로 보강한다
(전체 덮어쓰기 금지 — 과거 DART 재무 원본을 yfinance가 지워버리던 버그 수정).

실행: python scripts/fetch_kr_financial_data.py
"""
from __future__ import annotations
import csv, sys, time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH  = ROOT / "reports" / "dart_financial_data_kr.csv"
SECTOR_MAP = ROOT / "data" / "sector_map_kr.csv"

# fetch_dart_financials.py의 FIELDNAMES와 합집합 (DART 전용 필드 보존 + div 추가)
FIELDNAMES = [
    "symbol", "corp_code", "name", "year",
    "revenue", "operating_income", "net_income", "total_equity", "total_debt",
    "total_assets", "current_assets", "current_liabilities", "retained_earnings",
    "eps", "eps_prev", "per", "pbr", "shares_outstanding", "market_cap",
    "roe", "debt_ratio", "operating_margin", "net_margin",
    "revenue_growth", "eps_growth", "peg", "div",
    "quality_score", "value_score", "growth_score",
    "updatedAt",
]

# DART가 이미 값을 채웠으면 yfinance로 덮어쓰지 않는 필드 (DART가 더 신뢰도 높음)
_FILL_ONLY_IF_MISSING = {
    "per", "pbr", "eps", "roe", "debt_ratio", "operating_margin", "net_margin",
    "revenue_growth", "eps_growth", "peg", "value_score", "growth_score", "quality_score",
}


def _is_empty(v) -> bool:
    return v is None or str(v).strip() in ("", "None", "nan", "-")


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _safe(info: dict, key: str, mult: float = 1.0) -> float | None:
    v = info.get(key)
    if v is None or str(v).lower() in {"none", "nan", "inf", "-"}:
        return None
    try:
        f = float(v) * mult
        return None if (f != f) else round(f, 4)  # NaN check
    except Exception:
        return None


def _score_value(per, pbr) -> float | None:
    if per is None and pbr is None:
        return None
    s = 50.0
    if per is not None:
        if per < 8:    s += 25
        elif per < 12: s += 18
        elif per < 18: s += 10
        elif per < 25: s += 3
        elif per > 35: s -= 15
    if pbr is not None:
        if pbr < 0.8:  s += 20
        elif pbr < 1.5: s += 12
        elif pbr < 2.5: s += 5
        elif pbr > 5.0: s -= 12
    return round(max(0.0, min(100.0, s)), 1)


def _score_growth(rev_g, earn_g) -> float | None:
    if rev_g is None and earn_g is None:
        return None
    s = 50.0
    if rev_g is not None:
        if rev_g > 0.3:   s += 20
        elif rev_g > 0.1: s += 12
        elif rev_g > 0:   s += 5
        elif rev_g < -0.1: s -= 12
    if earn_g is not None:
        if earn_g > 0.5:  s += 20
        elif earn_g > 0.2: s += 12
        elif earn_g > 0:  s += 5
        elif earn_g < -0.2: s -= 15
    return round(max(0.0, min(100.0, s)), 1)


def _score_quality(roe, debt_ratio, op_margin) -> float | None:
    if roe is None and debt_ratio is None and op_margin is None:
        return None
    s = 50.0
    if roe is not None:
        if roe > 0.20:   s += 20
        elif roe > 0.12: s += 12
        elif roe > 0.06: s += 5
        elif roe < 0:    s -= 15
    if debt_ratio is not None:
        if debt_ratio < 30:   s += 15
        elif debt_ratio < 80: s += 8
        elif debt_ratio > 200: s -= 15
        elif debt_ratio > 150: s -= 8
    if op_margin is not None:
        if op_margin > 0.20:   s += 15
        elif op_margin > 0.10: s += 8
        elif op_margin > 0:    s += 3
        elif op_margin < -0.05: s -= 12
    return round(max(0.0, min(100.0, s)), 1)


def fetch_financial_data() -> None:
    try:
        import yfinance as yf
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "yfinance", "-q"])
        import yfinance as yf

    symbols_rows = _read_csv(SECTOR_MAP)
    symbols = [(r["symbol"], r.get("name", ""), r.get("market", "kr"))
               for r in symbols_rows if r.get("symbol")]
    print(f"[재무수집] {len(symbols)}종목 yfinance 조회 시작")

    today_str = date.today().isoformat()
    today_year = today_str[:4]

    # 기존 CSV(DART 수집분 포함) 로드 — symbol+year 키로 병합, 전체 덮어쓰기 금지
    existing_by_key: dict[tuple[str, str], dict] = {}
    for r in _read_csv(OUT_PATH):
        key = (str(r.get("symbol", "")).strip().zfill(6), str(r.get("year", "")).strip())
        existing_by_key[key] = r

    ok = fail = 0

    for sym, name, market in symbols:
        sym6 = sym.strip().zfill(6)
        key = (sym6, today_year)
        row: dict = dict(existing_by_key.get(key, {}))
        row["symbol"] = sym6
        row["name"] = name or row.get("name", "")
        row["year"] = today_year
        row["updatedAt"] = today_str

        # KS (KOSPI) 먼저, 실패 시 KQ (KOSDAQ) 시도
        info = {}
        for suffix in (".KS", ".KQ"):
            try:
                ticker_info = yf.Ticker(f"{sym}{suffix}").info
                if ticker_info and ticker_info.get("regularMarketPrice"):
                    info = ticker_info
                    break
                # 가격 없어도 재무 데이터 있으면 사용
                if ticker_info and (ticker_info.get("returnOnEquity") or
                                    ticker_info.get("forwardPE") or
                                    ticker_info.get("priceToBook")):
                    info = ticker_info
                    break
            except Exception:
                pass

        if info:
            per = _safe(info, "forwardPE") or _safe(info, "trailingPE")
            pbr = _safe(info, "priceToBook")
            roe = _safe(info, "returnOnEquity", mult=100.0)  # 소수 → %
            debt = _safe(info, "debtToEquity")               # yfinance는 % 단위
            op_m = _safe(info, "operatingMargins")           # 소수 단위
            net_m = _safe(info, "profitMargins")
            rev_g = _safe(info, "revenueGrowth")
            earn_g = _safe(info, "earningsGrowth")
            eps = _safe(info, "trailingEps")
            div = _safe(info, "dividendYield", mult=100.0)

            new_vals = {
                "per": per,
                "pbr": pbr,
                "eps": eps,
                "roe": roe,
                "div": div,
                "debt_ratio": debt,
                "operating_margin": round(op_m * 100, 2) if op_m else None,
                "net_margin": round(net_m * 100, 2) if net_m else None,
                "revenue_growth": round(rev_g * 100, 2) if rev_g else None,
                "eps_growth": round(earn_g * 100, 2) if earn_g else None,
                "peg": _safe(info, "pegRatio"),
                "value_score":   _score_value(per, pbr),
                "growth_score":  _score_growth(rev_g, earn_g),
                "quality_score": _score_quality(
                    roe / 100 if roe else None,
                    debt, op_m
                ),
            }
            for k, v in new_vals.items():
                if v is None:
                    continue
                # DART가 이미 채운 값이면 보존, div처럼 DART에 없는 필드는 항상 갱신
                if k not in _FILL_ONLY_IF_MISSING or _is_empty(row.get(k)):
                    row[k] = v
            ok += 1
        else:
            fail += 1

        existing_by_key[key] = row
        if (ok + fail) % 20 == 0:
            print(f"  {ok+fail}/{len(symbols)}: ok={ok} fail={fail}")
        time.sleep(0.1)  # API 부하 방지

    # CSV 저장 (DART 전용 필드를 가진 다른 연도/종목 행도 그대로 보존)
    results = list(existing_by_key.values())
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    per_ok  = sum(1 for r in results if r.get("per"))
    pbr_ok  = sum(1 for r in results if r.get("pbr"))
    roe_ok  = sum(1 for r in results if r.get("roe"))
    val_ok  = sum(1 for r in results if r.get("value_score"))
    print(f"\n[완료] {len(results)}종목 병합 저장 / ok={ok} fail={fail}")
    print(f"  PER:{per_ok} PBR:{pbr_ok} ROE:{roe_ok} 가치점수:{val_ok}")
    print(f"  → {OUT_PATH}")


if __name__ == "__main__":
    fetch_financial_data()
