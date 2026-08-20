import importlib.util
import pathlib
import sys


MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "configure_cron_job_org.py"
SPEC = importlib.util.spec_from_file_location("configure_cron_job_org", MODULE_PATH)
assert SPEC and SPEC.loader
cron = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cron
SPEC.loader.exec_module(cron)


class FakeClient:
    def __init__(self, jobs=None):
        self.jobs = list(jobs or [])
        self.created = []
        self.updated = []

    def list_jobs(self):
        return self.jobs

    def create_job(self, payload):
        self.created.append(payload)
        return 1000 + len(self.created)

    def update_job(self, job_id, payload):
        self.updated.append((job_id, payload))


def test_all_jobs_have_exact_independent_kst_schedules():
    jobs = cron.select_jobs("all")
    assert len(jobs) == 9
    assert len({job.title for job in jobs}) == 9
    for job in jobs:
        payload = cron.build_payload(job, "github-secret")
        schedule = payload["schedule"]
        assert schedule["timezone"] == "Asia/Seoul"
        assert schedule["hours"] == [job.hour]
        assert schedule["minutes"] == [job.minute]
        assert all(0 <= day <= 6 for day in schedule["wdays"])
        assert payload["requestMethod"] == 1


def test_upsert_creates_missing_and_updates_exact_title(capsys):
    existing = {"title": cron.JOURNAL_JOBS[0].title, "jobId": 42}
    client = FakeClient([existing, {"title": "Unrelated", "jobId": 7}])
    sleeps = []

    created, updated = cron.upsert_jobs(
        client,
        cron.JOURNAL_JOBS[:3],
        "do-not-print-this-token",
        sleep=sleeps.append,
    )

    assert (created, updated) == (2, 1)
    assert [item[0] for item in client.updated] == [42]
    assert len(client.created) == 2
    assert sleeps == [cron.CREATE_INTERVAL_SECONDS]
    assert "do-not-print-this-token" not in capsys.readouterr().out


def test_dry_run_does_not_mutate_or_sleep():
    client = FakeClient()
    sleeps = []
    created, updated = cron.upsert_jobs(
        client,
        cron.PAPER_JOBS,
        "secret",
        dry_run=True,
        sleep=sleeps.append,
    )
    assert (created, updated) == (3, 0)
    assert client.created == []
    assert client.updated == []
    assert sleeps == []


def test_duplicate_managed_title_fails_closed():
    title = cron.PAPER_JOBS[0].title
    client = FakeClient([{"title": title, "jobId": 1}, {"title": title, "jobId": 2}])
    try:
        cron.upsert_jobs(client, cron.PAPER_JOBS[:1], "secret")
    except cron.CronJobOrgError as exc:
        assert "duplicate existing jobs" in str(exc)
    else:
        raise AssertionError("duplicate title should fail closed")


def test_main_requires_both_secrets(monkeypatch, capsys):
    monkeypatch.delenv("CRON_JOB_ORG_API_KEY", raising=False)
    monkeypatch.delenv("MONE_CRON_GITHUB_TOKEN", raising=False)
    assert cron.main(["--dry-run"]) == 2
    error = capsys.readouterr().err
    assert "CRON_JOB_ORG_API_KEY" in error
    assert "MONE_CRON_GITHUB_TOKEN" in error
