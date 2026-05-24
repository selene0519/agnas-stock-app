from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

REPORT_DIR = Path("reports")


def _copy_aliases() -> dict:
    REPORT_DIR.mkdir(exist_ok=True)
    copied = []
    missing = []
    aliases = [
        ("v75_today_summary_{slug}.csv", "v76_today_summary_{slug}.csv"),
        ("v75_action_clean_{slug}.csv", "v76_action_clean_{slug}.csv"),
        ("v75_pullback_clean_{slug}.csv", "v76_pullback_clean_{slug}.csv"),
        ("v75_flow_clean_{slug}.csv", "v76_flow_clean_{slug}.csv"),
        ("v75_company_clean_{slug}.csv", "v76_company_clean_{slug}.csv"),
        ("v75_risk_clean_{slug}.csv", "v76_risk_clean_{slug}.csv"),
        ("v75_news_cards_{slug}.csv", "v76_news_cards_{slug}.csv"),
        ("v75_position_cards_{slug}.csv", "v76_position_cards_{slug}.csv"),
        ("v75_market_guard_{slug}.csv", "v76_market_guard_{slug}.csv"),
        ("v75_sector_strength_{slug}.csv", "v76_sector_strength_{slug}.csv"),
        ("v75_quant_portfolio_risk_{slug}.csv", "v76_quant_portfolio_risk_{slug}.csv"),
        ("v75_quant_backtest_{slug}.csv", "v76_quant_backtest_{slug}.csv"),
        ("v75_quant_monte_carlo_{slug}.csv", "v76_quant_monte_carlo_{slug}.csv"),
        ("v75_quant_correlation_{slug}.csv", "v76_quant_correlation_{slug}.csv"),
        ("v75_quant_options_{slug}.csv", "v76_quant_options_{slug}.csv"),
    ]
    for slug in ("kr", "us"):
        for src_tpl, dst_tpl in aliases:
            src = REPORT_DIR / src_tpl.format(slug=slug)
            dst = REPORT_DIR / dst_tpl.format(slug=slug)
            if src.exists() and src.stat().st_size > 0:
                shutil.copy2(src, dst)
                copied.append(dst.name)
            else:
                missing.append(src.name)
    src_status = REPORT_DIR / "v75_data_status.csv"
    if src_status.exists() and src_status.stat().st_size > 0:
        shutil.copy2(src_status, REPORT_DIR / "v76_data_status.csv")
        copied.append("v76_data_status.csv")
    src_json = REPORT_DIR / "v75_status.json"
    if src_json.exists() and src_json.stat().st_size > 0:
        try:
            data = json.loads(src_json.read_text(encoding="utf-8"))
            data["version"] = "v76-hotfix-v75-engine"
            data["alias_created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            (REPORT_DIR / "v76_status.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            copied.append("v76_status.json")
        except Exception:
            shutil.copy2(src_json, REPORT_DIR / "v76_status.json")
            copied.append("v76_status.json")
    return {"copied": copied, "missing": missing[:30], "copied_count": len(copied)}


def main() -> dict:
    result = {
        "status": "ERROR",
        "version": "v76-hotfix",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        from core.v75_donhyun_quant_complete_engine import run_v75_update
        base = run_v75_update(fetch_news=True, fetch_fundamentals=True, fetch_macro=True)
        aliases = _copy_aliases()
        status = "OK" if aliases.get("copied_count", 0) > 0 else "WARN"
        result.update({"status": status, "base_engine": "v75", "base_result": base, "aliases": aliases})
    except Exception as exc:
        aliases = _copy_aliases()
        status = "WARN" if aliases.get("copied_count", 0) > 0 else "ERROR"
        result.update({"status": status, "error": f"{type(exc).__name__}: {exc}", "aliases": aliases})
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    out = main()
    raise SystemExit(0 if out.get("status") in {"OK", "WARN"} else 2)
