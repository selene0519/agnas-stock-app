"""포트폴리오 주의사항/대응 UI 표시 변환 테스트 (계산 로직 변경 없음)."""
from __future__ import annotations

import app


def _sample_summary() -> dict:
    return {
        "blocked_candidate_count": 206,
        "total_exposure_pct": 100.0,
        "max_expected_loss_pct": 9.0,
        "portfolio_warnings": [
            "C/금지 후보 206개는 포트폴리오 편입 불가",
            "총 포지션 노출 80% 초과",
            "전기차/성장주 섹터 과집중",
            "반도체/AI 섹터 과집중",
            "반도체 섹터 과집중",
            "반도체 부품 섹터 과집중",
            "예상 최대 손실 6% 이상",
        ],
        "portfolio_actions": [
            "C/금지 후보는 신규 편입 목록에서 제외",
            "추가 편입 전 현금 비중 확인",
            "전기차/성장주 섹터 신규 편입 제한",
            "반도체/AI 섹터 신규 편입 제한",
            "반도체 섹터 신규 편입 제한",
            "반도체 부품 섹터 신규 편입 제한",
            "손절 기준 재점검 및 포지션 축소",
        ],
    }


def test_sector_warnings_grouped_into_single_row():
    rows, raw_warnings, _ = app.prepare_portfolio_guidance_rows(_sample_summary())
    sector_rows = [r for r in rows if r["구분"] == "섹터 과집중"]
    assert len(sector_rows) == 1
    assert "전기차/성장주" in sector_rows[0]["주의사항"]
    assert "반도체 부품" in sector_rows[0]["주의사항"]
    assert sector_rows[0]["대응방안"] == "해당 섹터 신규 편입 제한"
    assert sum(1 for w in raw_warnings if "섹터 과집중" in w) >= 2


def test_summary_status_labels():
    pr = _sample_summary()
    assert app._portfolio_exposure_status_label(pr) in ("80% 초과", "100% 초과")
    assert "6%" in app._portfolio_max_loss_status_label(pr) or "%" in app._portfolio_max_loss_status_label(pr)
    label, sectors = app._portfolio_sector_concentration_status(pr)
    assert label == "있음"
    assert len(sectors) >= 2


def test_guidance_rows_have_three_columns():
    rows, _, _ = app.prepare_portfolio_guidance_rows(_sample_summary())
    assert rows
    for row in rows:
        assert set(row.keys()) == {"구분", "주의사항", "대응방안"}
        assert row["주의사항"]
        assert row["대응방안"]
