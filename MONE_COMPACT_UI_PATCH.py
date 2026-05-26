from pathlib import Path
from datetime import datetime

p = Path("app.py")
s = p.read_text(encoding="utf-8")

backup = Path(f"app_backup_before_compact_ui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
backup.write_text(s, encoding="utf-8")

start_marker = "# =========================\n# MONE COMPACT UI PATCH"
end_marker = "# =========================\n# MONE FINAL ENTRYPOINT AFTER ALL OVERRIDES"

# 기존 compact 패치 제거
if start_marker in s and end_marker in s:
    before = s.split(start_marker)[0].rstrip()
    after = end_marker + s.split(end_marker, 1)[1]
    s = before + "\n\n" + after

patch = r'''
# =========================
# MONE COMPACT UI PATCH
# =========================
def _mone_compact_ui_css() -> None:
    try:
        st.markdown("""
        <style>
        /* 전체 여백 축소 */
        .block-container {
            max-width: 100% !important;
            padding-top: 1.0rem !important;
            padding-left: 1.2rem !important;
            padding-right: 1.2rem !important;
            padding-bottom: 1.5rem !important;
        }

        /* 기본 글자 크기 축소 */
        html, body, [class*="css"] {
            font-size: 14px !important;
        }

        /* 제목 크기 축소 */
        h1 {
            font-size: 1.85rem !important;
            line-height: 1.15 !important;
            margin-bottom: 0.6rem !important;
        }

        h2 {
            font-size: 1.35rem !important;
            line-height: 1.2 !important;
            margin-bottom: 0.5rem !important;
        }

        h3 {
            font-size: 1.12rem !important;
            line-height: 1.25 !important;
            margin-bottom: 0.4rem !important;
        }

        p, li, span, div {
            line-height: 1.45 !important;
        }

        /* 사이드바 폭/버튼 압축 */
        section[data-testid="stSidebar"] {
            width: 300px !important;
            min-width: 300px !important;
        }

        section[data-testid="stSidebar"] button {
            min-height: 2.35rem !important;
            height: 2.35rem !important;
            padding: 0.35rem 0.65rem !important;
            font-size: 0.92rem !important;
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
            font-size: 1.0rem !important;
        }

        /* 버튼 축소 */
        div[data-testid="stButton"] button {
            min-height: 2.35rem !important;
            padding: 0.35rem 0.8rem !important;
            font-size: 0.92rem !important;
            border-radius: 0.65rem !important;
        }

        /* 카드/컨테이너 간격 축소 */
        div[data-testid="stVerticalBlock"] {
            gap: 0.55rem !important;
        }

        div[data-testid="column"] {
            padding-left: 0.25rem !important;
            padding-right: 0.25rem !important;
        }

        /* Metric 크기 축소 */
        div[data-testid="stMetric"] {
            padding: 0.45rem 0.55rem !important;
        }

        div[data-testid="stMetricLabel"] {
            font-size: 0.78rem !important;
        }

        div[data-testid="stMetricValue"] {
            font-size: 1.35rem !important;
        }

        div[data-testid="stMetricDelta"] {
            font-size: 0.78rem !important;
        }

        /* 커스텀 카드류 강제 축소 */
        .mone-card,
        .mone-home-card,
        .mode-card,
        .v85-card,
        .v91-card,
        .quick-card,
        .judge-card,
        .tk-card,
        .metric-card,
        .home-card {
            padding: 0.85rem !important;
            border-radius: 0.9rem !important;
            min-height: auto !important;
        }

        .mone-card h1,
        .mone-card h2,
        .mone-card h3,
        .mone-home-card h1,
        .mone-home-card h2,
        .mone-home-card h3,
        .mode-card h1,
        .mode-card h2,
        .mode-card h3,
        .v85-card h1,
        .v85-card h2,
        .v85-card h3,
        .v91-card h1,
        .v91-card h2,
        .v91-card h3,
        .home-card h1,
        .home-card h2,
        .home-card h3 {
            font-size: 1.1rem !important;
            line-height: 1.25 !important;
            word-break: keep-all !important;
            white-space: normal !important;
        }

        /* 카드 내부 큰 숫자 축소 */
        .mone-card b,
        .mone-home-card b,
        .mode-card b,
        .v85-card b,
        .v91-card b,
        .home-card b {
            font-size: 1.15rem !important;
            line-height: 1.25 !important;
        }

        /* markdown 안의 큰 글자 강제 완화 */
        .stMarkdown div {
            word-break: keep-all !important;
            overflow-wrap: break-word !important;
        }

        .stMarkdown strong {
            font-size: inherit !important;
        }

        /* 표 높이/글자 축소 */
        div[data-testid="stDataFrame"] {
            font-size: 0.82rem !important;
        }

        table {
            font-size: 0.82rem !important;
        }

        th, td {
            padding: 0.28rem 0.45rem !important;
            white-space: nowrap !important;
        }

        /* expander 축소 */
        details {
            padding: 0.25rem 0 !important;
        }

        details summary {
            font-size: 0.92rem !important;
        }

        /* 탭 축소 */
        button[data-baseweb="tab"] {
            padding: 0.45rem 0.7rem !important;
            font-size: 0.9rem !important;
        }

        /* 화면이 좁을 때 카드가 너무 커지는 것 방지 */
        @media (max-width: 1400px) {
            .block-container {
                padding-left: 0.8rem !important;
                padding-right: 0.8rem !important;
            }

            h1 {
                font-size: 1.55rem !important;
            }

            h2 {
                font-size: 1.2rem !important;
            }

            div[data-testid="stMetricValue"] {
                font-size: 1.15rem !important;
            }
        }
        </style>
        """, unsafe_allow_html=True)
    except Exception:
        pass


# main 실행 직전에 compact CSS를 항상 먼저 주입
try:
    _mone_original_main_before_compact_ui = main

    def main():
        _mone_compact_ui_css()
        return _mone_original_main_before_compact_ui()
except Exception:
    pass
'''

if end_marker in s:
    s = s.replace(end_marker, patch.rstrip() + "\n\n" + end_marker)
else:
    s = s.rstrip() + "\n\n" + patch

p.write_text(s, encoding="utf-8")

print("OK: compact UI patch inserted")
print("BACKUP:", backup)
