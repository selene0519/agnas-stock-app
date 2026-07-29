"""색 대비(WCAG 2.1 AA) 회귀 테스트.

실측은 `scripts/measure_frontend_contrast.py`(Playwright)가 하지만, 그건 dev
서버와 브라우저가 필요해 CI에서 못 돈다. 여기서는 **브라우저 없이** 두 가지를
지킨다.

  1. 디자인 토큰 자체의 명암비 — globals.css의 텍스트/배경 토큰을 파싱해
     WCAG 공식으로 직접 계산한다. 토큰 하나만 잘못 바꿔도 앱 전체가 같이
     어두워지므로, 여기가 가장 값싼 방어선이다.
  2. 실측에서 AA 미달로 확인된 클래스 조합의 재등장 차단.

2026-07-29 실측(375x812, 12화면): `text-slate-600`이 어두운 배경 위에서
2.50~2.64:1로 **11개 화면 전부**에 깔려 있었다(고유 41건/총 139건). 이 색을
쓰지 않는 것만으로 위반이 11건으로 줄었다.

⚠️ 계측기 자체가 두 번 틀렸던 자리라 그 회귀도 같이 막는다:
  * 색 파싱을 `rgba?\\(` 정규식으로 하면 Chromium이 돌려주는
    `oklab()`/`oklch()`를 못 읽고 **조용히 건너뛴다**(journal 화면에서 200개 중
    141개가 그렇게 빠졌고, 그 상태로 "위반 5건"이라 보고했다).
  * `opacity`는 자기 자신과 후손에게만 걸린다. 요소에서 위로 올라가며 곱한
    값을 배경에도 쓰면 **자식의 opacity가 부모 배경까지** 흐리게 만든다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "mone-web-app" / "frontend"
GLOBALS_CSS = FRONTEND / "app" / "globals.css"
AUDIT_SCRIPT = ROOT / "scripts" / "measure_frontend_contrast.py"

AA_NORMAL = 4.5


# ── WCAG 2.1 상대휘도/명암비 ───────────────────────────────────────────
def _srgb_to_linear(channel: int) -> float:
    v = channel / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * _srgb_to_linear(r)
            + 0.7152 * _srgb_to_linear(g)
            + 0.0722 * _srgb_to_linear(b))


def contrast(fg: str, bg: str) -> float:
    l1, l2 = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_contrast_formula_matches_known_values() -> None:
    """공식이 맞는지부터 고정한다 — 계산기가 틀리면 나머지 결론이 전부 틀린다."""
    assert round(contrast("#ffffff", "#000000"), 2) == 21.0
    assert round(contrast("#ffffff", "#ffffff"), 2) == 1.0
    # WCAG 문서의 대표 예시(#767676 on white = 4.54:1, AA 경계 바로 위).
    assert 4.5 <= contrast("#767676", "#ffffff") <= 4.6


# ── 디자인 토큰 ────────────────────────────────────────────────────────
def _css() -> str:
    return GLOBALS_CSS.read_text(encoding="utf-8")


def _token(block: str, name: str) -> str:
    """지정한 CSS 블록 안에서 `--name: #hex;` 를 뽑는다."""
    m = re.search(rf"{re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{6}})\s*;", block)
    assert m, f"{name} 토큰을 찾지 못했다"
    return m.group(1)


def _block(selector: str) -> str:
    css = _css()
    start = css.index(selector)
    return css[start:css.index("}", start)]


def test_dark_theme_text_tokens_meet_aa() -> None:
    """다크 테마 텍스트 토큰이 기본 배경 위에서 AA를 넘는가.

    `--text-muted`는 #475569(slate-600)였고 2.64:1이었다. 이 토큰을 쓰는
    화면 전체가 같이 미달이 되므로 토큰 단계에서 막는다.
    """
    blk = _block(":root {")
    bg = _token(blk, "--bg-primary")
    for name in ("--text-primary", "--text-secondary", "--text-muted"):
        fg = _token(blk, name)
        ratio = contrast(fg, bg)
        assert ratio >= AA_NORMAL, (
            f"다크 테마 {name}={fg} 가 배경 {bg} 위에서 {ratio:.2f}:1 — "
            f"AA 기준 {AA_NORMAL} 미달")


def test_light_theme_text_tokens_meet_aa() -> None:
    """라이트 테마도 잰다 — 헤더에 토글이 있어 사용자가 실제로 본다.

    첫 감사는 다크만 재고 "위반 0"이라 말할 뻔했다. 라이트 테마의
    `--text-muted`는 #718096으로 3.78:1이었다.
    """
    blk = _block('html[data-theme="light"] {')
    bg = _token(blk, "--bg-primary")
    for name in ("--text-primary", "--text-secondary", "--text-muted"):
        fg = _token(blk, name)
        ratio = contrast(fg, bg)
        assert ratio >= AA_NORMAL, (
            f"라이트 테마 {name}={fg} 가 배경 {bg} 위에서 {ratio:.2f}:1 — "
            f"AA 기준 {AA_NORMAL} 미달")


# ── 실측에서 미달로 확인된 클래스 조합 ────────────────────────────────
def _tsx_files() -> list[Path]:
    return [p for p in (FRONTEND / "components").rglob("*.tsx")] + \
           [p for p in (FRONTEND / "app").rglob("*.tsx")]


def test_no_dim_slate_text_on_dark_surfaces() -> None:
    """slate-500 3.89:1 / slate-600 2.50:1 / slate-700 1.93:1 — 전부 AA 미달.

    이 앱은 다크 테마가 기본이고 밝은 표면이 5곳뿐인데 그 5곳은 전부
    `text-slate-950`처럼 어두운 글자색을 명시한다. 따라서 이 토큰들은
    본문 색으로 쓰일 자리가 없다(`bg-`/`border-slate-700`은 무관하다).
    """
    offenders = []
    for path in _tsx_files():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = re.search(r"(?<![\w-])text-slate-(500|600|700)\b", line)
            if m:
                offenders.append(f"{path.relative_to(FRONTEND)}:{i} (slate-{m.group(1)})")
    assert not offenders, (
        "AA 미달 텍스트 색이 다시 들어왔다 (text-slate-400 이상을 쓸 것):\n  "
        + "\n  ".join(offenders))


def test_hover_states_are_not_no_ops() -> None:
    """색을 일괄 승격하면 base와 hover가 같아져 **의도치 않게 hover가 사라진다**.

    실제로 `text-slate-600 hover:text-slate-400` 3곳이 승격 후
    `text-slate-400 hover:text-slate-400`이 됐다. 대비는 통과하는데
    상호작용 피드백이 조용히 죽는 종류라 눈으로는 안 보인다.
    """
    offenders = []
    pattern = re.compile(r"(?<![\w-])(bg|text|border)-([a-z]+)-(\d+) hover:\1-\2-\3\b")
    for path in _tsx_files():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = pattern.search(line)
            if m:
                offenders.append(f"{path.relative_to(FRONTEND)}:{i} ({m.group(0)})")
    assert not offenders, (
        "base와 같은 값의 hover는 아무 일도 하지 않는다:\n  " + "\n  ".join(offenders))


def test_no_white_text_on_mid_accent_backgrounds() -> None:
    """흰 글자 on emerald-600(3.65:1) / cyan-600(3.62:1) 은 AA 미달.

    이 앱의 기존 관례는 강조색 위에 **어두운 잉크**다
    (globals.css가 brand teal 위에 #052420을 깐다). 그 관례를 따른다.
    """
    offenders = []
    for path in _tsx_files():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"bg-(emerald|cyan)-600\b", line) and "text-white" in line:
                offenders.append(f"{path.relative_to(FRONTEND)}:{i}")
    assert not offenders, (
        "중간 밝기 강조색 위의 흰 글자는 AA 미달이다 (text-slate-950을 쓸 것):\n  "
        + "\n  ".join(offenders))


# ── 계측기 자체의 회귀 방지 ────────────────────────────────────────────
def test_audit_measures_both_themes() -> None:
    """다크만 재면 앱의 절반만 본 것이다."""
    src = AUDIT_SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"^THEMES\s*=\s*(\[[^\]]*\])", src, re.MULTILINE)
    assert m, "THEMES 목록이 없다"
    assert "light" in m.group(1) and "dark" in m.group(1), (
        f"두 테마를 다 재야 한다: {m.group(1)}")


def test_audit_does_not_parse_colors_with_naive_rgb_regex() -> None:
    """Chromium은 계산값을 oklab()/oklch()로 돌려준다.

    정규식으로 rgb()만 받으면 그 텍스트들을 **조용히 건너뛰고** 통과로
    보고한다(실측에서 200개 중 141개가 그렇게 빠졌다). 브라우저에 맡겨야 한다.
    """
    src = AUDIT_SCRIPT.read_text(encoding="utf-8")
    assert "getImageData" in src, (
        "색 파싱을 캔버스에 맡기지 않고 있다 — oklab/oklch를 놓친다")
    # 파서 본체가 rgb() 정규식 매칭에 의존하면 안 된다.
    assert "s.match(/rgba?\\(" not in src, (
        "rgb() 정규식 파서가 되살아났다 — oklab/oklch 텍스트가 조용히 빠진다")


def test_audit_applies_opacity_as_suffix_product() -> None:
    """`opacity`는 조상에게 걸리지 않는다.

    요소에서 위로 올라가며 누적한 곱(prefix)을 배경에 쓰면 자식의
    `opacity-70`이 부모 배경까지 흐리게 만든다. 실제로 브랜드 teal(#14b8a6)이
    #11867f로 계산돼 2.58:1로 보고됐다(참값 3.67:1).
    """
    src = AUDIT_SCRIPT.read_text(encoding="utf-8")
    assert "suffix" in src and "textOpacity" in src, (
        "opacity 누적이 suffix 방식이 아니다")
    assert "layer.opacity" not in src, (
        "prefix 누적 방식(layer.opacity)이 되살아났다")


def test_no_low_contrast_placeholder_colors() -> None:
    """placeholder도 사용자 눈에는 그냥 글자다.

    `placeholder:text-slate-700`은 1.93:1이었다. TreeWalker는 텍스트 노드만
    보므로 이건 **실측에서도 안 잡히던** 사각지대였다.
    """
    offenders = []
    for path in _tsx_files():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = re.search(r"placeholder:text-slate-(\d+)", line)
            if m and int(m.group(1)) >= 500:
                offenders.append(f"{path.relative_to(FRONTEND)}:{i} (slate-{m.group(1)})")
    assert not offenders, (
        "AA 미달 placeholder 색:\n  " + "\n  ".join(offenders))


def test_audit_measures_placeholder_and_gradient_backgrounds() -> None:
    """계측기가 두 사각지대를 계속 덮는지 고정한다."""
    src = AUDIT_SCRIPT.read_text(encoding="utf-8")
    assert "::placeholder" in src, "placeholder 색을 안 잰다"
    assert "input[placeholder]" in src, "placeholder 요소를 안 모은다"
    # 그라디언트를 통째로 '판정불가'로 넘기면 화면 하나가 통째로 미검사가 된다.
    assert "gradientStops" in src, "그라디언트 정지점을 안 잰다"


def test_audit_reports_what_it_did_not_check() -> None:
    """검사 못 한 것을 말하지 않는 감시 장치는 '위반 0'과 '안 봄'을 섞는다."""
    src = AUDIT_SCRIPT.read_text(encoding="utf-8")
    for marker in ("unparsedColor", "renderTrusted", "undetermined"):
        assert marker in src, f"{marker} 보고가 빠졌다"
