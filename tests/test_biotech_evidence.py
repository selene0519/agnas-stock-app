import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import biotech_evidence as bio


def _study(sponsor: str, status: str = "RECRUITING", completion: str = "2026-10-01") -> dict:
    return {
        "hasResults": True,
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Verified trial"},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor}},
            "statusModule": {
                "overallStatus": status,
                "completionDateStruct": {"date": completion},
            },
            "designModule": {"phases": ["PHASE3"]},
        },
    }


def test_clinical_evidence_rejects_fuzzy_unrelated_sponsors() -> None:
    payload = {"totalCount": 2, "studies": [_study("Acme Therapeutics Inc."), _study("Different University")]}

    result = bio._clinical_evidence("Acme Therapeutics", payload, as_of=date(2026, 8, 25))

    assert result["verifiedStudyCountInFetchedPage"] == 1
    assert result["rejectedIdentityCountInFetchedPage"] == 1
    assert result["activeStudyCountInFetchedPage"] == 1
    assert result["phase3StudyCountInFetchedPage"] == 1
    assert result["upcomingCompletion180dCountInFetchedPage"] == 1
    assert result["identityStatus"] == "VERIFIED"


def test_pubmed_requires_contact_email_instead_of_violating_eutilities_policy() -> None:
    called = []

    result = bio._pubmed_evidence("Acme", fetch_json=lambda url: called.append(url) or {}, email="")

    assert result["status"] == "MISSING_CONFIGURATION"
    assert result["publicationCountRecent5y"] is None
    assert called == []


def test_pubmed_persisted_source_url_never_contains_contact_or_api_key() -> None:
    secret_email = "private-contact@example.com"
    secret_key = "private-api-key"

    def fake_fetch(url: str) -> dict:
        assert secret_email in unquote(url)
        assert secret_key in url
        if "esearch.fcgi" in url:
            return {"esearchresult": {"count": "1", "idlist": ["123"]}}
        return {
            "result": {
                "123": {
                    "title": "Example",
                    "pubdate": "2026",
                    "fulljournalname": "Example Journal",
                }
            }
        }

    result = bio._pubmed_evidence(
        "AbbVie",
        fetch_json=fake_fetch,
        email=secret_email,
        api_key=secret_key,
    )

    serialized = json.dumps(result)
    assert secret_email not in serialized
    assert secret_key not in serialized
    assert result["sourceUrl"].startswith("https://pubmed.ncbi.nlm.nih.gov/")

def test_collect_isolates_source_failure_and_never_changes_score(monkeypatch) -> None:
    monkeypatch.delenv("NCBI_EMAIL", raising=False)
    candidates = [{"market": "us", "symbol": "ACME", "company": "Acme Therapeutics", "sector": "Biotech"}]

    result = bio.collect(
        candidates=candidates,
        fetch_json=lambda url: {"totalCount": 1, "studies": [_study("Acme Therapeutics")]},
        as_of=date(2026, 8, 25),
        save=False,
        sleep_fn=lambda _: None,
    )

    item = result["items"][0]
    assert item["clinicalTrials"]["verifiedStudyCountInFetchedPage"] == 1
    assert item["pubMed"]["status"] == "MISSING_CONFIGURATION"
    assert item["status"] == "PARTIAL"
    assert item["researchOnly"] is True
    assert item["promotionEligible"] is False
    assert item["scoreAdjustment"] == 0.0


def test_decorate_items_adds_metadata_without_mutating_scores(monkeypatch) -> None:
    monkeypatch.setattr(
        bio,
        "read_cache",
        lambda market="all", symbol="": {
            "items": [{"market": "us", "symbol": "ACME", "researchOnly": True}],
        },
    )
    original = [{"symbol": "ACME", "finalRankScore": 77.5, "expectedValue": 3.2}]

    decorated = bio.decorate_items(original, "us")

    assert decorated[0]["finalRankScore"] == 77.5
    assert decorated[0]["expectedValue"] == 3.2
    assert decorated[0]["biotechEvidenceScoreAdjustment"] == 0.0
    assert "biotechEvidence" not in original[0]
