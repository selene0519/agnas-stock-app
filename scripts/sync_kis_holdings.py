#!/usr/bin/env python
"""
한국투자증권(KIS) 실제 보유종목 조회 → data/kis_holdings_kr.csv 저장

Usage:
  python scripts/sync_kis_holdings.py
  python scripts/sync_kis_holdings.py --upload
  python scripts/sync_kis_holdings.py --upload --backend-url https://agnas-stock-app.onrender.com

Required env vars (.env 또는 환경변수):
  KIS_APP_KEY        앱 키
  KIS_APP_SECRET     앱 시크릿
  KIS_ACCOUNT_NO     계좌번호 10자리 (예: 12345678XX)

Optional env vars:
  KIS_ACCOUNT_PRODUCT_CODE  계좌상품코드 2자리 (미설정 시 KIS_ACCOUNT_NO 마지막 2자리)
  KIS_IS_MOCK               모의투자 여부 (true/false, 기본: false)
  KIS_BASE_URL              API 기본 URL 직접 지정
  MONE_USER_TOKEN           --upload 사용 시 필요
  MONE_BACKEND_URL          백엔드 URL (기본: http://localhost:8050)

보안:
  - 주문 API를 호출하지 않습니다 (조회 전용)
  - API Key/Secret/token은 Git에 올라가지 않습니다
  - Render 서버가 직접 증권사 API를 호출하지 않습니다
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# ── .env 로드 ──────────────────────────────────────────────────────────
def _load_dotenv() -> None:
    for candidate in [
        Path(__file__).resolve().parents[1] / ".env",
        Path(".env"),
    ]:
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8-sig").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
            except Exception:
                pass
            break

_load_dotenv()


# ── 환경변수 헬퍼 ──────────────────────────────────────────────────────
def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()

def _require_env(*names: str) -> dict[str, str]:
    missing = [n for n in names if not _env(n)]
    if missing:
        print(f"[ERROR] 필수 환경변수 미설정: {', '.join(missing)}", file=sys.stderr)
        print("  .env 파일 또는 환경변수에 추가해주세요. (.env.example 참고)", file=sys.stderr)
        sys.exit(1)
    return {n: _env(n) for n in names}

def _safe_float(v: Any) -> float:
    try:
        return float(str(v or "0").replace(",", "").strip())
    except Exception:
        return 0.0


# ── KIS 설정 ───────────────────────────────────────────────────────────
_TOKEN_CACHE = Path(__file__).resolve().parents[1] / "data" / "kis_token_cache.json"

def _kis_base_url(is_mock: bool) -> str:
    override = _env("KIS_BASE_URL")
    if override:
        return override.rstrip("/")
    return "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"

def _parse_account(account_no: str) -> tuple[str, str]:
    """KIS_ACCOUNT_NO (10자리) → (CANO 8자리, ACNT_PRDT_CD 2자리)"""
    raw = account_no.replace("-", "").replace(" ", "")
    cano_override = _env("KIS_CANO")
    acnt_override = _env("KIS_ACNT_PRDT_CD") or _env("KIS_ACCOUNT_PRODUCT_CODE")
    cano = cano_override or raw[:8]
    acnt = acnt_override or raw[8:10]
    if not cano or not acnt:
        print("[ERROR] 계좌번호 파싱 실패. KIS_ACCOUNT_NO가 10자리인지 확인하세요.", file=sys.stderr)
        sys.exit(1)
    return cano, acnt


# ── 토큰 발급 (파일 캐시) ────────────────────────────────────────────
def _get_token(app_key: str, app_secret: str, is_mock: bool, force: bool = False) -> str:
    if not force and _TOKEN_CACHE.exists():
        try:
            cache = json.loads(_TOKEN_CACHE.read_text(encoding="utf-8"))
            token = str(cache.get("access_token", "") or "")
            exp = float(cache.get("expires_at", 0) or 0)
            if token and exp > time.time() + 600:
                print(f"[token] 캐시 사용 (만료까지 {int(exp - time.time())}초)")
                return token
        except Exception:
            pass

    print("[token] KIS 토큰 발급 중...")
    base = _kis_base_url(is_mock)
    body = json.dumps({
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/oauth2/tokenP",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_txt = ""
        try:
            body_txt = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"[ERROR] 토큰 발급 실패: HTTP {exc.code} — {body_txt[:300]}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] 토큰 발급 네트워크 오류: {exc}", file=sys.stderr)
        sys.exit(1)

    token = str(payload.get("access_token", "") or "")
    if not token:
        print(f"[ERROR] 토큰 발급 실패: {payload.get('msg1', payload)}", file=sys.stderr)
        sys.exit(1)

    expires_in = int(_safe_float(payload.get("expires_in")) or 86400)
    _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_CACHE.write_text(json.dumps({
        "access_token": token,
        "expires_at": time.time() + max(60, expires_in - 300),
        "issued_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "is_mock": is_mock,
    }, ensure_ascii=False), encoding="utf-8")
    print("[token] 토큰 발급 완료")
    return token


# ── 보유종목 조회 ────────────────────────────────────────────────────
def _fetch_holdings(app_key: str, app_secret: str, is_mock: bool) -> list[dict[str, Any]]:
    token = _get_token(app_key, app_secret, is_mock)
    cano, acnt = _parse_account(_env("KIS_ACCOUNT_NO"))
    tr_id = "VTTC8434R" if is_mock else "TTTC8434R"
    base = _kis_base_url(is_mock)
    url = f"{base}/uapi/domestic-stock/v1/trading/inquire-balance"

    all_items: list[dict[str, Any]] = []
    ctx_fk = ""
    ctx_nk = ""
    force_refresh = False

    for page in range(1, 11):
        params = urllib.parse.urlencode({
            "CANO": cano,
            "ACNT_PRDT_CD": acnt,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "N",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": ctx_fk,
            "CTX_AREA_NK100": ctx_nk,
        })
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        req = urllib.request.Request(f"{url}?{params}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_txt = ""
            try:
                body_txt = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code == 401 and not force_refresh:
                print("[token] 토큰 만료 — 재발급 후 재시도")
                token = _get_token(app_key, app_secret, is_mock, force=True)
                force_refresh = True
                continue
            print(f"[ERROR] 잔고 조회 실패: HTTP {exc.code} — {body_txt[:300]}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"[ERROR] 잔고 조회 네트워크 오류: {exc}", file=sys.stderr)
            sys.exit(1)

        rt_cd = payload.get("rt_cd", "")
        if rt_cd != "0":
            msg = payload.get("msg1", str(payload)[:200])
            if rt_cd == "1" and not force_refresh:
                print("[token] API 응답 오류 — 토큰 재발급 후 재시도")
                token = _get_token(app_key, app_secret, is_mock, force=True)
                force_refresh = True
                continue
            print(f"[ERROR] KIS API 오류 (rt_cd={rt_cd}): {msg}", file=sys.stderr)
            sys.exit(1)

        force_refresh = False
        rows = payload.get("output1") or []
        for row in rows:
            qty = int(_safe_float(row.get("hldg_qty", "0")))
            if qty <= 0:
                continue
            symbol = str(row.get("pdno", "")).strip().zfill(6)
            if not symbol or not symbol.isdigit():
                continue
            avg = _safe_float(row.get("pchs_avg_pric", "0"))
            current = _safe_float(row.get("prpr", "0"))
            valuation = _safe_float(row.get("evlu_amt", "0")) or round(current * qty)
            pnl = _safe_float(row.get("evlu_pfls_amt", "0")) or round((current - avg) * qty if avg > 0 and current > 0 else 0)
            pnl_pct = _safe_float(row.get("evlu_pfls_rt", "0"))
            all_items.append({
                "symbol": symbol,
                "name": str(row.get("prdt_name", "")).strip() or symbol,
                "market": "kr",
                "quantity": qty,
                "avgPrice": round(avg, 2),
                "currentPrice": round(current, 2),
                "valuation": round(valuation),
                "pnl": round(pnl),
                "pnlPct": round(pnl_pct, 4),
            })

        print(f"  페이지 {page}: {len(rows)}건")
        ctx_fk = payload.get("ctx_area_fk100", "").strip()
        ctx_nk = payload.get("ctx_area_nk100", "").strip()
        if not ctx_nk:
            break

    # 중복 제거
    seen: set[str] = set()
    unique = []
    for item in all_items:
        if item["symbol"] not in seen:
            seen.add(item["symbol"])
            unique.append(item)

    return unique


# ── CSV 저장 ─────────────────────────────────────────────────────────
COLUMNS = ["symbol", "name", "market", "quantity", "avgPrice", "currentPrice", "valuation", "pnl", "pnlPct"]

def _save_csv(items: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)
    print(f"[saved] {path} ({len(items)}건)")


# ── 업로드 ───────────────────────────────────────────────────────────
def _upload(file_path: Path, backend_url: str, user_token: str) -> None:
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "local_broker_bridge_upload.py"),
        "--broker", "kis",
        "--file", str(file_path),
        "--backend-url", backend_url,
        "--user-token", user_token,
        "--mode", "replace_broker",
    ]
    print(f"\n[upload] 업로드 시작: {backend_url}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print("[ERROR] 업로드 실패", file=sys.stderr)
        sys.exit(result.returncode)


# ── 메인 ─────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="KIS 보유종목 조회 → CSV 저장 → (선택) MONE 업로드")
    parser.add_argument("--upload", action="store_true", help="조회 후 MONE에 자동 업로드")
    parser.add_argument("--backend-url", default=_env("MONE_BACKEND_URL", "http://localhost:8050"))
    parser.add_argument("--user-token", default=_env("MONE_USER_TOKEN", ""), help="업로드 시 필요")
    parser.add_argument("--output", default=str(Path(__file__).parents[1] / "data" / "kis_holdings_kr.csv"))
    parser.add_argument("--mock", action="store_true", help="모의투자 모드")
    args = parser.parse_args()

    # 필수 환경변수 확인
    _require_env("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO")
    app_key = _env("KIS_APP_KEY")
    app_secret = _env("KIS_APP_SECRET")
    is_mock = args.mock or _env("KIS_IS_MOCK").lower() in {"1", "true", "yes", "y", "mock", "모의"}
    mode = "모의" if is_mock else "실전"

    print(f"[KIS] 보유종목 조회 ({mode} 투자)")
    items = _fetch_holdings(app_key, app_secret, is_mock)

    if not items:
        print("[WARN] 조회된 보유종목이 없습니다. 계좌에 보유종목이 없거나 계좌정보를 확인해주세요.")
    else:
        print(f"[KIS] 총 {len(items)}건 조회")
        for it in items:
            avg_str = f"{it['avgPrice']:,.0f}원" if it["avgPrice"] else "-"
            cur_str = f"{it['currentPrice']:,.0f}원" if it["currentPrice"] else "-"
            print(f"  {it['symbol']} {it['name']:12s}  수량:{it['quantity']:>6}  평단:{avg_str:>10}  현재:{cur_str:>10}  손익:{it['pnlPct']:+.2f}%")

    out_path = Path(args.output)
    _save_csv(items, out_path)

    if args.upload:
        if not args.user_token:
            print("[ERROR] --upload 사용 시 --user-token 또는 MONE_USER_TOKEN 환경변수가 필요합니다.", file=sys.stderr)
            sys.exit(1)
        _upload(out_path, args.backend_url, args.user_token)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
