#!/usr/bin/env python3
"""
Catalyst history archiver (KR) — 재료(수급·공시) 이력 누적.

앱은 수급(kr_supply_flow.csv)·공시(disclosures_kr.csv)를 '오늘치 스냅샷'으로만 갖고 있어
"기관 매수가 저점 반등을 예측하나?" 같은 걸 백테스트할 과거 데이터가 없다. 이 스크립트를
매일 돌려 스냅샷을 날짜별 이력으로 append(중복 제거)하면, 몇 달 뒤 재료→수익 백테스트가
가능해진다. (렌즈 라이브 저널과 같은 '지금 쌓고 나중에 증명' 원리)

읽기: data/kr_supply_flow.csv, data/disclosures/disclosures_kr.csv
쓰기(append·dedup): reports/kr_supply_flow_history.csv, reports/disclosures_kr_history.csv
(data/history는 gitignore라 커밋되는 reports/에 저장)
"""
from __future__ import annotations
import csv
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def archive(src_path: str, hist_path: str, key_fields: list[str]) -> tuple[int, int]:
    if not os.path.exists(src_path):
        return (0, 0)
    src_rows = list(csv.DictReader(open(src_path, encoding="utf-8-sig")))
    if not src_rows:
        return (0, 0)
    fields = list(src_rows[0].keys())

    existing_keys = set()
    hist_fields = fields
    if os.path.exists(hist_path):
        for r in csv.DictReader(open(hist_path, encoding="utf-8-sig")):
            existing_keys.add(tuple(r.get(k, "") for k in key_fields))
        # 기존 헤더 유지
        with open(hist_path, encoding="utf-8-sig") as fh:
            hist_fields = next(csv.reader(fh))

    new_rows = [r for r in src_rows
                if tuple(str(r.get(k, "")) for k in key_fields) not in existing_keys]

    is_new = not os.path.exists(hist_path)
    os.makedirs(os.path.dirname(hist_path), exist_ok=True)
    with open(hist_path, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=hist_fields, extrasaction="ignore")
        if is_new:
            w.writeheader()
        for r in new_rows:
            w.writerow(r)
    return (len(new_rows), len(existing_keys))


def main() -> int:
    supply_new, supply_prev = archive(
        os.path.join(REPO, "data", "kr_supply_flow.csv"),
        os.path.join(REPO, "reports", "kr_supply_flow_history.csv"),
        key_fields=["symbol", "asOf"],
    )
    print(f"supply history: +{supply_new} (기존 {supply_prev}) -> reports/kr_supply_flow_history.csv")

    disc_new, disc_prev = archive(
        os.path.join(REPO, "data", "disclosures", "disclosures_kr.csv"),
        os.path.join(REPO, "reports", "disclosures_kr_history.csv"),
        key_fields=["symbol", "date", "rcept_no"],
    )
    print(f"disclosure history: +{disc_new} (기존 {disc_prev}) -> reports/disclosures_kr_history.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
