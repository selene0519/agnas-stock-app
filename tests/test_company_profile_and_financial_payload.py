"""기업 정보(사업 내용)·재무 payload 배선 회귀 테스트.

사진으로 지적받은 것: 앱이 차트·공시·수급은 보는데 **실적·재무상태·밸류에이션·
사업 내용**은 사용자에게 안 보여줬다. 파보니 두 군데가 끊겨 있었다.

  ① `_load_dart_financials`가 연도를 하나만 고르는 바람에 재무제표와 시장지표
     중 한쪽이 항상 죽었다 (test_dart_financial_year_selection.py가 담당).
  ② DART 주입이 비율 5개만 item에 넣어서 revenue/operatingProfit/netIncome/
     성장률이 CSV에 있어도 payload까지 못 왔다 — 이 파일이 담당.
  ③ 사업 내용은 소스 자체가 없었다 → fetch_dart_company_profile.py 신설.

테스트는 "값이 맞다"가 아니라 **"끊긴 데 없이 끝까지 전달되는가"**를 지킨다.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mone-web-app" / "backend"


@pytest.fixture()
def scanner():
    import sys
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app.engine import quant_scanner
    return quant_scanner


def _write_profile(root: Path, rows: list[dict]) -> None:
    p = root / "data" / "fundamental" / "dart_company_profile_kr.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = ["symbol", "corp_code", "corp_name", "stock_name", "industryCode",
              "industryName", "establishedDate", "ceo", "homepage", "address",
              "businessSummary", "updatedAt"]
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows([{k: r.get(k, "") for k in fields} for r in rows])


def test_company_profile_loads_and_keys_both_symbol_forms(tmp_path, scanner) -> None:
    _write_profile(tmp_path, [{
        "symbol": "005930", "industryName": "전자부품 제조",
        "businessSummary": "전자부품 제조 · 1969년 설립", "establishedDate": "19690113",
    }])
    got = scanner._load_company_profiles(tmp_path, "kr")
    assert got["005930"]["businessSummary"] == "전자부품 제조 · 1969년 설립"
    assert "5930" in got, "선행 0을 뗀 키로도 찾을 수 있어야 한다"


def test_missing_profile_file_is_safe(tmp_path, scanner) -> None:
    """파일이 없으면 빈 맵. 화면은 '정보 없음'을 그리면 되고 죽으면 안 된다."""
    assert scanner._load_company_profiles(tmp_path, "kr") == {}


def test_profile_is_not_loaded_for_us(tmp_path, scanner) -> None:
    _write_profile(tmp_path, [{"symbol": "005930", "industryName": "x"}])
    assert scanner._load_company_profiles(tmp_path, "us") == {}


def test_dart_injection_covers_every_field_the_payload_reads() -> None:
    """DART 주입 매핑이 financial_keys를 전부 덮어야 한다.

    예전에는 비율 5개만 주입해서, CSV에 revenue/operatingProfit/netIncome이
    있어도 financialDataStatus가 DATA_PENDING으로 남고 화면에 실적이 안 떴다.
    매핑에서 항목이 빠지면 같은 일이 조용히 재발하므로 소스로 고정한다.
    """
    src = (BACKEND / "app" / "engine" / "quant_scanner.py").read_text(encoding="utf-8")

    # payload가 읽는 키 목록(financial_keys)
    start = src.index("financial_keys = (")
    payload_keys = set()
    for tok in src[start:src.index(")", start)].split('"')[1::2]:
        payload_keys.add(tok)

    # 주입 매핑에서 item 쪽 키만 모은다.
    inj_start = src.index("for dart_k, item_k in [")
    injected = set(src[inj_start:src.index("]", inj_start)].split('"')[1::2])

    # 주입 대상이 아닌 파생 지표(엔진이 계산)는 제외.
    derived = {"operatingProfitGrowth", "operatingCashFlow", "interestCoverage"}
    missing = payload_keys - injected - derived
    assert not missing, (
        f"payload가 읽는데 DART 주입에서 빠진 필드: {sorted(missing)} — "
        "CSV에 값이 있어도 화면까지 오지 않는다"
    )


def test_analysis_endpoint_exposes_profile_and_valuation() -> None:
    """분석 API 응답에 companyProfile/valuation 블록이 있어야 한다."""
    src = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '"companyProfile"' in src, "사업 내용 블록이 응답에 없다"
    assert '"valuation"' in src, "밸류에이션 블록이 응답에 없다"
    # 어느 시점 수치인지 밝히는 필드가 빠지면 사용자가 오래된 값을 최신으로 읽는다.
    assert '"sourceYears"' in src


def test_frontend_renders_company_card() -> None:
    panel = (ROOT / "mone-web-app" / "frontend" / "components"
             / "StockResearchPanel.tsx").read_text(encoding="utf-8")
    assert "기업 정보" in panel
    for label in ("PER", "PBR", "ROE", "배당수익률", "매출", "영업이익"):
        assert label in panel, f"기업 정보 카드에 {label}이 없다"
    # 값이 없을 때 빈 표를 그리면 고장으로 보인다.
    assert "아직 수집되지 않았습니다" in panel


def test_profile_output_is_in_ci_staging_allowlist() -> None:
    """allowlist에 빠지면 수집이 성공해도 산출물이 매번 버려진다."""
    sh = (ROOT / "scripts" / "ci_commit_app_data.sh").read_text(encoding="utf-8")
    assert "dart_company_profile_kr.csv" in sh
