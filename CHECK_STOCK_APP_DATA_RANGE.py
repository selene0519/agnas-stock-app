from pathlib import Path
import pandas as pd
import json

OLD = Path(r"C:\Users\minbo\OneDrive\바탕 화면\stock_app\stock_app")
CURRENT = Path(r"C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app")

DATE_CANDIDATES = [
    "date", "target_date", "created_at", "updated_at", "prediction_date",
    "trade_date", "run_date", "timestamp", "datetime", "time",
    "scan_time", "scan_time_kst", "last_updated", "last_update",
    "결과일", "예측일", "작성일", "갱신일", "날짜", "시간"
]

TARGET_PATTERNS = [
    "*.csv",
    "*.json"
]

IMPORTANT_NAMES = [
    "watchlist",
    "candidate",
    "prediction",
    "predictions",
    "outcome",
    "holding",
    "holdings",
    "history",
    "report",
    "v91",
    "v92",
    "v93",
    "operational"
]


def read_csv_safely(path: Path) -> pd.DataFrame:
    for enc in ["utf-8-sig", "utf-8", "cp949"]:
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False).fillna("")
        except Exception:
            pass
    return pd.DataFrame()


def find_date_range_in_csv(path: Path):
    df = read_csv_safely(path)
    if df.empty:
        return None

    found = []

    for col in df.columns:
        col_l = str(col).strip().lower()
        if any(k.lower() in col_l for k in DATE_CANDIDATES):
            s = pd.to_datetime(df[col], errors="coerce")
            s = s.dropna()
            if len(s) > 0:
                found.append({
                    "column": col,
                    "min": s.min(),
                    "max": s.max(),
                    "valid_dates": len(s),
                    "rows": len(df)
                })

    if not found:
        return {
            "rows": len(df),
            "date_column": "",
            "min_date": "",
            "max_date": "",
            "valid_dates": 0
        }

    # 가장 날짜 인식이 많이 된 컬럼 선택
    best = sorted(found, key=lambda x: x["valid_dates"], reverse=True)[0]
    return {
        "rows": best["rows"],
        "date_column": best["column"],
        "min_date": str(best["min"]),
        "max_date": str(best["max"]),
        "valid_dates": best["valid_dates"]
    }


def find_date_range_in_json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    text = json.dumps(data, ensure_ascii=False)
    dates = []

    # 간단한 날짜 패턴 탐색
    import re
    for m in re.findall(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?", text):
        try:
            dates.append(pd.to_datetime(m))
        except Exception:
            pass

    if dates:
        return {
            "rows": "",
            "date_column": "json_date_pattern",
            "min_date": str(min(dates)),
            "max_date": str(max(dates)),
            "valid_dates": len(dates)
        }

    return {
        "rows": "",
        "date_column": "",
        "min_date": "",
        "max_date": "",
        "valid_dates": 0
    }


def scan_folder(root: Path, label: str):
    rows = []

    if not root.exists():
        print(f"[MISSING FOLDER] {root}")
        return pd.DataFrame()

    files = []
    for pattern in TARGET_PATTERNS:
        files.extend(root.rglob(pattern))

    for path in files:
        rel = str(path.relative_to(root))
        name_l = path.name.lower()
        rel_l = rel.lower()

        if not any(k in name_l or k in rel_l for k in IMPORTANT_NAMES):
            continue

        try:
            stat = path.stat()
            size = stat.st_size
            mtime = pd.to_datetime(stat.st_mtime, unit="s")
        except Exception:
            size = 0
            mtime = ""

        if path.suffix.lower() == ".csv":
            info = find_date_range_in_csv(path)
        elif path.suffix.lower() == ".json":
            info = find_date_range_in_json(path)
        else:
            info = None

        if info is None:
            info = {
                "rows": "",
                "date_column": "",
                "min_date": "",
                "max_date": "",
                "valid_dates": 0
            }

        rows.append({
            "source": label,
            "file": rel,
            "size_bytes": size,
            "modified_time": str(mtime),
            "rows": info.get("rows", ""),
            "date_column": info.get("date_column", ""),
            "min_date": info.get("min_date", ""),
            "max_date": info.get("max_date", ""),
            "valid_dates": info.get("valid_dates", 0)
        })

    return pd.DataFrame(rows)


old_df = scan_folder(OLD, "OLD_STOCK_APP")
cur_df = scan_folder(CURRENT, "CURRENT_GITHUB_APP")

out = pd.concat([old_df, cur_df], ignore_index=True)

if out.empty:
    print("No matching files found.")
else:
    out = out.sort_values(["source", "file"]).reset_index(drop=True)

    print("\n=== DATA RANGE SUMMARY ===")
    display_cols = [
        "source", "file", "size_bytes", "rows",
        "date_column", "min_date", "max_date", "valid_dates", "modified_time"
    ]
    print(out[display_cols].to_string(index=False))

    out_path = CURRENT / "stock_app_data_range_summary.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\n[OK] Saved summary:")
    print(out_path)
