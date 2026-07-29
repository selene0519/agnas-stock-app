#!/usr/bin/env python3
"""프론트엔드 **색 대비** 실측 (WCAG 2.1, 375x812).

왜 실측인가: 이 레포는 Tailwind 클래스만 보고 판정하는 정적 감사로 169건을
뱉었다가 실측에서 31건이었던 전례가 있다(2026-07-29). 색 대비는 그보다 더
심하다 —

  * `text-amber-300/90` 처럼 **알파가 붙은 색**은 배경과 합성돼야 실제 색이
    나온다. 클래스만 보면 알파를 무시하고 원색으로 판정한다.
  * 배경은 자기 요소가 아니라 **조상 어딘가**가 그린다(`bg-slate-900/60`이
    `bg-slate-950` 위에 얹히는 식). 조상 체인을 합성하지 않으면 값이 틀린다.
  * 조상의 `opacity`는 그 아래 전부를 흐리게 만든다.

그래서 브라우저에서 실제 계산된 색을 읽고, **루트→요소 순으로 알파 합성**한
뒤 명암비를 낸다.

그라디언트 배경은 텍스트가 어느 지점에 놓이는지 모르지만 **색 정지점은
읽을 수 있으므로**, 정지점마다 재서 **가장 나쁜 값**을 쓴다. 정지점조차 못
읽는 경우(이미지 배경 등)만 `undetermined`로 남긴다 — 추측해서 통과시키지
않는다. 감시 장치가 모르는 걸 안다고 말하기 시작하면 그때부터 거짓말이 된다.

`::placeholder`도 잰다. 텍스트 노드가 아니라 TreeWalker에는 안 걸리는데
사용자 눈에는 그냥 글자다(이 앱에 1.93:1짜리가 있었다).

기준(WCAG 2.1 AA):
  * 일반 텍스트 4.5:1
  * 큰 텍스트(>=24px, 또는 >=18.66px이고 bold) 3:1
  * 비활성(disabled) 컨트롤은 WCAG 대상 외 -> 제외

전제: 프론트 dev 서버가 떠 있어야 한다.
    cd mone-web-app/frontend && npx next dev -p 3000

실행: python scripts/measure_frontend_contrast.py [--base http://127.0.0.1:3000]
쓰기: reports/frontend_contrast_audit.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "frontend_contrast_audit.json"
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

VIEWPORT = {"width": 375, "height": 812}

# 터치타깃 스크립트와 같은 목록이어야 한다(app/page.tsx의 pageIds).
PAGES = ["home", "report", "stocks", "holdings", "chart", "news",
         "prediction", "advanced", "paper", "journal", "broker", "admin"]

# **두 테마 다 잰다.** 헤더에 라이트 토글이 있어(app/page.tsx:122) 사용자가
# 실제로 볼 수 있는데, 첫 감사는 다크만 재고 "위반 0"이라 말할 뻔했다.
# globals.css의 `html[data-theme="light"]` 오버라이드는 색을 통째로 갈아치운다.
THEMES = ["dark", "light"]

PROBE_JS = r"""
() => {
  // ── 색 파싱 ─────────────────────────────────────────────────────
  // **정규식으로 rgb()만 파싱하면 안 된다.** Chromium은 계산값을
  // `oklab(0.802 -0.123 -0.021 / 0.7)` / `oklch(...)` 로 돌려준다(Tailwind v4
  // 팔레트 + `/opacity` 수정자). 첫 구현이 그걸 몰라 journal 화면 텍스트
  // 200개 중 **141개를 조용히 건너뛰고** "위반 5건"이라 말했다.
  // 브라우저에게 시키면 CSS Color 4 전부를 처리한다.
  const _cv = document.createElement('canvas');
  _cv.width = _cv.height = 1;
  const _g = _cv.getContext('2d', { willReadFrequently: true });
  const _cache = new Map();
  const parse = (s) => {
    if (!s) return null;
    if (_cache.has(s)) return _cache.get(s);
    let v = null;
    try {
      _g.clearRect(0, 0, 1, 1);
      _g.fillStyle = '#000';
      _g.fillStyle = s;          // 무효한 값이면 이전 값(#000)이 유지된다
      _g.fillRect(0, 0, 1, 1);
      const d = _g.getImageData(0, 0, 1, 1).data;
      v = [d[0], d[1], d[2], d[3] / 255];
    } catch (e) { v = null; }
    _cache.set(s, v);
    return v;
  };
  // fg를 bg(불투명) 위에 얹는다.
  const over = (fg, bg) => {
    const a = fg[3];
    return [fg[0] * a + bg[0] * (1 - a),
            fg[1] * a + bg[1] * (1 - a),
            fg[2] * a + bg[2] * (1 - a), 1];
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => {
    const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (l1 + 0.05) / (l2 + 0.05);
  };
  const hex = (c) => '#' + c.slice(0, 3).map((v) =>
    Math.round(v).toString(16).padStart(2, '0')).join('');

  // 건너뛴 이유를 전부 센다. 감시 장치가 뭘 안 봤는지 말하지 않으면
  // "위반 0"이 "검사 안 함"과 구별되지 않는다.
  const out = { violations: [], undetermined: [], checked: 0,
                skipped: { hidden: 0, zeroBox: 0, disabled: 0, unparsedColor: 0 },
                textElements: 0 };

  // ── 텍스트를 실제로 그리는 요소만 모은다 ────────────────────────
  const els = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    if (!(n.textContent || '').trim()) continue;
    const p = n.parentElement;
    if (p && !['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE'].includes(p.tagName)) els.add(p);
  }
  // placeholder는 **텍스트 노드가 아니라** TreeWalker에 안 걸린다. 그런데
  // 사용자 눈에는 그냥 글자다(이 앱에 `placeholder:text-slate-700` = 1.93:1이
  // 있었다). 별도로 넣어 준다.
  const placeholders = new Set();
  for (const el of document.querySelectorAll('input[placeholder], textarea[placeholder]')) {
    if ((el.getAttribute('placeholder') || '').trim() && !el.value) {
      placeholders.add(el);
      els.add(el);
    }
  }

  out.textElements = els.size;
  for (const el of els) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') { out.skipped.hidden++; continue; }
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) { out.skipped.zeroBox++; continue; }
    // sr-only(스크린리더 전용)는 눈에 안 보이므로 대비 대상이 아니다.
    if (r.width <= 1 && r.height <= 1) { out.skipped.zeroBox++; continue; }
    if (el.closest('[disabled]') || el.matches(':disabled')) { out.skipped.disabled++; continue; }

    // 조상 체인을 루트 방향으로 모은다: 배경색 + 그 요소 자신의 opacity.
    const chain = [];
    let cur = el, gradient = null;
    while (cur) {
      const ccs = getComputedStyle(cur);
      const op = parseFloat(ccs.opacity);
      if (ccs.backgroundImage && ccs.backgroundImage !== 'none' && !gradient) {
        gradient = { el: cur.tagName.toLowerCase(), raw: ccs.backgroundImage,
                     bg: ccs.backgroundImage.slice(0, 60) };
      }
      chain.push({ color: parse(ccs.backgroundColor),
                   own: Number.isFinite(op) ? op : 1 });
      cur = cur.parentElement;
    }
    // `opacity`는 **자기 자신과 후손에게만** 걸린다. 조상에게는 안 걸린다.
    // 처음엔 el에서 위로 올라가며 곱한 값(prefix)을 배경에도 썼는데, 그러면
    // 자식의 `opacity-70`이 **부모 배경까지** 흐리게 만든다. 실제로 리포트
    // 화면에서 브랜드 teal(#14b8a6)이 #11867f로 계산돼 2.58:1로 보고됐다
    // (참값 3.67:1). 층 i의 실효 알파는 i에서 루트까지의 **suffix** 곱이다.
    // (한계) 한 요소가 opacity와 자기 배경색을 **동시에** 가지면 CSS는 그룹을
    // 먼저 합성하므로 우리 근사와 미세하게 갈린다. 배경 없이 opacity만 쓰는
    // 일반적인 경우엔 정확히 일치한다.
    const suffix = new Array(chain.length);
    let acc = 1;
    for (let i = chain.length - 1; i >= 0; i--) { acc *= chain[i].own; suffix[i] = acc; }
    const textOpacity = suffix[0];   // el 자신 + 모든 조상

    const isPlaceholder = placeholders.has(el);
    const shownText = isPlaceholder
      ? el.getAttribute('placeholder')
      : (el.textContent || '').trim();
    // placeholder는 자기 색을 따로 갖는다(::placeholder 의사요소).
    const colorSrc = isPlaceholder
      ? (getComputedStyle(el, '::placeholder').color || cs.color)
      : cs.color;
    const textColor = parse(colorSrc);
    if (!textColor) { out.skipped.unparsedColor++; continue; }

    // 배경이 그라디언트면 텍스트가 어느 지점에 놓이는지는 모르지만,
    // **색 정지점(stop)은 알 수 있다.** 각 정지점을 배경으로 놓고 재서
    // 가장 나쁜 값을 쓴다 — 그라디언트 어디에 놓여도 그 값보다는 낫다.
    // (이미지 배경이나 정지점을 못 읽는 경우에만 판정불가로 남긴다.)
    let gradientStops = null;
    if (gradient) {
      const found = gradient.raw.match(
        /(?:oklab|oklch|rgba?|hsla?|lab|lch|hwb|color)\([^()]*\)|#[0-9a-fA-F]{3,8}\b/g) || [];
      const parsed = found.map(parse).filter((c) => c && c[3] > 0);
      if (parsed.length) gradientStops = parsed;
      if (!gradientStops) {
        out.undetermined.push({
          text: shownText.slice(0, 40),
          color: colorSrc, reason: 'background-image (정지점 파싱 불가)',
          on: gradient.el, bg: gradient.bg,
        });
        continue;
      }
    }

    // 루트(브라우저 기본 흰색)부터 안쪽으로 합성한다.
    let bg = [255, 255, 255, 1];
    for (let i = chain.length - 1; i >= 0; i--) {
      const layer = chain[i];
      if (!layer.color || layer.color[3] === 0) continue;
      bg = over([layer.color[0], layer.color[1], layer.color[2],
                 layer.color[3] * suffix[i]], bg);
    }
    // 그라디언트면 정지점마다 배경 후보를 만든다. 아니면 배경은 하나뿐.
    const bgCandidates = gradientStops
      ? gradientStops.map((s) => over([s[0], s[1], s[2], s[3]], bg))
      : [bg];

    const size = parseFloat(cs.fontSize) || 0;
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const need = large ? 3.0 : 4.5;

    // 가장 나쁜 정지점을 대표값으로 쓴다.
    let worst = null;
    for (const cand of bgCandidates) {
      const fgOn = over([textColor[0], textColor[1], textColor[2],
                         textColor[3] * textOpacity], cand);
      const cr = ratio(fgOn, cand);
      if (!worst || cr < worst.cr) worst = { cr, fg: fgOn, bg: cand };
    }

    out.checked++;
    if (worst.cr < need) {
      out.violations.push({
        text: shownText.slice(0, 45),
        tag: el.tagName.toLowerCase() + (isPlaceholder ? '[placeholder]' : ''),
        fg: hex(worst.fg), bg: hex(worst.bg),
        rawColor: colorSrc,
        onGradient: Boolean(gradientStops),
        fontPx: Math.round(size * 10) / 10, weight,
        large, ratio: Math.round(worst.cr * 100) / 100, need,
        cls: (el.className || '').toString().slice(0, 80),
      });
    }
  }
  // 같은 클래스+같은 비율은 한 곳에서 나온 것 -> 대표 1건으로 접는다.
  const seen = new Map();
  for (const v of out.violations) {
    const key = v.cls + '|' + v.ratio + '|' + v.fontPx;
    if (seen.has(key)) { seen.get(key).count++; continue; }
    seen.set(key, Object.assign({ count: 1 }, v));
  }
  out.violations = [...seen.values()].sort((a, b) => a.ratio - b.ratio);
  return out;
}
"""


# 로딩 화면이 떠 있는 동안 재면 **로딩 화면을 잰다.** 실제로 첫 실행에서
# home의 가시 텍스트가 56자("MONE 준비 중...")뿐이었는데 위반 0으로 찍혔다 —
# 2026-07-28 휴장일 감사에서 근접 알림 칩이 안 그려져 못 본 것과 같은 계열이다.
#
# 처음엔 "가시 글자수 200자 이상"을 렌더 완료 신호로 썼는데 **틀린 대리지표였다** —
# broker/admin은 로그인 게이트라 본문이 원래 140자쯤이고, 다 그려졌는데도
# 미렌더로 찍혔다. 로딩 문구의 존재 여부가 직접 신호다.
LOADING_MARKERS = ["불러오는 중", "준비 중", "로딩 중", "계산 중", "확인하고 있어요"]


def _wait_for_content(page, timeout_ms: int = 60000) -> None:
    """로딩 문구가 전부 사라질 때까지 기다린다."""
    try:
        page.wait_for_function(
            "(marks) => { const t = document.body.innerText || '';"
            "  return t.length > 0 && !marks.some((m) => t.includes(m)); }",
            arg=LOADING_MARKERS,
            timeout=timeout_ms,
        )
    except Exception:
        # 못 기다렸으면 그대로 진행하되 renderTrusted=false로 드러난다.
        pass


def run(base: str) -> dict:
    from playwright.sync_api import sync_playwright

    themes: dict[str, dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM)
        for theme in THEMES:
            results: dict[str, dict] = {}
            for page_id in PAGES:
                ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
                # app/page.tsx가 localStorage["mone:theme"]를 읽어 data-theme을 세팅한다.
                ctx.add_init_script(
                    f"try {{ localStorage.setItem('mone:theme', '{theme}'); }} catch (e) {{}}")
                page = ctx.new_page()
                url = base if page_id == "home" else f"{base}/?page={page_id}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    pass
                _wait_for_content(page)
                page.wait_for_timeout(1500)
                probe = page.evaluate(PROBE_JS)
                # 테마가 실제로 걸렸는지 확인한다. 안 걸렸으면 dark를 두 번 잰 것이다.
                probe["appliedTheme"] = page.evaluate(
                    "() => document.documentElement.dataset.theme || 'unset'")
                probe["visibleTextChars"] = page.evaluate(
                    "() => (document.body.innerText || '').length")
                # 재는 시점에 로딩 문구가 남아 있으면 그 화면은 아직 다 안 그려졌다.
                probe["pendingLoaders"] = page.evaluate(
                    "(marks) => { const t = document.body.innerText || '';"
                    "  return marks.filter((m) => t.includes(m)); }",
                    LOADING_MARKERS)
                probe["renderTrusted"] = not probe["pendingLoaders"]
                results[page_id] = probe
                ctx.close()
            themes[theme] = results
        browser.close()
    return {"viewport": VIEWPORT, "standard": "WCAG 2.1 AA",
            "thresholds": {"normalText": 4.5, "largeText": 3.0},
            "loadingMarkers": LOADING_MARKERS,
            "themes": themes}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3000")
    args = ap.parse_args()

    data = run(args.base)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== 색 대비 실측 {VIEWPORT['width']}x{VIEWPORT['height']} (WCAG 2.1 AA) ===")
    grand_v = grand_all = 0
    rows = []
    for theme, pages in data["themes"].items():
        print(f"\n[{theme} 테마]")
        print(f"{'화면':<12}{'텍스트':>7}{'검사':>7}{'미파싱':>7}"
              f"{'위반(고유)':>11}{'위반(총)':>10}{'판정불가':>10}")
        tot_v = tot_all = tot_u = tot_unparsed = 0
        untrusted, wrong_theme = [], []
        for pid, r in pages.items():
            allv = sum(v["count"] for v in r["violations"])
            unp = r.get("skipped", {}).get("unparsedColor", 0)
            flag = "" if r.get("renderTrusted") else "  <- 미렌더"
            print(f"{pid:<12}{r.get('textElements', 0):>7}{r['checked']:>7}{unp:>7}"
                  f"{len(r['violations']):>11}{allv:>10}{len(r['undetermined']):>10}{flag}")
            tot_v += len(r["violations"]); tot_all += allv
            tot_u += len(r["undetermined"]); tot_unparsed += unp
            if not r.get("renderTrusted"):
                untrusted.append(pid)
            if r.get("appliedTheme") != theme:
                wrong_theme.append(f"{pid}({r.get('appliedTheme')})")
            for v in r["violations"]:
                rows.append((v["ratio"], theme, pid, v))
        print(f"합계: 고유 위반 {tot_v} / 총 {tot_all} / 판정불가 {tot_u} / 미파싱 {tot_unparsed}")
        grand_v += tot_v; grand_all += tot_all
        if tot_unparsed:
            # 색을 못 읽은 텍스트는 "통과"가 아니라 "안 본 것"이다.
            print("⚠ 색을 파싱 못 한 텍스트가 있다 — 그만큼은 검사되지 않았다.")
        if untrusted:
            # 로딩 화면을 재고 "위반 0"이라 말하는 건 감시 장치가 거짓말을 하는 것이다.
            print(f"⚠ 본문이 안 그려진 화면(위반 0을 믿으면 안 됨): {', '.join(untrusted)}")
        if wrong_theme:
            # 테마가 안 걸렸으면 같은 테마를 두 번 잰 것이다.
            print(f"⚠ 테마가 적용되지 않은 화면: {', '.join(wrong_theme)}")

    print(f"\n=== 전체 합계: 고유 위반 {grand_v} / 총 {grand_all} ===")
    if rows:
        print("\n--- 낮은 순 상위 25 ---")
        rows.sort(key=lambda x: x[0])
        for cr, theme, pid, v in rows[:25]:
            print(f"  {cr:>5.2f}:1 (기준 {v['need']}) [{theme}/{pid}] {v['fontPx']}px "
                  f"{v['fg']} on {v['bg']} x{v['count']} — {v['text'][:30]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
