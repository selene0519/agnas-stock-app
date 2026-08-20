#!/usr/bin/env python3
"""Idempotently configure cron-job.org backups for MONE GitHub workflows.

Secrets are accepted only through environment variables and are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable


API_BASE = "https://api.cron-job.org"
REPOSITORY = "selene0519/agnas-stock-app"
TIMEZONE = "Asia/Seoul"
CREATE_INTERVAL_SECONDS = 12.1  # PUT /jobs: max 5 requests per minute.


@dataclass(frozen=True)
class BackupJob:
    title: str
    workflow: str
    hour: int
    minute: int
    weekdays: tuple[int, ...]
    inputs: dict[str, str] | None = None


JOURNAL_JOBS = (
    BackupJob("MONE Backup - Journal 08:25 KST", "mone-vtj-capture.yml", 8, 25, (1, 2, 3, 4, 5)),
    BackupJob("MONE Backup - Journal 16:55 KST", "mone-vtj-capture.yml", 16, 55, (1, 2, 3, 4, 5)),
    BackupJob("MONE Backup - Journal 17:35 KST", "mone-vtj-capture.yml", 17, 35, (1, 2, 3, 4, 5)),
    BackupJob("MONE Backup - Journal 21:35 KST", "mone-vtj-capture.yml", 21, 35, (1, 2, 3, 4, 5)),
    BackupJob("MONE Backup - Journal 07:25 KST", "mone-vtj-capture.yml", 7, 25, (2, 3, 4, 5, 6)),
    BackupJob("MONE Backup - Journal 08:05 KST", "mone-vtj-capture.yml", 8, 5, (2, 3, 4, 5, 6)),
)

PAPER_JOBS = (
    BackupJob(
        "MONE Backup - Paper KR 08:35 KST",
        "mone-ai-paper-trader.yml",
        8,
        35,
        (1, 2, 3, 4, 5),
        {"market": "kr"},
    ),
    BackupJob(
        "MONE Backup - Paper US 22:05 KST",
        "mone-ai-paper-trader.yml",
        22,
        5,
        (1, 2, 3, 4, 5),
        {"market": "us"},
    ),
    BackupJob(
        "MONE Backup - Paper US 23:05 KST",
        "mone-ai-paper-trader.yml",
        23,
        5,
        (1, 2, 3, 4, 5),
        {"market": "us"},
    ),
)


class CronJobOrgError(RuntimeError):
    """A sanitized cron-job.org API error."""


class CronJobOrgClient:
    def __init__(self, api_key: str, opener: Callable[..., Any] = urllib.request.urlopen):
        self._api_key = api_key
        self._opener = opener

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{API_BASE}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "MONE-cron-configurator/1.0",
            },
        )
        try:
            with self._opener(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            # Do not include response bodies: an upstream could reflect request secrets.
            raise CronJobOrgError(f"cron-job.org API returned HTTP {exc.code} for {method} {path}") from exc
        except urllib.error.URLError as exc:
            raise CronJobOrgError(f"cron-job.org API connection failed for {method} {path}") from exc
        return json.loads(raw.decode("utf-8")) if raw else {}

    def list_jobs(self) -> list[dict[str, Any]]:
        result = self.request("GET", "/jobs")
        if result.get("someFailed"):
            raise CronJobOrgError("cron-job.org returned an incomplete job list; no changes were made")
        return list(result.get("jobs", []))

    def create_job(self, job: dict[str, Any]) -> int:
        result = self.request("PUT", "/jobs", {"job": job})
        return int(result["jobId"])

    def update_job(self, job_id: int, job: dict[str, Any]) -> None:
        self.request("PATCH", f"/jobs/{job_id}", {"job": job})


def select_jobs(scope: str) -> tuple[BackupJob, ...]:
    if scope == "journal":
        return JOURNAL_JOBS
    if scope == "paper":
        return PAPER_JOBS
    return JOURNAL_JOBS + PAPER_JOBS


def build_payload(spec: BackupJob, github_token: str) -> dict[str, Any]:
    dispatch: dict[str, Any] = {"ref": "main"}
    if spec.inputs:
        dispatch["inputs"] = spec.inputs
    return {
        "enabled": True,
        "title": spec.title,
        "saveResponses": False,
        "url": f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/{spec.workflow}/dispatches",
        "requestTimeout": 60,
        "redirectSuccess": False,
        "schedule": {
            "timezone": TIMEZONE,
            "expiresAt": 0,
            "hours": [spec.hour],
            "mdays": [-1],
            "minutes": [spec.minute],
            "months": [-1],
            "wdays": list(spec.weekdays),
        },
        "requestMethod": 1,
        "notification": {
            "onFailure": True,
            "onFailureCount": 1,
            "onSuccess": True,
            "onDisable": True,
            "onSslCertExpiry": True,
            "onSslCertExpirySeconds": 604800,
        },
        "extendedData": {
            "headers": {
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "MONE-cron-backup/1.0",
            },
            "body": json.dumps(dispatch, separators=(",", ":")),
        },
    }


def upsert_jobs(
    client: CronJobOrgClient,
    specs: Iterable[BackupJob],
    github_token: str,
    *,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, int]:
    current = client.list_jobs()
    by_title: dict[str, list[dict[str, Any]]] = {}
    for job in current:
        by_title.setdefault(str(job.get("title", "")), []).append(job)

    created = 0
    updated = 0
    for spec in specs:
        matches = by_title.get(spec.title, [])
        if len(matches) > 1:
            raise CronJobOrgError(f"duplicate existing jobs named {spec.title!r}; resolve them in the console first")
        payload = build_payload(spec, github_token)
        if matches:
            job_id = int(matches[0]["jobId"])
            if not dry_run:
                client.update_job(job_id, payload)
            print(f"{'WOULD UPDATE' if dry_run else 'UPDATED'}: {spec.title} (id={job_id})")
            updated += 1
        else:
            if not dry_run:
                if created:
                    sleep(CREATE_INTERVAL_SECONDS)
                job_id = client.create_job(payload)
                suffix = f" (id={job_id})"
            else:
                suffix = ""
            print(f"{'WOULD CREATE' if dry_run else 'CREATED'}: {spec.title}{suffix}")
            created += 1
    return created, updated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("all", "journal", "paper"), default="all")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cron_key = os.environ.get("CRON_JOB_ORG_API_KEY", "").strip()
    github_token = os.environ.get("MONE_CRON_GITHUB_TOKEN", "").strip()
    missing = [
        name
        for name, value in (
            ("CRON_JOB_ORG_API_KEY", cron_key),
            ("MONE_CRON_GITHUB_TOKEN", github_token),
        )
        if not value
    ]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    try:
        created, updated = upsert_jobs(
            CronJobOrgClient(cron_key),
            select_jobs(args.only),
            github_token,
            dry_run=args.dry_run,
        )
    except CronJobOrgError as exc:
        print(f"Configuration failed: {exc}", file=sys.stderr)
        return 1
    print(f"Done: {created} create target(s), {updated} update target(s). Secrets were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
