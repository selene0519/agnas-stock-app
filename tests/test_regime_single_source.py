"""국면 판정식이 **한 곳**에만 있게 지킨다.

2026-07-30 실측으로 드러난 사고 계열(같은 뿌리로 세 번 반복됐다):

1. `regime_kr`을 검증된 정의로 고쳤는데, 추천 생성기
   `generate_kr_recommendations._load_market_regime`이 옛 정의(MA20 이격 +
   5일 모멘텀)를 **자기 안에 복제**해 두고 있었다. 15년 KOSPI로 맞춰보니
   **일치가 46.2%**(3,621일 중 1,949일 불일치). 검증정의가 SIDE(최악)로 본
   653일을 옛 정의는 BULL로 불러 EV를 1.13~1.19배 부풀렸다 — 하필 가장 나쁜
   국면에서 낙관 쪽으로 틀리는 방향이다.

2. 미장은 SPY/QQQ/DIA 3지수 투표를 옛 정의로 돌렸다(일치 51.1%). 게다가
   `_price_band`가 국장 모듈 함수라 **미장 EV가 KOSPI 국면·국장 승률표로**
   보정됐다. 두 시장의 국면 순서는 정반대다.

3. 판정기에 거래량 확인을 넣으면서 **승률표를 다시 내지 않아**, 판정기는
   `trend60+거래량`인데 표는 `trend60단독` 값이었다.

세 번 다 "값을 다른 곳에 복제해 두고 한쪽만 고쳤다"가 원인이다.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

GENERATORS = [ROOT / "scripts" / "generate_kr_recommendations.py",
              ROOT / "scripts" / "generate_us_recommendations.py"]


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_generators_delegate_classification() -> None:
    """생성기가 판정식을 자기 안에 다시 구현하면 안 된다."""
    for p, mod in zip(GENERATORS, ("regime_kr", "regime_us")):
        s = _src(p)
        fn = "_load_market_regime" if mod == "regime_kr" else "_load_us_market_regime"
        block = s[s.index(f"def {fn}("):]
        block = block[:block.index("\ndef ")]
        assert f"import {mod}" in block, f"{p.name}: {mod}에 위임하지 않는다"
        assert "regime_from_rows" in block, f"{p.name}: 공용 판정 함수를 안 쓴다"
        # 옛 정의의 지문 — 이 조합이 다시 나타나면 복제가 부활한 것이다.
        code = "\n".join(ln for ln in block.splitlines()
                         if not ln.lstrip().startswith("#"))
        assert "dist > 0 and mom5 > 0" not in code, f"{p.name}: 옛 판정식이 되살아났다"
        assert 'regime": "BULL"' not in code, f"{p.name}: 국면 라벨을 직접 만든다"


def test_win_rate_tables_live_only_in_regime_modules() -> None:
    """승률표는 `regime_kr`/`regime_us`에만 있어야 한다."""
    for p in GENERATORS:
        code = "\n".join(ln for ln in _src(p).splitlines()
                         if not ln.lstrip().startswith("#"))
        assert "_REGIME_WR_BY_HORIZON" not in code, f"{p.name}: 승률표가 복제돼 있다"
        assert "_POOLED_WR_BY_HORIZON" not in code, f"{p.name}: 풀링 승률이 복제돼 있다"


def test_regime_source_dispatches_per_market() -> None:
    import regime_kr as K
    import regime_source as S
    import regime_us as U
    assert S.module("kr") is K
    assert S.module("us") is U
    assert S.module("") is K          # 알 수 없는 시장은 국장(기존 동작)


def test_ev_multiplier_uses_the_market_own_table() -> None:
    """미장 BULL은 최악이라 깎여야 하고, 국장 BULL은 최악이 아니다."""
    import regime_source as S
    assert S.ev_multiplier("us", "BULL", "mid") < 1.0
    assert S.ev_multiplier("us", "BEAR", "mid") == 1.0     # 미장 BEAR는 최고
    assert S.ev_multiplier("kr", "SIDE", "mid") < 1.0      # 국장 SIDE는 최악
    # 같은 국면이라도 시장이 다르면 배수가 달라야 한다.
    assert S.ev_multiplier("kr", "BEAR", "mid") != S.ev_multiplier("us", "BULL", "mid")


def test_win_rate_table_matches_the_adopted_definition() -> None:
    """표는 `_classify`가 만든 라벨 위에서 계산돼야 한다.

    재검증 리포트에 채택 정의가 실제로 존재하는지까지 확인한다 — 정의 이름을
    바꾸고 표를 안 옮기면 여기서 걸린다.
    """
    import json
    adopted = "trend60+거래량(약추세만)"
    for mk, mod_name in (("kr", "regime_kr"), ("us", "regime_us")):
        mod = __import__(mod_name)
        for h in ("short", "swing", "mid"):
            p = ROOT / "reports" / f"regime_recalibration_{mk}_{h}.json"
            if not p.exists():          # 리포트는 재현으로 만드는 산출물이라 없을 수 있다
                continue
            cells = json.loads(p.read_text(encoding="utf-8"))["definitions"][adopted]["cells"]
            for reg in ("BULL", "SIDE", "BEAR"):
                got = mod.WIN_RATES[h][reg]
                want = round(cells[reg]["winRatePct"] / 100, 3)
                assert abs(got - want) < 5e-4, (
                    f"{mk}/{h}/{reg}: 표 {got} != 재현 {want} — "
                    f"판정 정의를 바꾸고 표를 안 옮겼다")


def test_strong_trend_is_never_overridden_by_volume() -> None:
    """AST로 확인 — 두 모듈 다 강한 추세 예외를 갖고 있어야 한다."""
    for name in ("regime_kr.py", "regime_us.py"):
        src = _src(ROOT / "scripts" / name)
        tree = ast.parse(src)
        consts = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                  for t in n.targets if isinstance(t, ast.Name)}
        assert "TREND60_STRONG" in consts, f"{name}: 강한 추세 예외 상수가 없다"
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_classify")
        used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "TREND60_STRONG" in used, f"{name}: _classify가 예외를 안 쓴다"
