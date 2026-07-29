"""재무 데이터 연도 선택 회귀 테스트.

2026-07-29 실측: `_load_dart_financials`가 year 문자열 비교로 **가장 최신 연도**를
골랐는데, 아직 수집되지 않은 회계연도(2026) 행이 껍데기로 107종목 들어 있었다.
그 빈 행이 채워진 2025 행을 덮어써서 **106종목 중 1종목만** 실제 재무값이
스캐너에 전달되고 있었다.

즉 PER/PBR/ROE, '저PER'·'저평가 가치' 스타일 태그, 재무 기반 점수가 사실상
죽어 있었는데 아무도 몰랐다 — 컬럼도 있고 파일도 최신이라 겉으로는 멀쩡했다.
(이 레포가 반복해서 당한 "최신성은 맞는데 내용이 비어 있다"의 또 다른 형태다.)

수정: "가장 최신"이 아니라 **"값이 있는 것 중 가장 최신"**을 고른다.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mone-web-app" / "backend"

FIELDS = ["symbol", "corp_code", "name", "year", "revenue", "operating_income",
          "net_income", "total_equity", "eps"]


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


def test_empty_newer_year_does_not_shadow_filled_older_year(tmp_path, scanner) -> None:
    """핵심 회귀: 빈 최신 연도가 채워진 과거 연도를 덮으면 안 된다."""
    root = _write(tmp_path, [
        {"symbol": "005930", "year": "2025", "revenue": "300000",
         "operating_income": "50000", "net_income": "40000", "total_equity": "200000"},
        # 아직 수집 안 된 회계연도 — 행은 있는데 값이 없다.
        {"symbol": "005930", "year": "2026", "revenue": "", "operating_income": "",
         "net_income": "", "total_equity": ""},
    ])
    got = scanner._load_dart_financials(root, "kr")
    assert got["005930"]["year"] == "2025"
    assert got["005930"]["revenue"] == "300000"


def test_newer_year_wins_when_both_have_values(tmp_path, scanner) -> None:
    """둘 다 채워져 있으면 최신이 이겨야 한다 — 오래된 값에 고착되면 안 된다."""
    root = _write(tmp_path, [
        {"symbol": "005930", "year": "2025", "revenue": "300000",
         "operating_income": "50000", "net_income": "40000", "total_equity": "200000"},
        {"symbol": "005930", "year": "2026", "revenue": "350000",
         "operating_income": "60000", "net_income": "48000", "total_equity": "220000"},
    ])
    got = scanner._load_dart_financials(root, "kr")
    assert got["005930"]["year"] == "2026"
    assert got["005930"]["revenue"] == "350000"


def test_all_empty_keeps_newest_row(tmp_path, scanner) -> None:
    """전부 비었으면 최신을 남겨 '언제 시도됐는지'는 보존한다."""
    root = _write(tmp_path, [
        {"symbol": "005930", "year": "2025"},
        {"symbol": "005930", "year": "2026"},
    ])
    got = scanner._load_dart_financials(root, "kr")
    assert got["005930"]["year"] == "2026"


def test_real_repo_data_has_usable_coverage(scanner) -> None:
    """실제 레포 데이터에서 재무값이 전달되는 종목이 충분해야 한다.

    수정 전에는 106종목 중 1종목이었다. 이 검사가 다시 1로 떨어지면 재무 기반
    로직이 통째로 죽은 것이다.
    """
    src = ROOT / "reports" / "dart_financial_data_kr.csv"
    if not src.exists():
        pytest.skip("dart_financial_data_kr.csv 없음")
    got = scanner._load_dart_financials(ROOT, "kr")
    syms = [k for k in got if k.isdigit() and len(k) == 6]
    if not syms:
        pytest.skip("KR 재무 행 없음")
    filled = sum(
        1 for s in syms
        if str(got[s].get("operating_income") or "").strip() not in ("", "0", "nan", "None")
    )
    assert filled >= len(syms) * 0.5, (
        f"재무값이 전달되는 종목이 {filled}/{len(syms)}뿐이다 — "
        "빈 회계연도 행이 채워진 행을 덮고 있을 가능성이 높다"
    )
