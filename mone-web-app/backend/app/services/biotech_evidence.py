"""Official ClinicalTrials.gov and PubMed evidence for biotech research.

This module is deliberately research-only. Counts of trials or publications
are not investment returns, and fuzzy company-name matches are especially
dangerous. The collector therefore verifies the lead sponsor name, preserves
source URLs and timestamps, and never changes a recommendation score.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services import data_loader as data


REPORT_PATH = data.REPO_ROOT / "reports" / "biotech_evidence.json"
CLINICAL_BASE = "https://clinicaltrials.gov/api/v2/studies"
PUBMED_SEARCH_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
BIOTECH_HINTS = (
    "bio", "biotech", "pharma", "pharmaceutical", "therapeutic", "drug",
    "바이오", "제약", "의약",
)
ACTIVE_TRIAL_STATUSES = {"RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION"}
RISK_TRIAL_STATUSES = {"SUSPENDED", "TERMINATED", "WITHDRAWN"}
COMPANY_QUERY_ALIASES = {
    "us:ABBV": "AbbVie",
    "us:AMGN": "Amgen",
    "us:BMY": "Bristol-Myers Squibb",
    "us:GILD": "Gilead Sciences",
    "us:JNJ": "Johnson & Johnson",
    "us:LLY": "Eli Lilly and Company",
    "us:MRK": "Merck Sharp & Dohme",
    "us:NVO": "Novo Nordisk",
    "us:PFE": "Pfizer",
    "us:REGN": "Regeneron Pharmaceuticals",
    "us:VRTX": "Vertex Pharmaceuticals",
    "kr:000100": "Yuhan Corporation",
    "kr:068270": "Celltrion",
    "kr:086900": "Medytox",
    "kr:128940": "Hanmi Pharmaceutical",
    "kr:196170": "Alteogen",
    "kr:141080": "LigaChem Biosciences",
    "kr:298380": "ABL Bio",
    "kr:207940": "Samsung Biologics",
    "kr:214150": "Classys",
    "kr:326030": "SK Biopharmaceuticals",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_org(value: Any) -> str:
    text = re.sub(r"[^a-z0-9가-힣]+", " ", _text(value).lower())
    suffixes = {
        "inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "limited",
        "plc", "holdings", "holding", "group", "llc", "ag", "sa", "a", "s", "주식회사", "㈜",
    }
    return " ".join(token for token in text.split() if token not in suffixes)


def _identity_match(company: str, sponsor: str) -> str:
    left, right = _normalized_org(company), _normalized_org(sponsor)
    if not left or not right:
        return "NONE"
    if left == right:
        return "HIGH"
    if min(len(left), len(right)) >= 5 and (left in right or right in left):
        return "MEDIUM"
    return "NONE"


def _parse_iso_day(value: Any) -> date | None:
    raw = _text(value)[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _get_json(url: str, *, timeout: int = 20) -> dict[str, Any]:
    email = _text(os.getenv("NCBI_EMAIL"))
    user_agent = f"MONEQuantResearch/1.0 ({email})" if email else "MONEQuantResearch/1.0"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed official API hosts
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _clinical_url(company: str, page_size: int = 20) -> str:
    return CLINICAL_BASE + "?" + urlencode({
        "query.spons": company,
        "pageSize": max(1, min(page_size, 100)),
        "countTotal": "true",
        "format": "json",
    })


def _clinical_evidence(company: str, payload: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    matched: list[dict[str, Any]] = []
    ambiguous_sponsors: list[str] = []
    rejected = 0
    for study in payload.get("studies") or []:
        protocol = study.get("protocolSection") if isinstance(study, dict) else {}
        protocol = protocol if isinstance(protocol, dict) else {}
        sponsor_module = protocol.get("sponsorCollaboratorsModule") or {}
        sponsor = sponsor_module.get("leadSponsor") or {}
        sponsor_name = _text(sponsor.get("name")) if isinstance(sponsor, dict) else ""
        confidence = _identity_match(company, sponsor_name)
        if confidence != "HIGH":
            rejected += 1
            if confidence == "MEDIUM" and sponsor_name:
                ambiguous_sponsors.append(sponsor_name)
            continue
        identification = protocol.get("identificationModule") or {}
        status_module = protocol.get("statusModule") or {}
        design = protocol.get("designModule") or {}
        completion = (status_module.get("completionDateStruct") or {}).get("date")
        nct_id = _text(identification.get("nctId"))
        matched.append({
            "nctId": nct_id,
            "title": _text(identification.get("briefTitle") or identification.get("officialTitle")),
            "leadSponsor": sponsor_name,
            "identityConfidence": confidence,
            "overallStatus": _text(status_module.get("overallStatus")).upper(),
            "phases": list(design.get("phases") or []),
            "completionDate": _text(completion),
            "hasResults": bool(study.get("hasResults")),
            "sourceUrl": f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "",
        })

    upcoming_cutoff = as_of.toordinal() + 180
    active = [row for row in matched if row["overallStatus"] in ACTIVE_TRIAL_STATUSES]
    risky = [row for row in matched if row["overallStatus"] in RISK_TRIAL_STATUSES]
    phase3 = [row for row in matched if any(str(phase).upper() == "PHASE3" for phase in row["phases"])]
    upcoming = []
    for row in matched:
        completion_day = _parse_iso_day(row.get("completionDate"))
        if completion_day and as_of.toordinal() <= completion_day.toordinal() <= upcoming_cutoff:
            upcoming.append(row)
    return {
        "status": "OK",
        "queryCompany": company,
        "apiTotalCount": int(payload.get("totalCount") or 0),
        "fetchedStudyCount": len(payload.get("studies") or []),
        "verifiedStudyCountInFetchedPage": len(matched),
        "rejectedIdentityCountInFetchedPage": rejected,
        "ambiguousSponsorMatches": sorted(set(ambiguous_sponsors))[:10],
        "identityStatus": "VERIFIED" if matched else "NO_VERIFIED_SPONSOR_MATCH",
        "identityConfidence": "HIGH" if matched else "NONE",
        "activeStudyCountInFetchedPage": len(active),
        "phase3StudyCountInFetchedPage": len(phase3),
        "riskStatusStudyCountInFetchedPage": len(risky),
        "upcomingCompletion180dCountInFetchedPage": len(upcoming),
        "studies": matched[:10],
        "source": "ClinicalTrials.gov API v2",
        "sourceUrl": _clinical_url(company),
    }


def _pubmed_urls(company: str, email: str, api_key: str = "") -> tuple[str, Callable[[list[str]], str]]:
    params = {
        "db": "pubmed", "term": f'"{company}"[Affiliation]', "reldate": "1825",
        "datetype": "pdat", "retmax": "5", "sort": "pub_date", "retmode": "json",
        "tool": "MONEQuantResearch", "email": email,
    }
    if api_key:
        params["api_key"] = api_key

    def summary_url(ids: list[str]) -> str:
        summary = {
            "db": "pubmed", "id": ",".join(ids), "retmode": "json",
            "tool": "MONEQuantResearch", "email": email,
        }
        if api_key:
            summary["api_key"] = api_key
        return PUBMED_SUMMARY_BASE + "?" + urlencode(summary)

    return PUBMED_SEARCH_BASE + "?" + urlencode(params), summary_url


def _pubmed_public_url(company: str) -> str:
    """Return a shareable source URL without NCBI contact or API credentials."""
    return "https://pubmed.ncbi.nlm.nih.gov/?" + urlencode({"term": f'"{company}"[Affiliation]'})



def _pubmed_evidence(
    company: str,
    *,
    fetch_json: Callable[[str], dict[str, Any]],
    email: str,
    api_key: str = "",
    pause: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if not email:
        return {
            "status": "MISSING_CONFIGURATION",
            "reason": "NCBI_EMAIL_REQUIRED_BY_EUTILITIES_GUIDELINES",
            "publicationCountRecent5y": None,
            "mappingStatus": "NOT_QUERIED",
            "source": "NCBI PubMed E-utilities",
        }
    search_url, summary_url = _pubmed_urls(company, email, api_key)
    search = fetch_json(search_url)
    result = search.get("esearchresult") or {}
    ids = [str(value) for value in result.get("idlist") or []]
    publications: list[dict[str, Any]] = []
    if ids:
        if pause:
            pause()
        summary = fetch_json(summary_url(ids))
        summary_result = summary.get("result") or {}
        for pmid in ids:
            item = summary_result.get(pmid) or {}
            publications.append({
                "pmid": pmid,
                "title": _text(item.get("title")),
                "publicationDate": _text(item.get("pubdate")),
                "journal": _text(item.get("fulljournalname")),
                "sourceUrl": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            })
    return {
        "status": "OK",
        "queryCompany": company,
        "publicationCountRecent5y": int(result.get("count") or 0),
        "mappingStatus": "AFFILIATION_QUERY_MATCH_UNVERIFIED",
        "publications": publications,
        "source": "NCBI PubMed E-utilities",
        "sourceUrl": _pubmed_public_url(company),
    }


def _query_company(market: str, symbol: str, company: str) -> str:
    alias = COMPANY_QUERY_ALIASES.get(f"{market}:{symbol}")
    if alias:
        return alias
    if market == "us" and _normalized_org(company) == _normalized_org(symbol):
        return ""
    return company

def _is_biotech_row(row: dict[str, Any]) -> bool:
    haystack = " ".join(_text(row.get(key)).lower() for key in ("sector", "industry", "theme", "name", "companyName"))
    return any(token in haystack for token in BIOTECH_HINTS)


def _candidate_universe() -> list[dict[str, str]]:
    selected: dict[str, dict[str, str]] = {}
    for path in sorted((data.REPO_ROOT / "reports").glob("mone_v36_final_recommendations_*.csv")):
        match = re.search(r"recommendations_(kr|us)_", path.name)
        if not match:
            continue
        market = match.group(1)
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            continue
        for row in rows:
            if not _is_biotech_row(row):
                continue
            symbol = _text(row.get("symbol")).upper()
            company = _text(row.get("name") or row.get("companyName"))
            if not symbol or len(_normalized_org(company)) < 3:
                continue
            query_company = _query_company(market, symbol, company)
            if not query_company:
                continue
            selected.setdefault(f"{market}:{symbol}", {
                "market": market, "symbol": symbol, "company": company, "queryCompany": query_company,
                "sector": _text(row.get("sector") or row.get("industry") or row.get("theme")),
                "universeSource": "current_recommendation",
            })

    recommended = list(selected.values())
    master_rows: dict[str, list[dict[str, str]]] = {"kr": [], "us": []}
    for market in ("kr", "us"):
        path = data.REPO_ROOT / "data" / f"sector_map_{market}.csv"
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            continue
        for row in rows:
            if not _is_biotech_row(row):
                continue
            symbol = _text(row.get("symbol")).upper()
            company = _text(row.get("name") or row.get("companyName"))
            key = f"{market}:{symbol}"
            query_company = _query_company(market, symbol, company)
            if not symbol or len(_normalized_org(company)) < 3 or key in selected or not query_company:
                continue
            master_rows[market].append({
                "market": market, "symbol": symbol, "company": company, "queryCompany": query_company,
                "sector": _text(row.get("sector") or row.get("industry") or row.get("theme")),
                "universeSource": "sector_master",
            })
    supplement: list[dict[str, str]] = []
    depth = 0
    while any(depth < len(master_rows[market]) for market in ("kr", "us")):
        for market in ("kr", "us"):
            if depth < len(master_rows[market]):
                supplement.append(master_rows[market][depth])
        depth += 1
    return recommended + supplement


def collect(
    *,
    candidates: list[dict[str, str]] | None = None,
    fetch_json: Callable[[str], dict[str, Any]] = _get_json,
    as_of: date | None = None,
    save: bool = True,
    max_symbols: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    today = as_of or date.today()
    universe = list(candidates if candidates is not None else _candidate_universe())
    limit = max_symbols if max_symbols is not None else int(os.getenv("MONE_BIOTECH_MAX_SYMBOLS", "12"))
    universe = universe[: max(0, min(limit, 50))]
    email = _text(os.getenv("NCBI_EMAIL"))
    api_key = _text(os.getenv("NCBI_API_KEY"))
    records: list[dict[str, Any]] = []

    def pause() -> None:
        sleep_fn(0.36 if not api_key else 0.11)

    for candidate in universe:
        company = _text(candidate.get("queryCompany") or candidate.get("company"))
        record: dict[str, Any] = {
            **candidate, "asOfDate": today.isoformat(), "researchOnly": True,
            "scoreAdjustment": 0.0, "promotionEligible": False,
        }
        errors: list[str] = []
        try:
            clinical_payload = fetch_json(_clinical_url(company))
            record["clinicalTrials"] = _clinical_evidence(company, clinical_payload, as_of=today)
        except Exception as exc:  # noqa: BLE001 - external source isolation
            record["clinicalTrials"] = {"status": "ERROR", "error": type(exc).__name__}
            errors.append("CLINICALTRIALS_UNAVAILABLE")
        pause()
        try:
            record["pubMed"] = _pubmed_evidence(
                company, fetch_json=fetch_json, email=email, api_key=api_key, pause=pause,
            )
            if record["pubMed"].get("status") != "OK":
                errors.append("PUBMED_NOT_READY")
        except Exception as exc:  # noqa: BLE001 - external source isolation
            record["pubMed"] = {"status": "ERROR", "error": type(exc).__name__}
            errors.append("PUBMED_UNAVAILABLE")
        record["status"] = "PARTIAL" if errors else "OK"
        record["errors"] = errors
        records.append(record)
        pause()

    payload = {
        "status": "OK" if all(row.get("status") == "OK" for row in records) else "PARTIAL",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asOfDate": today.isoformat(), "count": len(records), "items": records,
        "policy": {
            "researchOnly": True, "scoreAdjustment": 0.0, "promotionEligible": False,
            "identityRule": "Clinical trial counts require verified lead-sponsor name matching; PubMed affiliation hits remain unverified.",
            "temporalRule": "Only data returned by official APIs at collection time is persisted; no future-event outcome is inferred.",
        },
        "sources": [
            {"name": "ClinicalTrials.gov API v2", "url": "https://clinicaltrials.gov/api/v2/studies"},
            {"name": "NCBI PubMed E-utilities", "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"},
        ],
    }
    if save:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = REPORT_PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(REPORT_PATH)
    return payload


def read_cache(market: str = "all", symbol: str = "") -> dict[str, Any]:
    try:
        payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "EMPTY", "count": 0, "items": [], "policy": {"researchOnly": True}}
    except (OSError, json.JSONDecodeError):
        return {"status": "ERROR", "count": 0, "items": [], "policy": {"researchOnly": True}}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    normalized_market = _text(market).lower()
    normalized_symbol = _text(symbol).upper()
    filtered = [
        row for row in items
        if (normalized_market == "all" or _text(row.get("market")).lower() == normalized_market)
        and (not normalized_symbol or _text(row.get("symbol")).upper() == normalized_symbol)
    ]
    return {**payload, "items": filtered, "count": len(filtered)}


def decorate_items(items: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    evidence = read_cache(market)
    index = {_text(row.get("symbol")).upper(): row for row in evidence.get("items") or []}
    decorated: list[dict[str, Any]] = []
    for original in items:
        row = dict(original)
        match = index.get(_text(row.get("symbol")).upper())
        if match:
            row["biotechEvidence"] = match
            row["biotechEvidenceResearchOnly"] = True
            row["biotechEvidenceScoreAdjustment"] = 0.0
        decorated.append(row)
    return decorated