#!/usr/bin/env python3
"""국면 라벨 정규화 — **단일 출처**.

2026-07-29 실측: 저널 880건의 `market_regime_at_signal`이
    횡보장 424 / BULL 236 / SIDE 150 / 약세장 70
으로 갈려 있었다. 한글 라벨과 영문 코드가 **같은 컬럼**에 섞여, 국면별
집계가 전부 어긋났다(같은 국면이 여러 버킷으로 쪼개짐).

원인은 판정 경로가 둘이었던 것이다 — 생성기는 한글 라벨을, 다른 경로는
영문 코드를 썼다. 생성기 쪽은 정규 코드로 고쳤지만 **과거 원장은 그대로**라,
읽는 쪽에서 정규화해야 한다.

이 모듈이 그 유일한 출처다. 각 스크립트가 자기 매핑을 들고 있으면 하나가
낡는 순간 조용히 갈린다 — 이 레포가 반복해 당한 형태다.
"""
from __future__ import annotations

CANONICAL = ("BULL", "SIDE", "BEAR")

# 표시용 한글 라벨 (정규 코드 -> 사람이 읽는 말)
LABEL_KO = {"BULL": "강세장", "SIDE": "횡보장", "BEAR": "약세장"}

# 지금까지 원장에 실제로 나타난 모든 표기 -> 정규 코드
_ALIAS = {
    "BULL": "BULL", "강세장": "BULL", "RISK_ON": "BULL", "UPTREND": "BULL",
    "SIDE": "SIDE", "횡보장": "SIDE", "NEUTRAL": "SIDE", "RANGE": "SIDE",
    "BEAR": "BEAR", "약세장": "BEAR", "RISK_OFF": "BEAR", "DOWNTREND": "BEAR",
}


def normalize(value: object) -> str | None:
    """어떤 표기든 BULL/SIDE/BEAR로. 모르면 **None**(추측하지 않는다)."""
    s = str(value or "").strip()
    if not s:
        return None
    return _ALIAS.get(s) or _ALIAS.get(s.upper())


def label_ko(value: object) -> str:
    """화면에 쓸 한글 라벨. 모르면 빈 문자열."""
    code = normalize(value)
    return LABEL_KO.get(code or "", "")


def is_canonical(value: object) -> bool:
    return str(value or "").strip() in CANONICAL
