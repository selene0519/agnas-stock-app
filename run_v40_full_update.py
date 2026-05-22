from __future__ import annotations

import json

from core.v40_analysis_engine import save_v40_reports

if __name__ == "__main__":
    print(json.dumps(save_v40_reports(), ensure_ascii=False, indent=2))
