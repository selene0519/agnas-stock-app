"""두 원장이 서로 다른 모집단이라는 사실을 코드로 고정한다.

2026-07-29 실측: clean window 정산 표본이 한쪽은 3건, 다른 쪽은 65건(20배)이었고
고유 예측 교집합은 854 vs 880 중 **88건뿐**이었다. 같은 걸 다르게 세는 게 아니라
서로 다른 걸 담고 있다:

  A 추천 원장  = `_recommendations_payload(limit=50)` — 서빙 경로, 필터 없음
  B VTJ 저널   = 리포트 CSV -> _reject_reason -> _unique_by_symbol[:5]

이 구분이 흐려지면 "승률이 3배 다르다"(2026-07-28) 같은 혼란이 되풀이된다.
그래서 테스트는 숫자가 아니라 **정의와 소비자 배선**을 지킨다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_reconciliation_report_names_both_denominators() -> None:
    mod = _load("reconcile_ledgers", "scripts/reconcile_ledgers.py")
    data = mod.build()
    rec = data["recommendation"]
    # 엣지 판정과 화면 표시가 서로 다른 분모를 쓴다는 비대칭이 명시돼야 한다.
    assert rec["edgeVerdictDenominator"] in ("ledgerA", "ledgerB")
    assert rec["displayDenominator"] in ("ledgerA", "ledgerB")
    assert rec["edgeVerdictDenominator"] != rec["displayDenominator"], (
        "두 분모가 같아졌다면 구분이 사라진 것이다 — 그렇다면 문서와 소비자 배선을 "
        "같이 정리해야 한다."
    )
    for key in ("ledgerA", "ledgerB"):
        d = data[key]
        assert d["question"], f"{key}에 '무엇을 묻는 원장인지'가 없다"
        assert d["captures"], f"{key}에 캡처 방식 설명이 없다"
        assert d["consumers"], f"{key}의 소비자 목록이 비었다"


def test_win_rate_source_stays_on_ledger_a() -> None:
    """화면 승률(strategy_win_rates.json)은 A에서 나와야 한다.

    A는 사용자가 실제로 보는 카드 전체다. 여기를 B로 바꾸면 화면 승률이
    '상위 5개만 샀을 때'를 말하게 되는데, 카드에는 그보다 훨씬 많이 떠 있다.
    """
    src = (ROOT / "scripts" / "update_win_rates.py").read_text(encoding="utf-8")
    assert "virtual_validation_results.csv" in src
    assert "virtual_trade_journal" not in src, (
        "승률 소스가 VTJ(B)로 바뀌었다 — 화면 분모가 조용히 부분집합이 된다"
    )


def test_live_calibration_source_stays_on_ledger_b() -> None:
    """라이브 보정(게이트 근거)은 B에서 나와야 한다.

    게이트가 답해야 하는 질문은 '따라 샀을 때의 기댓값'이고, 그건 상위 N
    부분집합이다. 여기를 A로 바꾸면 아무도 사지 않는 50종목 목록으로
    게이트를 정하게 된다.
    """
    src = (ROOT / "scripts" / "build_live_calibration.py").read_text(encoding="utf-8")
    assert "virtual_trade_evaluations.csv" in src
    assert "virtual_trade_journal.csv" in src


def test_ledgers_are_not_assumed_to_overlap() -> None:
    """교집합이 작은 걸 '버그'로 오해하지 않도록 리포트가 설명을 달아야 한다."""
    mod = _load("reconcile_ledgers", "scripts/reconcile_ledgers.py")
    data = mod.build()
    o = data["overlap"]
    assert {"sharedPredictions", "onlyA", "onlyB"} <= set(o)
    assert o["note"], "교집합이 작은 이유 설명이 없다"
