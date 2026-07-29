"""재무 데이터 로딩 회귀 테스트 — 연도 선택이 아니라 **필드 병합**이어야 한다.

`reports/dart_financial_data_kr.csv`에는 writer가 둘이고 서로 다른 필드를 채운다:

  fetch_dart_financials.py    year=**회계연도**(2025/2024)
                              원시 재무제표: revenue/operating_income/
                              net_income/total_equity
  fetch_kr_financial_data.py  year=**달력연도**(오늘이 2026이면 2026)
                              yfinance 시장 지표: per/revenue_growth/
                              eps_growth/div/market_cap

2026-07-29 실측 (KR):
            revenue  operating_income   per   revenue_growth   div
  2025행    96/102       102/102       0/102      0/102       0/102
  2026행     0/107         0/107      84/107     88/107      69/107

어느 한 해도 단독으로는 불완전하다. 실제로 두 번 틀렸다:
  ① 원래 로더는 year 문자열 비교로 2026을 골라 **원시 재무제표가 106종목 중
     1종목만** 살아 있었다 (PER/ROE·'저평가 가치' 태그가 사실상 죽어 있었다).
  ② 그걸 "값 있는 최신 연도"로 고쳤더니 이번엔 2025가 뽑혀 per/성장률/배당이
     0이 됐다 — '저PER' 태그가 쓰는 바로 그 값이다.

그래서 최신 연도를 기준으로 두고 **빈 칸만 과거 연도에서 채운다.**
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mone-web-app" / "backend"

FIELDS = ["symbol", "corp_code", "name", "year", "revenue", "operating_income",
          "net_income", "total_equity", "eps", "per", "roe", "revenue_growth", "div"]


@pytest.fixture()
def scanner():
    import sys
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app.engine import quant_scanner
    return quant_scanner


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "reports" / "dart_financial_data_kr.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows([{k: r.get(k, "") for k in FIELDS} for r in rows])
    return tmp_path


def test_statements_and_market_ratios_are_merged_across_years(tmp_path, scanner) -> None:
    """핵심 회귀: 회계연도 재무제표 + 달력연도 시장지표가 **둘 다** 살아야 한다."""
    root = _write(tmp_path, [
        # DART: 원시 재무제표만
        {"symbol": "005930", "year": "2025", "revenue": "300000",
         "operating_income": "50000", "net_income": "40000", "total_equity": "200000",
         "roe": "15.2"},
        # yfinance: 시장 지표만 (달력연도라 항상 더 최신으로 정렬된다)
        {"symbol": "005930", "year": "2026", "per": "12.5",
         "revenue_growth": "8.1", "div": "2.3"},
    ])
    got = scanner._load_dart_financials(root, "kr")["005930"]
    # 어느 한쪽도 잃으면 안 된다.
    assert got["revenue"] == "300000"
    assert got["operating_income"] == "50000"
    assert got["per"] == "12.5"
    assert got["revenue_growth"] == "8.1"
    assert got["div"] == "2.3"
    assert got["roe"] == "15.2"


def test_newer_value_wins_when_both_years_have_the_field(tmp_path, scanner) -> None:
    """같은 필드가 양쪽에 있으면 최신이 이긴다 — 옛 수치가 새 수치를 덮으면 안 된다."""
    root = _write(tmp_path, [
        {"symbol": "005930", "year": "2025", "roe": "10.0", "revenue": "300000"},
        {"symbol": "005930", "year": "2026", "roe": "15.0"},
    ])
    got = scanner._load_dart_financials(root, "kr")["005930"]
    assert got["roe"] == "15.0"
    assert got["revenue"] == "300000"


def test_blank_newer_field_does_not_shadow_filled_older_field(tmp_path, scanner) -> None:
    """빈 칸은 값이 아니다. 최신 행이 비었으면 과거 값이 살아야 한다."""
    root = _write(tmp_path, [
        {"symbol": "005930", "year": "2025", "operating_income": "50000"},
        {"symbol": "005930", "year": "2026", "operating_income": ""},
    ])
    got = scanner._load_dart_financials(root, "kr")["005930"]
    assert got["operating_income"] == "50000"


def test_merged_years_are_recorded(tmp_path, scanner) -> None:
    """어느 연도들이 합쳐졌는지 남아야 '이 PER은 언제 값인가'를 되짚을 수 있다."""
    root = _write(tmp_path, [
        {"symbol": "005930", "year": "2025", "revenue": "300000"},
        {"symbol": "005930", "year": "2026", "per": "12.5"},
    ])
    got = scanner._load_dart_financials(root, "kr")["005930"]
    assert "2026" in got["_mergedYears"] and "2025" in got["_mergedYears"]


def test_symbol_without_leading_zero_is_also_keyed(tmp_path, scanner) -> None:
    root = _write(tmp_path, [{"symbol": "005930", "year": "2025", "revenue": "1"}])
    got = scanner._load_dart_financials(root, "kr")
    assert "005930" in got and "5930" in got


def test_real_repo_data_keeps_both_families_usable(scanner) -> None:
    """실제 레포 데이터에서 재무제표와 시장지표가 **동시에** 살아 있어야 한다.

    한쪽만 살아 있던 실패를 두 번 겪었으므로 둘 다 검사한다.
    """
    if not (ROOT / "reports" / "dart_financial_data_kr.csv").exists():
        pytest.skip("dart_financial_data_kr.csv 없음")
    got = scanner._load_dart_financials(ROOT, "kr")
    syms = [k for k in got if k.isdigit() and len(k) == 6]
    if not syms:
        pytest.skip("KR 재무 행 없음")

    def cov(field: str) -> int:
        return sum(1 for s in syms
                   if str(got[s].get(field) or "").strip() not in ("", "nan", "None", "-"))

    assert cov("operating_income") >= len(syms) * 0.5, (
        f"원시 재무제표가 {cov('operating_income')}/{len(syms)}뿐 — "
        "달력연도 행이 회계연도 행을 덮고 있을 가능성"
    )
    assert cov("per") >= len(syms) * 0.3, (
        f"PER이 {cov('per')}/{len(syms)}뿐 — "
        "회계연도 행이 달력연도 시장지표를 덮고 있을 가능성"
    )
