#!/usr/bin/env python3
"""프론트엔드 터치타깃·미명명 컨트롤 **실측** (375x812).

정적 분석(scripts/audit_frontend_a11y.py)은 Tailwind 클래스만 보고 높이를
추정하므로 과탐한다 — flex 부모가 늘려주거나 형제 요소가 행 높이를 만드는
경우를 못 본다. 실제 렌더 박스를 재는 건 브라우저뿐이다.

반대로 손 계측은 화면이 늘어날 때마다 빠진다(2026-07-26 4개, 07-28 9개만
계측 — AI매매·관리자는 두 번 다 누락). 그래서 **화면 목록을 코드에서 받아**
전부 순회한다.

전제: 프론트 dev 서버가 떠 있어야 한다.
    cd mone-web-app/frontend && npx next dev -p 3000

실행: python scripts/measure_frontend_touch_targets.py [--base http://127.0.0.1:3000]
쓰기: reports/frontend_touch_target_audit.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "frontend_touch_target_audit.json"
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

VIEWPORT = {"width": 375, "height": 812}
MIN_TOUCH_PX = 44

# app/page.tsx의 pageIds와 같아야 한다. 어긋나면 화면이 조용히 빠진다.
PAGES = ["home", "report", "stocks", "holdings", "chart", "news",
         "prediction", "advanced", "paper", "journal", "broker", "admin"]

# ⚠️ `admin`은 **로그인 게이트**다(app/page.tsx:322 — adminToken이 없으면
# AdminLoginPage를 그린다). 토큰 없이 재면 12개 화면을 다 돈 것처럼 보이지만
# 실제로는 로그인 폼만 잰다 — 2026-07-31에 그 사실이 드러났고, 그때까지
# 가려져 있던 관리자 대시보드에서 44px 미달 18건과 기계코드 9건이 나왔다.
# (2026-07-26/28/29 세 번의 감사가 전부 이걸 놓쳤다.)
#
# 토큰을 주면 실제 대시보드를 잰다:
#   MONE_MEASURE_ADMIN_TOKEN=$(curl -s -XPOST localhost:8050/api/auth/admin-login \
#     -H 'Content-Type: application/json' -d '{"adminId":"...","password":"..."}' \
#     | python -c 'import json,sys;print(json.load(sys.stdin)["token"])')
ADMIN_TOKEN_KEY = "mone:adminToken"

# 탭 안에만 있는 화면은 URL이 없다. 관리자 "자가보정" 탭은 다른 어떤 pageId로도
# 안 닿아서 지금껏 한 번도 계측되지 않았다 -> 탭을 눌러서 연다.
#
# 탭만 열면 **빈 상태**를 잰다. 자가보정 탭은 데이터를 불러와야 전략 선택
# 버튼들이 그려지는데, 탭만 누른 계측은 6건, 실제로 불러온 뒤는 13건이었다.
# 그래서 라벨을 **순서대로** 눌러 본문이 채워진 상태를 잰다(없으면 조용히 넘어간다).
TAB_DRILLS: dict[str, list[tuple[str, list[str]]]] = {
    "admin": [("자가보정", ["자가보정", "대시보드 갱신", "미리보기 로드"])],
}

# 보이는 상호작용 요소를 모아 렌더 박스를 재는 스크립트.
# getBoundingClientRect는 부모 flex/grid가 늘려준 실제 높이를 반영한다.
PROBE_JS = r"""
() => {
  const SEL = 'button, a[href], a[role="button"], input, select, textarea, [role="button"], [role="tab"], [role="combobox"], [role="switch"]';
  const out = { small: [], unnamed: [], machineCodes: [], total: 0 };
  const MACHINE = /^[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)*$/;
  const ALLOW = new Set(['KRW','USD','KR','US','KOSPI','KOSDAQ','NASDAQ','NYSE','ETF','NAV','AI','API','URL','CSV','JSON','OHLCV','RSI','MACD','MA','VTJ','BULL','BEAR','SIDE','WIN','LOSS','PENDING','OK','ERROR','WARN','BUY','SELL','HOLD','PER','PBR','ROE','EPS','DART','KIS','MONE','MDD','MAE','MFE','CAGR','RR','ID','PC',
    // 브랜딩(의도적 대문자 조판)과 도메인 용어 — 기계코드가 아니다.
    'AGNAS','STOCK','APP','WHERE','MOMENTUM','BEGINS','PAPER','ONLY','OOS','NEUTRAL']);
  const label = (el) => (
    el.getAttribute('aria-label') ||
    (el.getAttribute('aria-labelledby') && (document.getElementById(el.getAttribute('aria-labelledby'))||{}).textContent) ||
    el.title ||
    (el.id && (document.querySelector('label[for="'+CSS.escape(el.id)+'"]')||{}).textContent) ||
    el.closest('label')?.textContent ||
    el.placeholder ||
    el.value ||
    el.textContent || ''
  ).trim();

  for (const el of document.querySelectorAll(SEL)) {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || el.hidden) continue;
    if (r.width === 0 || r.height === 0) continue;      // 안 그려진 것
    if (el.disabled) continue;
    out.total++;
    // 클릭 가능한 조상이 44px를 만들어주면 사용자는 그걸 누른다 -> 통과.
    let box = Math.min(r.width, r.height);
    // ::after/::before로 히트영역을 넓히는 패턴(after:-inset-1 등)을 반영한다.
    // 시각 박스는 36px여도 실제로 누르는 영역은 44px인 경우가 흔하다 —
    // 이걸 안 보면 이미 적합한 요소를 위반으로 세고, 멀쩡한 코드를 고치게 된다.
    for (const pseudo of ['::after', '::before']) {
      const ps = getComputedStyle(el, pseudo);
      if (!ps || ps.content === 'none' || ps.position !== 'absolute') continue;
      const px = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
      const eh = r.height - px(ps.top) - px(ps.bottom);
      const ew = r.width - px(ps.left) - px(ps.right);
      if (eh > 0 && ew > 0) box = Math.max(box, Math.min(ew, eh));
    }
    const par = el.parentElement;
    if (par) {
      const pr = par.getBoundingClientRect();
      const pcs = getComputedStyle(par);
      if (pcs.cursor === 'pointer' || par.onclick) box = Math.max(box, Math.min(pr.width, pr.height));
    }
    if (box < 44) {
      out.small.push({ tag: el.tagName.toLowerCase(), w: Math.round(r.width),
                       h: Math.round(r.height), text: label(el).slice(0, 40),
                       cls: (el.className || '').toString().slice(0, 70) });
    }
    if (!label(el)) {
      out.unnamed.push({ tag: el.tagName.toLowerCase(), type: el.type || '',
                         cls: (el.className || '').toString().slice(0, 70) });
    }
  }
  // 사용자에게 보이는 텍스트 중 기계코드
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const t = (n.textContent || '').trim();
    if (!t || t.length > 40) continue;
    for (const tok of t.split(/[\s,/()|]+/)) {
      if (tok && MACHINE.test(tok) && !ALLOW.has(tok) && !/^(MA|EMA|SMA|BB)\d+$/.test(tok)) {
        out.machineCodes.push({ code: tok, context: t.slice(0, 50) });
      }
    }
  }
  return out;
}
"""


def _measure(page) -> dict:
    probe = page.evaluate(PROBE_JS)
    # 가로 스크롤(모바일에서 제일 티나는 레이아웃 붕괴)
    probe["horizontalOverflowPx"] = page.evaluate(
        "() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)"
    )
    return probe


def run(base: str, admin_token: str = "") -> dict:
    from playwright.sync_api import sync_playwright

    results: dict[str, dict] = {}
    console_errors: dict[str, list[str]] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM)
        for page_id in PAGES:
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
            if admin_token:
                ctx.add_init_script(
                    f"window.localStorage.setItem({json.dumps(ADMIN_TOKEN_KEY)}, {json.dumps(admin_token)});")
            page = ctx.new_page()
            errs: list[str] = []
            page.on("console", lambda m, e=errs: e.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda exc, e=errs: e.append(str(exc)))
            url = base if page_id == "home" else f"{base}/?page={page_id}"
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                # 백엔드가 없으면 networkidle이 안 올 수 있다 — 렌더는 됐으므로 계속.
                pass
            page.wait_for_timeout(1500)
            probe = _measure(page)
            # 인증이 필요한 화면인데 토큰이 없으면 **로그인 폼을 잰 것**이다.
            # 0으로 찍힌 걸 "통과"로 읽으면 안 되니 리포트에 남긴다.
            if page_id in ("admin", "broker"):
                probe["authGated"] = True
                probe["measuredAuthenticated"] = bool(admin_token) and page_id == "admin"
            results[page_id] = probe
            console_errors[page_id] = errs[:5]

            # 탭 전용 화면(URL 없음)도 같은 기준으로 잰다.
            for tab_name, click_labels in TAB_DRILLS.get(page_id, []):
                if page_id == "admin" and not admin_token:
                    continue  # 로그인 폼엔 그 탭이 없다
                opened = False
                for label in click_labels:
                    try:
                        page.get_by_text(label, exact=True).first.click(timeout=15000)
                        page.wait_for_timeout(3000)
                        opened = True
                    except Exception:
                        continue  # 그 단계 버튼이 없으면 건너뛴다(데이터가 없을 수 있다)
                if not opened:
                    continue
                key = f"{page_id}:{tab_name}"
                results[key] = _measure(page)
                console_errors[key] = errs[:5]
            ctx.close()
        browser.close()
    return {"viewport": VIEWPORT, "minTouchPx": MIN_TOUCH_PX,
            "adminMeasuredAuthenticated": bool(admin_token),
            "pages": results, "consoleErrors": console_errors}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3000")
    ap.add_argument("--admin-token", default=os.environ.get("MONE_MEASURE_ADMIN_TOKEN", ""),
                    help="관리자 대시보드를 실제로 재려면 필요. 없으면 로그인 폼만 잰다.")
    args = ap.parse_args()

    data = run(args.base, args.admin_token)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== 터치타깃 실측 {VIEWPORT['width']}x{VIEWPORT['height']} (기준 {MIN_TOUCH_PX}px) ===")
    print(f"{'화면':<12}{'요소':>6}{'44px미달':>9}{'무명':>6}{'기계코드':>9}{'가로스크롤':>11}{'콘솔':>6}")
    totals = [0, 0, 0, 0]
    for pid, r in data["pages"].items():
        errs = len(data["consoleErrors"].get(pid) or [])
        print(f"{pid:<12}{r['total']:>6}{len(r['small']):>9}{len(r['unnamed']):>6}"
              f"{len(r['machineCodes']):>9}{r['horizontalOverflowPx']:>11}{errs:>6}")
        totals[0] += len(r["small"]); totals[1] += len(r["unnamed"])
        totals[2] += len(r["machineCodes"]); totals[3] += errs
    print(f"\n합계: 44px미달 {totals[0]} / 무명 {totals[1]} / 기계코드 {totals[2]} / 콘솔에러 {totals[3]}")
    if not data.get("adminMeasuredAuthenticated"):
        print("\n⚠️  admin은 로그인 폼만 쟀다 — 관리자 대시보드 본문은 **미계측**이다.")
        print("    실제로 재려면 --admin-token 또는 MONE_MEASURE_ADMIN_TOKEN을 넘길 것.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
