#!/usr/bin/env python
"""
토스증권 실제 보유종목 조회 → data/toss_holdings_kr.csv 저장

Usage:
  python scripts/sync_toss_holdings.py
  python scripts/sync_toss_holdings.py --upload
  python scripts/sync_toss_holdings.py --upload --backend-url https://agnas-stock-app.onrender.com

Required env vars (.env 또는 환경변수):
  TOSS_CLIENT_ID      토스증권 Open API Client ID (= App Key)
  TOSS_CLIENT_SECRET  토스증권 Open API Client Secret (= App Secret)

Optional env vars:
  MONE_USER_TOKEN     --upload 사용 시 필요
  MONE_BACKEND_URL    백엔드 URL (기본: http://localhost:8050)

API 흐름:
  1. POST https://openapi.tossinvest.com/oauth2/token  (x-www-form-urlencoded)
  2. GET  https://openapi.tossinvest.com/api/v1/accounts
  3. GET  https://openapi.tossinvest.com/api/v1/holdings  (X-Tossinvest-Account: {accountSeq})

보안:
  - 주문 API를 호출하지 않습니다 (조회 전용)
  - Client ID/Secret/token은 Git에 올라가지 않습니다
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

_TOSS_BASE = "https://openapi.tossinvest.com"
_TOKEN_CACHE = Path(__file__).resolve().parents[1] / "data" / "toss_token_cache.json"
COLUMNS = ["symbol", "name", "market", "quantity", "avgPrice", "currentPrice", "valuation", "pnl", "pnlPct"]


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


# ── 헬퍼 ─────────────────────────────────────────────────────────────
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

def _normalize_market(value: Any) -> str:
    raw = str(value or "").upper().strip()
    if raw in ("KR", "KOR", "KOREA", "DOMESTIC", "국내", "KRX"):
        return "kr"
    if raw in ("US", "USA", "OVERSEAS", "해외", "FOREIGN", "NYSE", "NASDAQ", "NAS", "NYS"):
        return "us"
    # 종목코드로 추정: 6자리 숫자이면 국내
    return "kr"

def _http_get(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"[ERROR] HTTP {exc.code} {url} — {body[:300]}", file=sys.stderr)
        raise
    except Exception as exc:
        print(f"[ERROR] 네트워크 오류 {url}: {exc}", file=sys.stderr)
        raise


# ── 토큰 발급 (파일 캐시) ─────────────────────────────────────────────
def _get_token(client_id: str, client_secret: str, force: bool = False) -> str:
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

    print("[token] 토스증권 토큰 발급 중...")
    form_data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{_TOSS_BASE}/oauth2/token",
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "MONE-SyncToss/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if exc.code in (400, 401):
            print(f"[ERROR] 토큰 발급 인증 실패 (HTTP {exc.code}) — TOSS_CLIENT_ID/TOSS_CLIENT_SECRET 확인", file=sys.stderr)
            print(f"  응답: {body[:300]}", file=sys.stderr)
        elif exc.code == 404:
            print(f"[ERROR] 토큰 엔드포인트를 찾을 수 없습니다 (HTTP 404). 토스증권 Open API 가입 여부를 확인하세요.", file=sys.stderr)
        else:
            print(f"[ERROR] 토큰 발급 실패 HTTP {exc.code}: {body[:300]}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] 토큰 발급 네트워크 오류: {exc}", file=sys.stderr)
        sys.exit(1)

    token = str(payload.get("access_token", "") or "")
    if not token:
        print(f"[ERROR] 토큰 발급 실패: {payload}", file=sys.stderr)
        sys.exit(1)

    expires_in = int(_safe_float(payload.get("expires_in")) or 86400)
    _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_CACHE.write_text(json.dumps({
        "access_token": token,
        "expires_at": time.time() + max(60, expires_in - 300),
        "issued_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "token_type": payload.get("token_type", "Bearer"),
    }, ensure_ascii=False), encoding="utf-8")
    print("[token] 토큰 발급 완료")
    return token


# ── 계좌 목록 조회 ────────────────────────────────────────────────────
def _get_accounts(token: str) -> list[dict[str, Any]]:
    print("[accounts] 계좌 목록 조회 중...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "MONE-SyncToss/1.0",
    }
    try:
        data = _http_get(f"{_TOSS_BASE}/api/v1/accounts", headers)
    except Exception:
        print("[ERROR] 계좌 목록 조회 실패", file=sys.stderr)
        sys.exit(1)

    accounts = data if isinstance(data, list) else (
        data.get("result") or data.get("accounts") or data.get("data") or []
    )
    if not accounts:
        print("[ERROR] 계좌를 찾을 수 없습니다. 토스증권 Open API 계좌 접근 권한을 확인하세요.", file=sys.stderr)
        sys.exit(1)

    print(f"[accounts] {len(accounts)}개 계좌 발견")
    for acc in accounts:
        seq = acc.get("accountSeq") or acc.get("accountId") or acc.get("id") or ""
        hint = str(acc.get("accountNumber") or acc.get("number") or "")[-4:]
        print(f"  accountSeq={seq}  (끝 4자리: ***{hint})")
    return accounts


# ── 보유종목 조회 ────────────────────────────────────────────────────
def _get_holdings(token: str, account_seq: str) -> list[dict[str, Any]]:
    print(f"[holdings] 계좌 {account_seq} 보유종목 조회 중...")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tossinvest-Account": str(account_seq),
        "Accept": "application/json",
        "User-Agent": "MONE-SyncToss/1.0",
    }
    try:
        data = _http_get(f"{_TOSS_BASE}/api/v1/holdings", headers)
    except urllib.error.HTTPError:
        sys.exit(1)
    except Exception:
        sys.exit(1)

    result = data.get("result") or data
    if isinstance(result, dict):
        raw = (
            result.get("items")
            or result.get("holdings")
            or result.get("accountBalances")
            or result.get("data")
            or []
        )
    elif isinstance(result, list):
        raw = result
    else:
        raw = []
    return raw


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(
        raw.get("shortCode") or raw.get("isinCode") or raw.get("symbol")
        or raw.get("code") or raw.get("ticker") or ""
    ).strip()
    if not symbol:
        return None

    # ISIN 코드(KR...로 시작)이면 6자리 종목코드 추출
    if symbol.upper().startswith("KR") and len(symbol) == 12:
        symbol = symbol[3:9]

    qty = _safe_float(
        raw.get("holdingQuantity") or raw.get("quantity") or raw.get("qty") or 0
    )
    if qty <= 0:
        return None

    avg = _safe_float(
        raw.get("averagePurchasePrice") or raw.get("averagePrice")
        or raw.get("purchaseUnitPrice") or raw.get("avgPrice") or raw.get("avg_price") or 0
    )
    current = _safe_float(
        raw.get("lastPrice") or raw.get("currentPrice") or raw.get("closePrice")
        or raw.get("price") or 0
    )
    # marketValue: {"amount":"...", "purchaseAmount":"..."} (Toss response)
    mv = raw.get("marketValue")
    eval_amount = 0.0
    if isinstance(mv, dict):
        eval_amount = _safe_float(mv.get("amount") or mv.get("purchaseAmount") or 0)
    elif mv is not None:
        eval_amount = _safe_float(mv)
    valuation = _safe_float(
        raw.get("evaluationAmount") or raw.get("evalAmount") or eval_amount
        or (current * qty if current else 0)
    )
    # profitLoss: {"amount":"...", "rate":"0.36"} — rate is decimal (0.36 = 36%)
    pl = raw.get("profitLoss")
    if isinstance(pl, dict):
        pnl = _safe_float(pl.get("amount") or pl.get("amountAfterCost") or 0)
        pnl_pct = _safe_float(pl.get("rate") or pl.get("rateAfterCost") or 0) * 100
    else:
        pnl = _safe_float(
            raw.get("profitLoss") or raw.get("profitLossAmount") or raw.get("pnl")
            or ((current - avg) * qty if current and avg else 0)
        )
        pnl_pct = _safe_float(
            raw.get("profitLossRate") or raw.get("profitLossRatio") or raw.get("pnlPct")
            or (pnl / (avg * qty) * 100 if avg and qty and avg * qty > 0 else 0)
        )
    name = str(
        raw.get("stockName") or raw.get("name") or raw.get("issueName") or symbol
    ).strip()

    # market 정규화
    market_raw = (
        raw.get("marketCountry") or raw.get("market") or raw.get("marketType")
        or raw.get("exchange") or ""
    )
    # 종목코드로 추정: 6자리 숫자 → kr
    if not market_raw:
        market_raw = "kr" if symbol.isdigit() else "us"
    market = _normalize_market(market_raw)

    # Keep fractional quantities (Toss supports fractional shares)
    qty_out = round(qty, 6) if qty != int(qty) else int(qty)
    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "quantity": qty_out,
        "avgPrice": round(avg, 4),
        "currentPrice": round(current, 2),
        "valuation": round(valuation),
        "pnl": round(pnl),
        "pnlPct": round(pnl_pct, 4),
    }


# ── CSV 저장 ─────────────────────────────────────────────────────────
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
        "--broker", "toss",
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
    parser = argparse.ArgumentParser(description="토스증권 보유종목 조회 → CSV 저장 → (선택) MONE 업로드")
    parser.add_argument("--upload", action="store_true", help="조회 후 MONE에 자동 업로드")
    parser.add_argument("--backend-url", default=_env("MONE_BACKEND_URL", "http://localhost:8050"))
    parser.add_argument("--user-token", default=_env("MONE_USER_TOKEN", ""), help="업로드 시 필요")
    parser.add_argument("--output", default=str(Path(__file__).parents[1] / "data" / "toss_holdings_kr.csv"))
    parser.add_argument("--account-seq", default="", help="특정 계좌 seq 지정 (기본: 첫 번째 계좌)")
    args = parser.parse_args()

    _require_env("TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET")
    client_id = _env("TOSS_CLIENT_ID")
    client_secret = _env("TOSS_CLIENT_SECRET")

    print("[Toss] 보유종목 조회 시작")
    token = _get_token(client_id, client_secret)
    accounts = _get_accounts(token)

    # 계좌 선택
    if args.account_seq:
        acc = next(
            (a for a in accounts if str(a.get("accountSeq") or a.get("id") or "") == args.account_seq),
            None,
        )
        if not acc:
            print(f"[ERROR] 계좌 seq={args.account_seq}를 찾을 수 없습니다.", file=sys.stderr)
            sys.exit(1)
    else:
        acc = accounts[0]

    account_seq = str(acc.get("accountSeq") or acc.get("accountId") or acc.get("id") or "")
    if not account_seq:
        print("[ERROR] accountSeq를 읽을 수 없습니다. 토스증권 API 응답을 확인하세요.", file=sys.stderr)
        sys.exit(1)

    raw_holdings = _get_holdings(token, account_seq)
    if raw_holdings is None or (isinstance(raw_holdings, list) and len(raw_holdings) == 0):
        print("[WARN] 보유종목이 없습니다.")
        items = []
    else:
        items = [n for n in (_normalize_item(r) for r in raw_holdings) if n]
        print(f"[Toss] 총 {len(items)}건 조회 (전체 {len(raw_holdings)}건 중 유효)")

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
