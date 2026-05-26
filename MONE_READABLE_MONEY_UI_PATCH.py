from pathlib import Path
from datetime import datetime

p = Path("app.py")
s = p.read_text(encoding="utf-8")

backup = Path(f"app_backup_before_readable_money_ui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
backup.write_text(s, encoding="utf-8")

start_marker = "# =========================\n# MONE READABLE MONEY UI PATCH"
end_marker = "# =========================\n# MONE FINAL ENTRYPOINT AFTER ALL OVERRIDES"

# 기존 동일 패치 제거
if start_marker in s and end_marker in s:
    before = s.split(start_marker)[0].rstrip()
    after = end_marker + s.split(end_marker, 1)[1]
    s = before + "\n\n" + after

patch = r'''
# =========================
# MONE READABLE MONEY UI PATCH
# =========================
def _mone_money_parse_num(value: Any) -> float:
    try:
        if value is None:
            return np.nan

        text = str(value).strip()

        if not text or text.lower() in {"nan", "none", "null", "na", "n/a"}:
            return np.nan

        if text in {"-", "확인 필요", "현재가 미수신", "데이터 부족", "가격 데이터 부족", "현재가 없음"}:
            return np.nan

        for token in ["₩", "원", "$", "USD", "KRW", ",", " "]:
            text = text.replace(token, "")

        text = text.replace("%", "")

        if not text:
            return np.nan

        return float(text)

    except Exception:
        return np.nan


def _mone_money_market(value: Any = None, market: Any = None, row: Any = None) -> str:
    texts = []

    for x in [market, value]:
        if x is not None:
            texts.append(str(x))

    try:
        if row is not None and hasattr(row, "get"):
            for c in ["market", "시장", "market_name", "시장구분"]:
                v = row.get(c, "")
                if v is not None:
                    texts.append(str(v))

            for c in ["symbol", "ticker", "code", "종목코드"]:
                v = str(row.get(c, "") or "").strip()
                if v:
                    if v.isdigit() or (len(v) >= 6 and v[:6].isdigit()):
                        texts.append("한국주식")
                    else:
                        texts.append("미국주식")
    except Exception:
        pass

    joined = " ".join(texts).lower()

    if "$" in joined or "usd" in joined or "미국" in joined or "미장" in joined or "us" in joined:
        return "us"

    if "₩" in joined or "원" in joined or "krw" in joined or "한국" in joined or "국장" in joined or "kr" in joined:
        return "kr"

    return "kr"


def _mone_money_format(value: Any, market: Any = None, missing: str = "현재가 없음") -> str:
    n = _mone_money_parse_num(value)

    if np.isnan(n) or n <= 0:
        return missing

    m = _mone_money_market(value=value, market=market)

    if m == "us":
        return f"${n:,.2f}"

    return f"₩{n:,.0f}"


def _mone_money_from_row(row: Any, keys: Any, default: str = "현재가 없음") -> str:
    if isinstance(keys, str):
        keys = [keys]

    try:
        for k in keys:
            if hasattr(row, "get"):
                v = row.get(k, "")
            else:
                v = ""

            text = str(v or "").strip()
            if text and text not in {"-", "확인 필요", "현재가 미수신", "데이터 부족"}:
                return _mone_money_format(v, row=row, missing=default)
    except Exception:
        pass

    return default


# 기존 fmt_price를 보기 좋은 원/달러 표기로 통일
def fmt_price(price: Any, market: Any = "") -> str:
    return _mone_money_format(price, market=market, missing="현재가 없음")


# 여러 화면에서 쓰는 가격 표시 함수들을 보기 좋은 표기로 통일
def _format_price_display_cell(value: Any, *args: Any, **kwargs: Any) -> str:
    market = kwargs.get("market", "")
    if not market and args:
        market = args[0]
    return _mone_money_format(value, market=market, missing="현재가 없음")


def _format_price_or_reason(row_or_value: Any, key: Any = None, default: str = "현재가 없음", *args: Any, **kwargs: Any) -> str:
    try:
        if hasattr(row_or_value, "get") and key is not None:
            return _mone_money_from_row(row_or_value, [key], default=default)

        market = kwargs.get("market", "")
        if args and not market:
            market = args[0]

        return _mone_money_format(row_or_value, market=market, missing=default)
    except Exception:
        return default


def _home_price_or_reason(row: Any, keys: Any, default: str = "현재가 없음", *args: Any, **kwargs: Any) -> str:
    return _mone_money_from_row(row, keys, default=default)


def _candidate_pick_price(row: Any, keys: Any, default: str = "현재가 없음", *args: Any, **kwargs: Any) -> str:
    return _mone_money_from_row(row, keys, default=default)


# 보유종목/선택종목 화면에서 직접 쓰는 보조 포맷도 통일
def _mone_clean_display_price(value: Any, market: Any = "") -> str:
    return _mone_money_format(value, market=market, missing="현재가 없음")
'''

if end_marker in s:
    s = s.replace(end_marker, patch.rstrip() + "\n\n" + end_marker)
else:
    s = s.rstrip() + "\n\n" + patch

p.write_text(s, encoding="utf-8")

print("OK: readable money UI patch inserted")
print("BACKUP:", backup)
