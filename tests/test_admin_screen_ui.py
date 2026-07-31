"""관리자 화면 UI 회귀 테스트 (2026-07-31).

**왜 이 파일이 필요했나 — 관리자 대시보드는 한 번도 계측된 적이 없었다.**
`scripts/measure_frontend_touch_targets.py`의 PAGES에 `admin`이 들어 있어서
12개 화면을 다 도는 것처럼 보였지만, `app/page.tsx`가 adminToken이 없으면
AdminLoginPage를 그린다. 즉 세 번의 감사(07-26·07-28·07-29)가 전부 **로그인
폼을 재고 "위반 0"이라 보고**했다. 토큰을 넣고 재니 44px 미달 18건,
기계코드 9건이 나왔다.

여기서 막는 것은 브라우저 없이 정적으로 확인 가능한 것들뿐이다. 실측은
여전히 measure 스크립트가 한다(`--admin-token` 필요).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "mone-web-app" / "frontend"
ADMIN_PAGE = FRONTEND / "components" / "pages" / "AdminPage.tsx"
GLOBALS_CSS = FRONTEND / "app" / "globals.css"
MEASURE_SCRIPT = ROOT / "scripts" / "measure_frontend_touch_targets.py"

TSX_FILES = [p for p in FRONTEND.rglob("*.tsx") if "node_modules" not in p.parts]

# class 문자열 리터럴만 뽑는다(주석·설명문에 걸리지 않게).
CLASS_ATTR = re.compile(r'className=\{?[`"]([^`"]*)[`"]')
SOLID_BLUE_BG = re.compile(r"bg-blue-(?:500|600)(?![0-9/])")
# 모든 문자열 리터럴. ⚠️ `className=`만 보면 **변형 맵**을 놓친다 — 실제 버그가
# 바로 그 모양이었다(`const cls = { blue: "border-blue-500/30 bg-blue-600 ..." }`).
ANY_STRING = re.compile(r'[`"]([^`"\n]*)[`"]')
JS_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def _class_strings(text: str) -> list[str]:
    return [m.group(1) for m in CLASS_ATTR.finditer(text)]


def _strip_comments(text: str) -> str:
    """주석 제거. 이 규칙을 설명하는 주석이 위반 예시 문자열을 담고 있어서,
    안 걷어내면 검사기가 자기 설명문을 잡는다(이 레포에서 세 번 반복된 실수)."""
    return JS_COMMENT.sub("", text)


def test_no_solid_blue_bg_mixed_with_slash_utility():
    """불투명 blue 배경 + 슬래시 달린 blue 유틸리티를 한 class에 같이 쓰지 않는다.

    globals.css는 `bg-blue-600`에 브랜드 teal 배경 + 어두운 잉크(#052420)를
    입히고, 반투명 blue(`bg-blue-500/10` 등)에는 10% 틴트 배경을 입힌다.
    그런데 예전 선택자 `[class*="bg-blue-"][class*="/"]`의 `[class*="/"]`는
    **class 문자열 어디에** 슬래시가 있든 걸린다. 그래서
    `border-blue-500/30 bg-blue-600 text-white`처럼 둘을 섞으면 배경만 10%
    틴트로 덮이고 잉크는 남아 글자가 사실상 사라진다 — 관리자 대시보드
    "GitHub 동기화" 버튼 실측 **1.08:1**(다크) / 3.23:1(라이트).

    선택자는 고쳤지만(아래 테스트), 이 조합 자체가 읽는 사람을 헷갈리게 하고
    다른 규칙에도 같은 함정이 있을 수 있어 소스 쪽에서도 막는다.
    """
    offenders = []
    for path in TSX_FILES:
        source = _strip_comments(path.read_text(encoding="utf-8"))
        for cls in ANY_STRING.findall(source):
            if SOLID_BLUE_BG.search(cls) and "/" in cls:
                offenders.append(f"{path.relative_to(ROOT)}: {cls}")
    assert not offenders, (
        "불투명 bg-blue-500/600 과 슬래시 유틸리티를 같은 class에 섞었다 — "
        "globals.css의 반투명 규칙이 배경만 덮어써서 글자가 안 보인다:\n  "
        + "\n  ".join(offenders)
    )


def test_translucent_blue_rule_targets_the_bg_utility_itself():
    """반투명 blue 규칙은 `bg-blue-<숫자>/` 형태로 검사해야 한다."""
    # ⚠️ 주석을 먼저 걷어낸다. 이 규칙을 **설명하는 주석**이 옛 선택자 문자열을
    # 그대로 담고 있어서, 안 걷어내면 검사기가 자기 설명문을 잡는다.
    # (2026-07-29에 AST 검사와 `set +e` 검사에서 각각 한 번씩 같은 실수를 했다.)
    css = re.sub(r"/\*.*?\*/", "", GLOBALS_CSS.read_text(encoding="utf-8"), flags=re.S)
    assert '[class*="bg-blue-"][class*="/"]' not in css, (
        '`[class*="bg-blue-"][class*="/"]`는 class 어디의 슬래시든 잡는다. '
        "불투명 배경 버튼의 배경까지 덮어써 글자를 지운다."
    )
    # 실제로 쓰이는 반투명 배경은 계속 브랜드색으로 바뀌어야 한다.
    for shade in ("400", "500", "600", "900", "950"):
        assert f'[class*="bg-blue-{shade}/"]' in css, (
            f"bg-blue-{shade}/<opacity> 를 브랜드색으로 바꾸는 규칙이 사라졌다"
        )


def test_admin_page_does_not_print_raw_status_codes():
    """상태 코드를 본문 텍스트로 그대로 찍지 않는다.

    실측에서 UNKNOWN·NORMAL·EMPTY_RESULT·LOADING이 화면에 노출됐다.
    원문은 title 속성으로만 남기고 본문에는 한국어 라벨을 쓴다.
    """
    src = ADMIN_PAGE.read_text(encoding="utf-8")
    raw_renders = [
        "{row.githubActionsStatus",
        "{row.currentPriceSourceStatus",
        "{row.dataStatus",
        "{row.localCollectorStatus",
        '{trendlineAccuracy.status || "확인 불가"}',
        '{audit.status || "확인 불가"}',
        'label="VERIFIED_90"',
    ]
    found = [needle for needle in raw_renders if needle in src]
    assert not found, f"기계 코드가 본문에 그대로 렌더된다: {found}"
    # 라벨 변환기를 실제로 쓰고 있어야 한다.
    assert "statusLabel" in src and "codeText(" in src
    assert "failureReasonLabel(" in src, "실패 원인 코드도 한국어로 바꿔야 한다"


def test_admin_interactive_controls_declare_touch_height():
    """`<button>` 태그에 붙은 class만 보고 최소 높이 선언을 확인한다.

    ⚠️ 여기서 **class 문자열 전체를 훑는 정적 검사는 쓰지 않는다.** 그렇게
    했더니 배지·상태칩·Mini 카드처럼 누를 수 없는 요소까지 위반으로 셌다
    (7건 전부 오탐). 2026-07-29에 정적 Tailwind 분석이 169건을 뱉고 실측은
    31건이라 스크립트를 폐기한 것과 같은 실수다 — 과탐 감시는 없느니만 못하다.
    진짜 판정은 measure 스크립트의 실측이 한다. 여기서는 `<button ...>` 여는
    태그에 실제로 붙은 class만 본다.
    """
    src = ADMIN_PAGE.read_text(encoding="utf-8")
    ok_tokens = ("min-h-11", "size-11", "h-11", "h-12", "min-h-[44px]", "py-3")
    too_small = []
    for m in re.finditer(r"<button\b[^>]*?>", src, flags=re.S):
        tag = m.group(0)
        cls_match = re.search(r'className=\{?[`"]([^`"]*)[`"]', tag)
        if not cls_match:
            continue
        cls = cls_match.group(1)
        if any(tok in cls for tok in ok_tokens):
            continue
        # 템플릿 리터럴로 조건부 클래스를 붙이는 버튼은 여는 태그만으론 못 본다.
        if "${" in tag:
            continue
        if re.search(r"\bpy-(?:0\.5|1|1\.5|2)\b", cls):
            too_small.append(cls)
    assert not too_small, (
        "관리자 화면 버튼이 44px 최소 높이를 선언하지 않았다(min-h-11 필요):\n  "
        + "\n  ".join(too_small)
    )


def test_admin_result_banner_is_outside_the_overview_tab():
    """결과 배너가 특정 탭 안에만 있으면 다른 탭의 액션은 피드백이 없다.

    자가보정 탭의 "보정 파라미터 재계산"은 setMessage를 부르는데, 배너가
    운영 탭 블록 안에만 있어서 눌러도 화면에 아무 변화가 없었다.
    """
    src = ADMIN_PAGE.read_text(encoding="utf-8")
    banner = src.index("{message && (")
    overview_gate = src.index('{tab === "overview" && (')
    assert banner < overview_gate, (
        "결과 배너가 운영 탭 블록 안에 있다 — 다른 탭의 액션 결과가 안 보인다."
    )
    assert 'role="status"' in src and 'aria-label="알림 닫기"' in src


def test_measure_script_can_authenticate_into_admin():
    """계측 스크립트가 로그인 게이트를 넘을 수단을 갖고 있어야 한다.

    이게 없으면 admin은 영원히 로그인 폼만 재고 "위반 0"으로 보고된다.
    """
    src = MEASURE_SCRIPT.read_text(encoding="utf-8")
    assert "MONE_MEASURE_ADMIN_TOKEN" in src
    assert "--admin-token" in src
    assert "mone:adminToken" in src
    # 인증 없이 잰 결과를 통과로 오독하지 않게 리포트에 남겨야 한다.
    assert "measuredAuthenticated" in src
    assert "adminMeasuredAuthenticated" in src
    # 탭 전용 화면(자가보정)도 순회 대상이어야 한다.
    assert "TAB_DRILLS" in src and "자가보정" in src
