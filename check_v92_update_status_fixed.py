from pathlib import Path
import json
import csv

try:
    import pandas as pd
except Exception:
    pd = None


REPORT_DIR = Path("reports")


CORE_REQUIRED = [
    "v92_today_summary_kr.csv",
    "v92_today_summary_us.csv",
    "v92_symbol_snapshot_kr.csv",
    "v92_symbol_snapshot_us.csv",
]

# app.py에서 우선적으로 찾는 파일명입니다.
# 없으면 앱 일부 화면에서 fallback 또는 빈 화면이 발생할 수 있으므로 별도로 경고합니다.
APP_EXPECTED = [
    "v92_confidence_cards_kr.csv",
    "v92_confidence_cards_us.csv",
    "v92_operational_dashboard_kr.csv",
    "v92_operational_dashboard_us.csv",
]

# 현재 reports 폴더에 실제로 생성되는 v92 세부 리포트 후보들입니다.
# confidence/dashboard 파일이 없더라도 이 파일들이 있으면 v92 리포트 생성 자체는 돌아간 것으로 판단합니다.
ALTERNATIVE_GROUPS = {
    "confidence_related_kr": [
        "v92_action_cards_kr.csv",
        "v92_kpi_cards_kr.csv",
        "v92_risk_cards_kr.csv",
        "v92_flow_cards_kr.csv",
        "v92_position_cards_kr.csv",
        "v92_future_probability_kr.csv",
        "v92_pullback_cards_kr.csv",
    ],
    "confidence_related_us": [
        "v92_action_cards_us.csv",
        "v92_kpi_cards_us.csv",
        "v92_risk_cards_us.csv",
        "v92_flow_cards_us.csv",
        "v92_position_cards_us.csv",
        "v92_future_probability_us.csv",
        "v92_pullback_cards_us.csv",
    ],
    "dashboard_related_kr": [
        "v92_data_status_kr.csv",
        "operational_readiness_kr.csv",
        "v92_macro_analysis_kr.csv",
        "v92_flow_clean_kr.csv",
        "v92_company_integrated_kr.csv",
    ],
    "dashboard_related_us": [
        "v92_data_status_us.csv",
        "operational_readiness_us.csv",
        "v92_macro_analysis_us.csv",
        "v92_flow_clean_us.csv",
        "v92_company_integrated_us.csv",
    ],
}


def count_csv_rows(path: Path):
    """CSV row count helper. pandas가 있으면 pandas를 쓰고, 실패하면 csv 모듈로 fallback합니다."""
    if not path.exists():
        return {
            "exists": False,
            "bytes": 0,
            "rows": 0,
            "read_status": "MISSING",
            "error": "",
        }

    size = path.stat().st_size

    if pd is not None:
        for enc in ["utf-8-sig", "utf-8", "cp949"]:
            try:
                df = pd.read_csv(path, encoding=enc)
                return {
                    "exists": True,
                    "bytes": size,
                    "rows": len(df),
                    "read_status": "OK",
                    "error": "",
                }
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
    else:
        last_error = "pandas not available"

    # pandas 실패 시 간단한 csv row count fallback
    for enc in ["utf-8-sig", "utf-8", "cp949"]:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            data_rows = max(len(rows) - 1, 0)
            return {
                "exists": True,
                "bytes": size,
                "rows": data_rows,
                "read_status": "OK_CSV_FALLBACK",
                "error": "",
            }
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

    return {
        "exists": True,
        "bytes": size,
        "rows": 0,
        "read_status": "READ_ERROR",
        "error": last_error,
    }


def print_file_line(name: str, category: str):
    info = count_csv_rows(REPORT_DIR / name)

    if info["exists"] and info["read_status"].startswith("OK"):
        print(f"[OK] {category:<18} {name:<45} {info['rows']} rows {info['bytes']} bytes")
    elif info["exists"]:
        print(f"[READ_ERROR] {category:<10} {name:<45} {info['error']}")
    else:
        print(f"[MISSING] {category:<14} {name}")


def existing_files(names):
    return [name for name in names if (REPORT_DIR / name).exists()]


def main():
    print("=== v92 core required files ===")
    for name in CORE_REQUIRED:
        print_file_line(name, "CORE_REQUIRED")

    print("\n=== app.py expected exact files ===")
    for name in APP_EXPECTED:
        print_file_line(name, "APP_EXPECTED")

    print("\n=== available alternative v92 report groups ===")
    alt_summary = {}
    for group_name, names in ALTERNATIVE_GROUPS.items():
        found = existing_files(names)
        alt_summary[group_name] = found

        print(f"\n[{group_name}]")
        if not found:
            print("  MISSING_GROUP")
        else:
            for name in found:
                print_file_line(name, "ALT_FOUND")

    print("\n=== status json ===")
    status_path = REPORT_DIR / "v92_status.json"
    status_json_summary = {}

    if status_path.exists():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            status_json_summary = {
                k: data.get(k)
                for k in ["status", "version", "updated_at", "base_status", "copied_files", "checks"]
            }
            print(json.dumps(status_json_summary, ensure_ascii=False, indent=2))
        except Exception as e:
            print("v92_status.json READ_ERROR", type(e).__name__, e)
    else:
        print("v92_status.json not found")

    missing_core = [name for name in CORE_REQUIRED if not (REPORT_DIR / name).exists()]
    missing_app_exact = [name for name in APP_EXPECTED if not (REPORT_DIR / name).exists()]

    alt_ok = all(len(v) > 0 for v in alt_summary.values())

    if missing_core:
        overall_status = "FAIL_CORE_REQUIRED_MISSING"
    elif not missing_app_exact:
        overall_status = "OK_ALL_APP_EXPECTED_FILES_EXIST"
    elif alt_ok:
        overall_status = "OK_CORE_WITH_APP_EXPECTED_WARNING"
    else:
        overall_status = "WARN_APP_EXPECTED_AND_ALTERNATIVES_MISSING"

    diagnostic = {
        "overall_status": overall_status,
        "core_required_ok": len(missing_core) == 0,
        "app_expected_exact_ok": len(missing_app_exact) == 0,
        "alternative_groups_ok": alt_ok,
        "missing_core": missing_core,
        "missing_app_expected_exact": missing_app_exact,
        "alternative_groups_found": alt_summary,
        "status_json_summary": status_json_summary,
    }

    print("\n=== diagnostic summary ===")
    print(json.dumps(diagnostic, ensure_ascii=False, indent=2))

    out_path = REPORT_DIR / "v92_check_diagnostic.json"
    try:
        out_path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[OK] diagnostic saved: {out_path}")
    except Exception as e:
        print(f"\n[WARN] diagnostic save failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
