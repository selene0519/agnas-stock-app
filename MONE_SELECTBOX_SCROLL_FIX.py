from pathlib import Path
from datetime import datetime

p = Path("app.py")
s = p.read_text(encoding="utf-8")

backup = Path(f"app_backup_before_selectbox_scroll_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
backup.write_text(s, encoding="utf-8")

start_marker = "# =========================\n# MONE SELECTBOX SCROLL FIX"
end_marker = "# =========================\n# MONE FINAL ENTRYPOINT AFTER ALL OVERRIDES"

# 기존 동일 패치 제거
if start_marker in s and end_marker in s:
    before = s.split(start_marker)[0].rstrip()
    after = end_marker + s.split(end_marker, 1)[1]
    s = before + "\n\n" + after

patch = r'''
# =========================
# MONE SELECTBOX SCROLL FIX
# =========================
def _mone_selectbox_scroll_fix_css() -> None:
    try:
        st.markdown("""
        <style>
        /* 전체 페이지 스크롤 복구 */
        html, body {
            overflow-y: auto !important;
            height: auto !important;
        }

        .stApp {
            overflow-y: auto !important;
        }

        section.main {
            overflow-y: auto !important;
        }

        div[data-testid="stAppViewContainer"] {
            overflow-y: auto !important;
        }

        div[data-testid="stVerticalBlock"] {
            overflow: visible !important;
        }

        /* 사이드바 스크롤 복구 */
        section[data-testid="stSidebar"] {
            overflow-y: auto !important;
        }

        section[data-testid="stSidebar"] > div {
            overflow-y: auto !important;
        }

        /* Streamlit selectbox dropdown 높이 제한 + 내부 스크롤 */
        div[data-baseweb="popover"] {
            max-height: 360px !important;
            overflow-y: auto !important;
            z-index: 999999 !important;
        }

        div[data-baseweb="popover"] ul {
            max-height: 340px !important;
            overflow-y: auto !important;
        }

        ul[role="listbox"] {
            max-height: 340px !important;
            overflow-y: auto !important;
        }

        div[role="listbox"] {
            max-height: 340px !important;
            overflow-y: auto !important;
        }

        li[role="option"] {
            min-height: 36px !important;
            padding-top: 6px !important;
            padding-bottom: 6px !important;
            font-size: 0.92rem !important;
        }

        div[role="option"] {
            min-height: 36px !important;
            padding-top: 6px !important;
            padding-bottom: 6px !important;
            font-size: 0.92rem !important;
        }

        /* 선택박스 자체가 너무 커지지 않게 */
        div[data-baseweb="select"] {
            font-size: 0.95rem !important;
        }

        /* 빨간 테두리 선택박스가 너무 크게 보이는 문제 완화 */
        div[data-baseweb="select"] > div {
            min-height: 42px !important;
        }

        /* 드롭다운이 화면 하단을 덮을 때 마우스휠 작동 보강 */
        [data-baseweb="menu"] {
            max-height: 340px !important;
            overflow-y: auto !important;
        }

        /* 표/카드 영역은 화면 밖으로 나가도 페이지 스크롤로 접근 가능 */
        .block-container {
            overflow: visible !important;
            padding-bottom: 3rem !important;
        }
        </style>
        """, unsafe_allow_html=True)
    except Exception:
        pass


try:
    _mone_original_main_before_selectbox_scroll_fix = main

    def main():
        _mone_selectbox_scroll_fix_css()
        return _mone_original_main_before_selectbox_scroll_fix()
except Exception:
    pass
'''

if end_marker in s:
    s = s.replace(end_marker, patch.rstrip() + "\n\n" + end_marker)
else:
    s = s.rstrip() + "\n\n" + patch

p.write_text(s, encoding="utf-8")

print("OK: selectbox scroll fix inserted")
print("BACKUP:", backup)
