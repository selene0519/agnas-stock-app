"""국면 라벨이 한 체계로만 기록·해석되는지 지킨다.

2026-07-29 실측: 저널 880건의 `market_regime_at_signal`이
    횡보장 424 / BULL 236 / SIDE 150 / 약세장 70
으로 갈려 있었다. 한글 라벨과 영문 코드가 **같은 컬럼**에 섞여 국면별
집계가 전부 어긋났다 — 같은 국면이 여러 버킷으로 쪼개졌다.

원인은 판정 경로가 둘이었던 것이다(생성기는 한글, 다른 경로는 영문).
그래서 두 가지를 고정한다:
  * 생성기는 **정규 코드**(BULL/SIDE/BEAR)를 쓴다. 사람이 읽을 라벨은 별도 필드.
  * 읽는 쪽 정규화 매핑은 `scripts/regime_labels.py` **한 곳**에만 둔다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
GENERATORS = [ROOT / "scripts" / "generate_kr_recommendations.py",
              ROOT / "scripts" / "generate_us_recommendations.py"]


def test_generators_write_canonical_code_not_korean_label() -> None:
    for p in GENERATORS:
        s = p.read_text(encoding="utf-8")
        assert '"marketRegime": regime_type,' in s, (
            f"{p.name}이 marketRegime에 정규 코드를 안 쓴다")
        assert '"marketRegime": regime_label,' not in s, (
            f"{p.name}이 한글 라벨을 marketRegime에 쓴다 — 원장이 다시 섞인다")
        assert '"marketRegimeLabel": regime_label,' in s, (
            f"{p.name}에 사람이 읽을 라벨 필드가 없다")


def test_normalizer_handles_every_form_seen_in_the_ledger() -> None:
    from regime_labels import normalize
    assert normalize("횡보장") == "SIDE"
    assert normalize("약세장") == "BEAR"
    assert normalize("강세장") == "BULL"
    assert normalize("BULL") == "BULL"
    assert normalize("SIDE") == "SIDE"
    assert normalize("RISK_ON") == "BULL"
    assert normalize("RISK_OFF") == "BEAR"
    assert normalize("NEUTRAL") == "SIDE"


def test_unknown_label_is_none_not_guessed() -> None:
    """모르는 표기를 SIDE로 뭉개면 집계가 조용히 틀린다."""
    from regime_labels import normalize
    assert normalize("") is None
    assert normalize(None) is None
    assert normalize("XXX") is None


def test_mapping_lives_in_one_place_only() -> None:
    """스크립트마다 사본을 들면 하나가 낡는 순간 조용히 갈린다."""
    s = (ROOT / "scripts" / "analyze_live_axes.py").read_text(encoding="utf-8")
    assert "from regime_labels import" in s
    assert '"횡보장": "SIDE"' not in s, "사본 매핑이 남아 있다"
