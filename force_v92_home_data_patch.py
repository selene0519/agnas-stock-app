from pathlib import Path
from datetime import datetime

p = Path("app.py")
s = p.read_text(encoding="utf-8")

backup = Path(f"app_backup_before_force_v92_home_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
backup.write_text(s, encoding="utf-8")

patch = r'''

# =========================
# MONE FORCE V92 HOME DATA OVERRIDE
# =========================
def _mone_force_market_slug(slug: str = "") -> str:
    text = str(slug or "").lower()
    if "us" in text or "미국" in text:
        return "us"
    return "kr"


def _mone_force_read_csv(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size <= 0:
            return pd.DataFrame()
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                return pd.read_csv(path, encoding=enc, dtype=str).fillna("")
            except Exception:
                continue
    except Exception:
        pass
    return pd.DataFrame()


def _mone_force_v92_candidates(slug: str, kind: str) -> pd.DataFrame:
    m = _mone_force_market_slug(slug)
    k = str(kind or "").lower().strip()

    files = {
        "summary": [
            f"v92_today_summary_{m}.csv",
        ],
        "action": [
            f"v92_action_cards_{m}.csv",
        ],
        "pullback": [
            f"v92_pullback_cards_{m}.csv",
        ],
        "flow": [
            f"v92_flow_cards_{m}.csv",
            f"v92_flow_clean_{m}.csv",
        ],
        "company": [
            f"v92_company_integrated_{m}.csv",
            f"v92_company_summary_cards_{m}.csv",
            f"v92_company_cards_{m}.csv",
            f"v92_kpi_cards_{m}.csv",
        ],
        "risk": [
            f"v92_risk_cards_{m}.csv",
        ],
        "position": [
            f"v92_position_cards_{m}.csv",
        ],
        "future": [
            f"v92_future_probability_{m}.csv",
        ],
        "news": [
            f"v92_news_summary_{m}.csv",
            f"v92_narrative_cards_{m}.csv",
        ],
        "status": [
            f"v92_data_status_{m}.csv",
            "v92_data_status.csv",
        ],
    }

    for name in files.get(k, []):
        df = _mone_force_read_csv(REPORT_DIR / name)
        if df is not None and not df.empty:
            df = df.copy()
            df["_source_file"] = name
            return df
    return pd.DataFrame()


def _mone_force_display_name(row: Any) -> str:
    try:
        for c in ["종목명", "name", "stock_name", "company", "종목", "symbol", "ticker", "종목코드", "code"]:
            if hasattr(row, "get"):
                v = str(row.get(c, "") or "").strip()
                if v and v.lower() not in {"nan", "none"}:
                    return v
    except Exception:
        pass
    return "-"


def _mone_force_v92_summary_rows(slug: str) -> list[dict[str, Any]]:
    action = _mone_force_v92_candidates(slug, "action")
    pull = _mone_force_v92_candidates(slug, "pullback")
    flow = _mone_force_v92_candidates(slug, "flow")
    company = _mone_force_v92_candidates(slug, "company")
    risk = _mone_force_v92_candidates(slug, "risk")

    def top(df: pd.DataFrame) -> str:
        if df is None or df.empty:
            return "-"
        return _mone_force_display_name(df.iloc[0])

    return [
        {"아이콘": "🎯", "카드": "오늘 우선 확인", "설명": "직전가·기준가·손절가를 먼저 확인할 후보", "건수": len(action), "TOP": top(action), "구분": "buy"},
        {"아이콘": "🪜", "카드": "눌림목 진입 후보", "설명": "추격보다 눌림 조건부 진입을 기다릴 후보", "건수": len(pull), "TOP": top(pull), "구분": "buy"},
        {"아이콘": "💚", "카드": "수급 급증 후보", "설명": "수급·거래대금 흐름을 우선 보는 후보", "건수": len(flow), "TOP": top(flow), "구분": "flow"},
        {"아이콘": "💎", "카드": "실적·저평가 후보", "설명": "실적과 밸류를 함께 확인할 후보", "건수": len(company), "TOP": top(company), "구분": "company"},
        {"아이콘": "🚫", "카드": "매수금지·주의", "설명": "신규매수보다 제외·관망이 우선인 후보", "건수": len(risk), "TOP": top(risk), "구분": "risk"},
    ]


# 홈 카드/상세 후보 로더를 v92 실제 파일 기준으로 강제 연결
try:
    _v85_candidates = _mone_force_v92_candidates
    _v85_build_summary_rows = _mone_force_v92_summary_rows
except Exception:
    pass

try:
    _v84_candidates = _mone_force_v92_candidates
    _v84_build_summary_rows = _mone_force_v92_summary_rows
except Exception:
    pass

try:
    _v81_candidates = _mone_force_v92_candidates
    _v81_summary_rows = _mone_force_v92_summary_rows
except Exception:
    pass

try:
    _v80_candidates = _mone_force_v92_candidates
except Exception:
    pass

try:
    _v79_candidates_for = _mone_force_v92_candidates
except Exception:
    pass

try:
    _v91_candidates = _mone_force_v92_candidates
    _v91_build_summary_rows = _mone_force_v92_summary_rows
except Exception:
    pass
'''

marker = "# =========================\n# MONE FINAL ENTRYPOINT AFTER ALL OVERRIDES"

if marker in s:
    s = s.replace(marker, patch + "\n\n" + marker)
else:
    # final entrypoint marker가 없으면 맨 아래에 추가
    s = s.rstrip() + "\n\n" + patch + "\n"

p.write_text(s, encoding="utf-8")

print("OK: forced v92 home data override inserted")
print("BACKUP:", backup)
