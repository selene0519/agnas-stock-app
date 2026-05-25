from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"


SUMMARY_FALLBACK = [
    {"icon": "01.", "title": "오늘 우선 확인", "desc": "기준가와 손절가를 먼저 확인할 후보", "kind": "action"},
    {"icon": "02.", "title": "눌림목 진입 후보", "desc": "추격보다 기다릴 조건부 진입 후보", "kind": "pullback"},
    {"icon": "03.", "title": "수급 급증 후보", "desc": "거래대금과 수급 흐름을 우선 보는 후보", "kind": "flow"},
    {"icon": "04.", "title": "실적·저평가 후보", "desc": "실적과 밸류를 같이 확인할 후보", "kind": "company"},
    {"icon": "05.", "title": "매수금지·주의", "desc": "신규매수보다 제외·관망이 우선인 후보", "kind": "risk"},
]


def css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --bg:#07111f; --panel:#101c30; --panel2:#14243a; --line:rgba(148,163,184,.24);
          --text:#f8fafc; --muted:#9fb0c8; --dim:#71839d; --accent:#e5a313; --red:#fb4b64;
        }
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
          background: radial-gradient(circle at 18% 0%, rgba(56,189,248,.08), transparent 34%),
                      linear-gradient(180deg,#081322 0%,#07111f 52%,#050c17 100%) !important;
          color:var(--text) !important;
        }
        [data-testid="stHeader"] { background:rgba(7,17,31,.94) !important; border-bottom:1px solid rgba(148,163,184,.14); }
        [data-testid="stSidebar"] { background:linear-gradient(180deg,#091426 0%,#07111f 100%) !important; border-right:1px solid rgba(148,163,184,.18); }
        [data-testid="stSidebar"] * { color:#eef5ff; }
        .block-container { max-width:1360px; padding-top:2rem; padding-bottom:4rem; }
        h1,h2,h3,h4,h5,h6 { color:var(--text) !important; letter-spacing:0; }
        p,li,label,.stMarkdown,.muted { color:var(--muted) !important; }
        .hero { margin-bottom:20px; }
        .hero h1 { font-size:2rem; line-height:1.2; margin-bottom:.35rem; }
        .pill { display:inline-flex; border:1px solid rgba(229,163,19,.45); background:rgba(229,163,19,.14);
                color:#ffe8a3 !important; border-radius:999px; padding:7px 12px; font-weight:900; }
        .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; margin:18px 0; }
        .card { background:linear-gradient(180deg,#14243a 0%,#0f1c30 100%); border:1px solid var(--line);
                border-radius:16px; padding:18px; min-height:176px; box-shadow:0 18px 38px rgba(0,0,0,.24); }
        .card-title { color:var(--text); font-size:1.08rem; line-height:1.35; font-weight:950; word-break:keep-all; }
        .card-desc { color:var(--muted); font-size:.92rem; line-height:1.55; margin-top:10px; }
        .count { color:#fff; font-size:1.8rem; font-weight:950; margin-top:16px; }
        .top { color:var(--dim); font-size:.82rem; line-height:1.45; margin-top:10px; }
        .panel { background:linear-gradient(180deg,rgba(20,36,58,.98),rgba(13,24,41,.98)); border:1px solid var(--line);
                 border-radius:16px; padding:18px; box-shadow:0 18px 42px rgba(0,0,0,.24); margin:14px 0; }
        .stButton > button, .stDownloadButton > button { border-radius:12px; border:1px solid rgba(148,163,184,.28);
          background:rgba(255,255,255,.045); color:var(--text); font-weight:850; }
        .stButton > button:hover, .stDownloadButton > button:hover { border-color:rgba(229,163,19,.72); color:#ffe8a3; background:rgba(229,163,19,.14); }
        [data-testid="stDataFrame"] { border-radius:16px; overflow:hidden; border:1px solid var(--line); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def read_report(*names: str) -> pd.DataFrame:
    for name in names:
        path = REPORT_DIR / name
        if path.exists() and path.stat().st_size > 0:
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
                except Exception:
                    continue
    return pd.DataFrame()


def report(slug: str, kind: str) -> pd.DataFrame:
    files = {
        "summary": [f"v83_today_summary_{slug}.csv", f"v82_today_summary_{slug}.csv"],
        "action": [f"v83_action_cards_{slug}.csv", f"v82_action_cards_{slug}.csv"],
        "pullback": [f"v83_pullback_cards_{slug}.csv", f"v82_pullback_cards_{slug}.csv"],
        "flow": [f"v83_flow_cards_{slug}.csv", f"v83_flow_clean_{slug}.csv", f"v82_flow_cards_{slug}.csv"],
        "company": [f"v83_company_integrated_{slug}.csv", f"v82_company_integrated_{slug}.csv"],
        "risk": [f"v83_risk_cards_{slug}.csv", f"v82_risk_cards_{slug}.csv"],
        "news": [f"v83_news_summary_{slug}.csv", f"v82_news_summary_{slug}.csv"],
        "position": [f"v83_position_cards_{slug}.csv", f"v82_position_cards_{slug}.csv"],
        "snapshot": [f"v83_symbol_snapshot_{slug}.csv", f"v82_symbol_snapshot_{slug}.csv"],
        "future": [f"v83_future_probability_{slug}.csv", f"v82_future_probability_{slug}.csv"],
    }
    return read_report(*files.get(kind, []))


def value(row: Any, *cols: str, default: str = "-") -> str:
    if isinstance(row, dict):
        getter = row.get
    else:
        getter = row.get if hasattr(row, "get") else lambda _c, _d=None: _d
    for col in cols:
        raw = getter(col, "")
        if str(raw).strip() and str(raw).lower() not in {"nan", "none"}:
            return str(raw).strip()
    return default


def display_name(row: Any) -> str:
    name = value(row, "종목명", "종목", "name", default="")
    code = value(row, "종목코드", "ticker", "symbol", default="")
    if name and code and code not in name:
        return f"{name} ({code})"
    return name or code or "-"


def render_hero(title: str, subtitle: str = "") -> None:
    st.markdown(f"<div class='hero'><h1>{title}</h1><div class='muted'>{subtitle}</div></div>", unsafe_allow_html=True)


def summary_cards(slug: str) -> None:
    rows = report(slug, "summary")
    cards: list[str] = []
    for idx, fallback in enumerate(SUMMARY_FALLBACK):
        row = rows.iloc[idx] if not rows.empty and idx < len(rows) else {}
        title = value(row, "카드", "항목", "title", default=fallback["title"])
        desc = value(row, "설명", "요약", "description", default=fallback["desc"])
        count = value(row, "건수", "count", default=str(len(report(slug, fallback["kind"]))))
        top = value(row, "TOP", "대표", "top", default="-")
        cards.append(
            "<div class='card'>"
            f"<div><div class='card-title'>{fallback['icon']} {title}</div><div class='card-desc'>{desc}</div></div>"
            f"<div><div class='count'>{count}개</div><div class='top'>TOP: {top}</div></div>"
            "</div>"
        )
    st.markdown("<div class='grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)


def show_table(df: pd.DataFrame, empty: str, limit: int = 20) -> None:
    if df.empty:
        st.info(empty)
        return
    st.dataframe(df.head(limit), use_container_width=True, hide_index=True)


def show_cards(df: pd.DataFrame, empty: str, limit: int = 12) -> None:
    if df.empty:
        st.info(empty)
        return
    cols = st.columns(3)
    for idx, (_, row) in enumerate(df.head(limit).iterrows()):
        with cols[idx % 3]:
            st.markdown("<div class='panel'>", unsafe_allow_html=True)
            st.markdown(f"#### {display_name(row)}")
            st.caption(value(row, "분류", "시장", "market", default=""))
            st.write(value(row, "요약", "설명", "reason", "추천이유", default="기준가·손절가·수급을 확인하세요."))
            st.caption(value(row, "다음행동", "다음 행동", default="무리한 추격매수는 피하고 조건 확인"))
            st.markdown("</div>", unsafe_allow_html=True)


def run_update() -> None:
    with st.spinner("빠른 갱신 중입니다..."):
        from core.v83_sidebar_update_fix_engine import run_v83_update

        res = run_v83_update(False, False, False)
    if str(res.get("status")) in {"OK", "WARN"}:
        st.success(f"갱신 완료: {res.get('updated_at', '')}")
    else:
        st.error(res)


def main() -> None:
    st.set_page_config(page_title="MONE Fast", page_icon="M", layout="wide")
    css()

    with st.sidebar:
        st.markdown("## MONE")
        st.caption("주식 분석 카드")
        page = st.radio(
            "핵심 메뉴",
            ["홈", "매수 후보", "선택 종목", "보유 관리", "뉴스·기업분석", "확률 예측", "데이터 상태"],
            index=0,
        )
        market_mode = st.radio("시장", ["국장", "미장"], horizontal=True, index=1)
        slug = "kr" if market_mode == "국장" else "us"
        st.caption("기본 실행은 10초 이내 첫 화면을 목표로 한 경량 모드입니다.")

    label = "국장" if slug == "kr" else "미장"
    if page == "홈":
        render_hero(f"{label} 오늘 우선 확인", "먼저 봐야 할 후보만 요약하고, 상세는 메뉴에서 불러옵니다.")
        if st.button("MONE v83 빠른 갱신"):
            run_update()
        summary_cards(slug)
    elif page == "매수 후보":
        render_hero(f"{label} 매수 후보", "오늘 확인·눌림목·수급·실적·주의 후보를 분리해서 봅니다.")
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["오늘 확인", "눌림목", "수급", "실적·저평가", "매수주의"])
        with tab1:
            show_cards(report(slug, "action"), f"{label} 오늘 확인 후보가 없습니다.")
        with tab2:
            show_cards(report(slug, "pullback"), f"{label} 눌림목 후보가 없습니다.")
        with tab3:
            show_cards(report(slug, "flow"), f"{label} 수급 후보가 없습니다.")
        with tab4:
            show_cards(report(slug, "company"), f"{label} 실적·저평가 후보가 없습니다.")
        with tab5:
            show_cards(report(slug, "risk"), f"{label} 매수주의 후보가 없습니다.")
    elif page == "선택 종목":
        render_hero(f"{label} 선택 종목", "현재 시장 기준 후보·스냅샷을 빠르게 확인합니다.")
        show_table(report(slug, "snapshot"), f"{label} 선택 종목 데이터가 없습니다.", limit=40)
    elif page == "보유 관리":
        render_hero(f"{label} 보유 관리", "보유·매도 판단에 필요한 권장수량과 상태를 확인합니다.")
        show_table(report(slug, "position"), f"{label} 보유 관리 데이터가 없습니다.", limit=40)
    elif page == "뉴스·기업분석":
        render_hero(f"{label} 뉴스·기업분석", "뉴스 요약과 기업분석 카드를 나눠 봅니다.")
        tab1, tab2 = st.tabs(["뉴스", "기업분석"])
        with tab1:
            show_cards(report(slug, "news"), f"{label} 뉴스 요약이 없습니다.", limit=9)
        with tab2:
            show_cards(report(slug, "company"), f"{label} 기업분석 데이터가 없습니다.", limit=12)
    elif page == "확률 예측":
        render_hero(f"{label} 확률 예측", "미래확률 표를 원본 기준으로 빠르게 확인합니다.")
        show_table(report(slug, "future"), f"{label} 확률 예측 데이터가 없습니다.", limit=60)
    else:
        render_hero("데이터 상태", "v83 업데이트와 리포트 생성 상태를 확인합니다.")
        show_table(read_report("v83_data_status.csv", "v82_data_status.csv"), "데이터 상태 파일이 없습니다.", limit=50)


if __name__ == "__main__":
    main()
