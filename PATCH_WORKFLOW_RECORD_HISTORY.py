from __future__ import annotations

from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "mone-auto-accumulator.yml"

STEP = """\n      - name: Record virtual operation history\n        run: |\n          python mone-web-app/backend/record_operation_history.py --market all --modes all --source github-actions --backfill-existing\n"""

if not WORKFLOW.exists():
    raise FileNotFoundError(f"workflow 파일을 찾지 못했습니다: {WORKFLOW}")

text = WORKFLOW.read_text(encoding="utf-8")
if "Record virtual operation history" in text:
    print("OK: 이미 기록 저장 step이 있습니다.")
    raise SystemExit(0)

backup = WORKFLOW.with_suffix(WORKFLOW.suffix + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
backup.write_text(text, encoding="utf-8")

anchors = [
    "      - name: Show generated report status",
    "      - name: Commit generated data",
    "      - name: Commit updated reports",
]
for anchor in anchors:
    if anchor in text:
        text = text.replace(anchor, STEP + "\n" + anchor, 1)
        break
else:
    text = text.rstrip() + "\n" + STEP + "\n"

WORKFLOW.write_text(text, encoding="utf-8")
print("OK: workflow에 가상 운용/예측 스냅샷 기록 step을 추가했습니다.")
print("Backup:", backup)
