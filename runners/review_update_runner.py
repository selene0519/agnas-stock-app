from __future__ import annotations

from core.review_actual_update_engine import run_review_actual_update

if __name__ == "__main__":
    updated, stats = run_review_actual_update()
    print({
        "updated_rows": stats.updated_rows,
        "filled_cells": stats.filled_cells,
        "fetch_failed": stats.fetch_failed,
        "output_rows": stats.output_rows,
    })
