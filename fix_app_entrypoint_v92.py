from pathlib import Path
from datetime import datetime

p = Path("app.py")
s = p.read_text(encoding="utf-8")

backup = Path(f"app_backup_before_entrypoint_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
backup.write_text(s, encoding="utf-8")

marker = "# =========================\n# MONE v92 Stable Update Override"
idx = s.find(marker)

if idx == -1:
    raise SystemExit("ERROR: MONE v92 Stable Update Override marker not found")

start = s.rfind("\n# Final call must stay", 0, idx)

if start == -1:
    raise SystemExit("ERROR: old __main__ block marker not found")

# 기존 __main__ 실행 블록을 v92 override 앞에서 제거
s = s[:start] + "\n\n" + s[idx:]

# 혹시 이전 패치가 있다면 중복 제거
final_marker = "# =========================\n# MONE FINAL ENTRYPOINT AFTER ALL OVERRIDES"
if final_marker in s:
    s = s.split(final_marker)[0].rstrip() + "\n\n"

final_block = r'''
# =========================
# MONE FINAL ENTRYPOINT AFTER ALL OVERRIDES
# =========================
if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--runner":
        raise SystemExit(run_headless_runner(sys.argv[2]))
    try:
        main()
    except Exception as e:
        log_app_event("streamlit_main", "error", f"{type(e).__name__}: {e}")
        st.error("앱 실행 중 오류가 발생했습니다. 관리자 모드에서 오류 로그를 확인하세요.")
'''

s = s.rstrip() + "\n\n" + final_block.lstrip()

p.write_text(s, encoding="utf-8")

print("OK: app.py entrypoint moved after all overrides")
print("BACKUP:", backup)
