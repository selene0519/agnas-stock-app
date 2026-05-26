from pathlib import Path
from datetime import datetime

p = Path("app.py")
s = p.read_text(encoding="utf-8")

backup = Path(f"app_backup_before_absolute_final_binding_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
backup.write_text(s, encoding="utf-8")

start_marker = "# =========================\n# MONE ABSOLUTE FINAL DATA BINDING"
end_marker = "# =========================\n# MONE FINAL ENTRYPOINT AFTER ALL OVERRIDES"

# 기존 ABSOLUTE FINAL 패치가 있으면 제거
if start_marker in s and end_marker in s:
    before = s.split(start_marker)[0].rstrip()
    after = end_marker + s.split(end_marker, 1)[1]
    s = before + "\n\n" + after

if end_marker not in s:
    raise SystemExit("ERROR: final entrypoint marker not found")

patch = r'''
# =========================
# MONE ABSOLUTE FINAL DATA BINDING
# =========================
def _mone_abs_market(slug: str = "") -> str:
    text = str(slug or "").lower()
    if text in {"us", "usa", "미장", "미국", "미국주식"} or "us" in text or "미국" in text or "미장" in text:
        return "us"
    return "kr"


def _mone_abs_read_csv(path) -> pd.DataFrame:
    try:
        path = Path(path)
        if not path.exists() or path.stat().st_size <= 0:
            return pd.DataFrame()

        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False).fillna("")
            except Exception:
                continue
    except Exception:
        pass
    return pd.DataFrame()


def _mone_abs_candidates(slug: str, kind: str) -> pd.DataFrame:
    m = _mone_abs_market(slug)
    k = str(kind or "").lower().strip()

    file_map = {
        "summary": [
            f"v92_today_summary_{m}.csv",
            f"v91_today_summary_{m}.csv",
        ],
        "action": [
            f"v92_action_cards_{m}.csv",
            f"v91_action_cards_{m}.csv",
        ],
        "pullback": [
            f"v92_pullback_cards_{m}.csv",
            f"v91_pullback_cards_{m}.csv",
        ],
        "flow": [
            f"v92_flow_cards_{m}.csv",
            f"v92_flow_clean_{m}.csv",
            f"v91_flow_cards_{m}.csv",
            f"v91_flow_clean_{m}.csv",
        ],
        "company": [
            f"v92_company_integrated_{m}.csv",
            f"v92_company_summary_cards_{m}.csv",
            f"v92_company_cards_{m}.csv",
            f"v92_kpi_cards_{m}.csv",
            f"v91_company_integrated_{m}.csv",
            f"v91_company_summary_cards_{m}.csv",
            f"v91_company_cards_{m}.csv",
            f"v91_kpi_cards_{m}.csv",
        ],
        "risk": [
            f"v92_risk_cards_{m}.csv",
            f"v91_risk_cards_{m}.csv",
        ],
        "position": [
            f"v92_position_cards_{m}.csv",
            f"v91_position_cards_{m}.csv",
        ],
        "future": [
            f"v92_future_probability_{m}.csv",
            f"v91_future_probability_{m}.csv",
        ],
        "snapshot": [
            f"v92_symbol_snapshot_{m}.csv",
            f"v91_symbol_snapshot_{m}.csv",
        ],
        "status": [
            f"v92_data_status_{m}.csv",
            f"v92_data_status.csv",
            f"v91_data_status_{m}.csv",
            f"v91_data_status.csv",
        ],
    }

    for name in file_map.get(k, []):
        df = _mone_abs_read_csv(REPORT_DIR / name)
        if df is not None and not df.empty:
            df = df.copy()
            df["_source_file"] = name
            return df

    return pd.DataFrame()


def _mone_abs_display_name(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "-"

    row = df.iloc[0]

    for c in [
        "종목명", "stock_name", "name", "company", "종목",
        "symbol", "ticker", "종목코드", "code"
    ]:
        if c in df.columns:
            v = str(row.get(c, "") or "").strip()
            if v and v.lower() not in {"nan", "none", "확인 필요"}:
                return v

    return "-"


def _mone_abs_summary_rows(slug: str) -> list[dict[str, Any]]:
    action = _mone_abs_candidates(slug, "action")
    pullback = _mone_abs_candidates(slug, "pullback")
    flow = _mone_abs_candidates(slug, "flow")
    company = _mone_abs_candidates(slug, "company")
    risk = _mone_abs_candidates(slug, "risk")

    return [
        {
            "아이콘": "🎯",
            "카드": "오늘 우선 확인",
            "설명": "직전가·기준가·손절가를 먼저 확인할 후보",
            "건수": int(len(action)),
            "TOP": _mone_abs_display_name(action),
            "구분": "buy",
        },
        {
            "아이콘": "🪜",
            "카드": "눌림목 진입 후보",
            "설명": "추격보다 눌림 조건부 진입을 기다릴 후보",
            "건수": int(len(pullback)),
            "TOP": _mone_abs_display_name(pullback),
            "구분": "buy",
        },
        {
            "아이콘": "💚",
            "카드": "수급 급증 후보",
            "설명": "수급·거래대금 흐름을 우선 보는 후보",
            "건수": int(len(flow)),
            "TOP": _mone_abs_display_name(flow),
            "구분": "flow",
        },
        {
            "아이콘": "💎",
            "카드": "실적·저평가 후보",
            "설명": "실적과 밸류를 함께 확인할 후보",
            "건수": int(len(company)),
            "TOP": _mone_abs_display_name(company),
            "구분": "company",
        },
        {
            "아이콘": "🚫",
            "카드": "매수금지·주의",
            "설명": "신규매수보다 제외·관망이 우선인 후보",
            "건수": int(len(risk)),
            "TOP": _mone_abs_display_name(risk),
            "구분": "risk",
        },
    ]


# 핵심 후보 로더를 제일 마지막에 다시 연결
try:
    _v85_candidates = _mone_abs_candidates
except Exception:
    pass

try:
    _v84_candidates = _mone_abs_candidates
except Exception:
    pass

try:
    _v81_candidates = _mone_abs_candidates
except Exception:
    pass

try:
    _v80_candidates = _mone_abs_candidates
except Exception:
    pass

try:
    _v79_candidates_for = _mone_abs_candidates
except Exception:
    pass

try:
    _v91_candidates = _mone_abs_candidates
except Exception:
    pass


# 홈 카드 요약 로더를 제일 마지막에 다시 연결
try:
    _v85_build_summary_rows = _mone_abs_summary_rows
except Exception:
    pass

try:
    _v84_build_summary_rows = _mone_abs_summary_rows
except Exception:
    pass

try:
    _v81_summary_rows = _mone_abs_summary_rows
except Exception:
    pass

try:
    _v91_build_summary_rows = _mone_abs_summary_rows
except Exception:
    pass

try:
    _mone_force_v92_summary_rows = _mone_abs_summary_rows
except Exception:
    pass

try:
    _mone_data_restore_summary_rows = _mone_abs_summary_rows
except Exception:
    pass

try:
    _mone_force_v92_candidates = _mone_abs_candidates
except Exception:
    pass

try:
    _mone_data_restore_candidates = _mone_abs_candidates
except Exception:
    pass
'''

s = s.replace(end_marker, patch.rstrip() + "\n\n" + end_marker)

p.write_text(s, encoding="utf-8")

print("OK: absolute final data binding inserted")
print("BACKUP:", backup)
