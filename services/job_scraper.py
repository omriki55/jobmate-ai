"""
Job Scraper Service — Phase 2
Fetches live job listings from free public APIs and upserts them into the DB.

Sources (no API key required):
  • Remotive   — https://remotive.com/api/remote-jobs
  • Arbeitnow  — https://arbeitnow.com/api/job-board-api

Plug-in stubs (add API keys later):
  • JSearch  (RapidAPI)  — LinkedIn / Indeed / Glassdoor
  • Adzuna               — 250 free calls/day
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.database import AsyncSessionLocal
from db.models import Job

logger = logging.getLogger(__name__)

REMOTIVE_URL  = "https://remotive.com/api/remote-jobs"
ARBEITNOW_URL = "https://arbeitnow.com/api/job-board-api"
HTTP_TIMEOUT  = 15  # seconds

# ---------------------------------------------------------------------------
# Salary parsing
# ---------------------------------------------------------------------------

def _parse_salary(raw: str | None) -> tuple[Optional[int], Optional[int], str]:
    """Parse '€60,000 – €80,000' → (60000, 80000, 'EUR')."""
    if not raw:
        return None, None, "USD"
    cur = "USD"
    if "€" in raw or "EUR" in raw.upper():
        cur = "EUR"
    elif "£" in raw or "GBP" in raw.upper():
        cur = "GBP"
    elif "CA$" in raw or "CAD" in raw.upper():
        cur = "CAD"
    nums = re.findall(r"[\d]{2,}", raw.replace(",", "").replace(".", ""))
    # Multiply k-values
    parts = re.findall(r"([\d]+\.?[\d]*)\s*[kK]", raw)
    if parts:
        nums = [str(int(float(p) * 1000)) for p in parts]
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1]), cur
    if len(nums) == 1:
        v = int(nums[0])
        return v, None, cur
    return None, None, cur


def _detect_industry(tags: list[str], title: str) -> str:
    text = " ".join(tags + [title]).lower()
    if any(k in text for k in ("python", "javascript", "react", "engineer", "developer",
                                "backend", "frontend", "fullstack", "devops", "cloud",
                                "ios", "android", "data", "ml", "ai", "machine learning")):
        return "tech"
    if any(k in text for k in ("marketing", "seo", "content", "growth", "brand")):
        return "marketing"
    if any(k in text for k in ("sales", "account executive", "business development", "crm")):
        return "sales"
    if any(k in text for k in ("finance", "accounting", "fintech", "payments", "banking")):
        return "fintech"
    if any(k in text for k in ("design", "figma", "ux", "ui", "product designer")):
        return "tech"
    if any(k in text for k in ("customer success", "customer support", "customer experience")):
        return "saas"
    return "tech"


def _detect_size(description: str) -> str:
    desc = description.lower()
    if any(k in desc for k in ("series a", "seed", "early stage", "startup", "small team")):
        return "startup"
    if any(k in desc for k in ("series b", "series c", "scale", "mid-size")):
        return "smb"
    if any(k in desc for k in ("enterprise", "fortune", "10,000", "global team")):
        return "enterprise"
    return "startup"


def _stable_id(source: str, external_id: str) -> str:
    return hashlib.md5(f"{source}:{external_id}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Remotive
# ---------------------------------------------------------------------------

REMOTIVE_CATEGORIES = [
    "software-dev", "devops-sysadmin", "product", "design",
    "marketing", "customer-support", "sales", "data",
]

REMOTIVE_EMP_MAP = {
    "full_time": "full-time", "part_time": "part-time",
    "contract": "contract", "freelance": "contract",
    "internship": "part-time",
}


async def _fetch_remotive(client: httpx.AsyncClient) -> list[dict]:
    jobs: list[dict] = []
    for cat in REMOTIVE_CATEGORIES:
        try:
            r = await client.get(REMOTIVE_URL, params={"category": cat, "limit": 50},
                                  timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            raw_jobs = r.json().get("jobs", [])
            for j in raw_jobs:
                sal_min, sal_max, cur = _parse_salary(j.get("salary", ""))
                tags = [t.lower() for t in (j.get("tags") or [])]
                title = j.get("title", "")
                jobs.append({
                    "external_id": str(j.get("id", "")),
                    "source":      "remotive",
                    "title":       title,
                    "company":     j.get("company_name", "Unknown"),
                    "location":    j.get("candidate_required_location") or "Remote",
                    "remote":      True,
                    "salary_min":  sal_min,
                    "salary_max":  sal_max,
                    "salary_currency": cur,
                    "description": (j.get("description") or "")[:1000],
                    "requirements": tags[:15],
                    "employment_type": REMOTIVE_EMP_MAP.get(j.get("job_type", ""), "full-time"),
                    "industry":    _detect_industry(tags, title),
                    "company_size": _detect_size(j.get("description", "")),
                    "url":         j.get("url", ""),
                    "posted_at":   _parse_dt(j.get("publication_date")),
                })
        except Exception as exc:
            logger.warning("Remotive [%s] failed: %s", cat, exc)
    return jobs


# ---------------------------------------------------------------------------
# Arbeitnow
# ---------------------------------------------------------------------------

async def _fetch_arbeitnow(client: httpx.AsyncClient) -> list[dict]:
    jobs: list[dict] = []
    try:
        r = await client.get(ARBEITNOW_URL, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("data", []):
            # Guard: tags may be list[str] or list[int] depending on API version
            raw_tags = j.get("tags") or []
            tags = [str(t).lower() for t in raw_tags if t is not None]
            title = j.get("title", "")
            # Guard: job_types may be a list, a string, or a non-iterable int
            raw_emp = j.get("job_types")
            if isinstance(raw_emp, list) and raw_emp:
                emp_type = str(raw_emp[0])
            elif isinstance(raw_emp, str) and raw_emp:
                emp_type = raw_emp
            else:
                emp_type = "full-time"
            desc = j.get("description") or ""
            jobs.append({
                "external_id": j.get("slug", _stable_id("arbeitnow", title)),
                "source":      "arbeitnow",
                "title":       title,
                "company":     j.get("company_name", "Unknown"),
                "location":    j.get("location") or "Remote",
                "remote":      bool(j.get("remote", False)),
                "salary_min":  None,
                "salary_max":  None,
                "salary_currency": "USD",
                "description": (desc if isinstance(desc, str) else "")[:1000],
                "requirements": tags[:15],
                "employment_type": emp_type,
                "industry":    _detect_industry(tags, title),
                "company_size": _detect_size(desc if isinstance(desc, str) else ""),
                "url":         j.get("url", ""),
                "posted_at":   _parse_dt(j.get("created_at")),
            })
    except Exception as exc:
        logger.warning("Arbeitnow fetch failed: %s", exc)
    return jobs


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_dt(raw) -> datetime:
    """Parse ISO string or Unix timestamp → datetime. Handles int/float/str."""
    if not raw:
        return datetime.utcnow()
    # Unix timestamp (int or float)
    if isinstance(raw, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(raw))
        except (ValueError, OSError, OverflowError):
            return datetime.utcnow()
    raw = str(raw)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

async def _upsert_jobs(job_dicts: list[dict]) -> tuple[int, int]:
    """Insert new jobs; skip duplicates. Returns (inserted, skipped)."""
    inserted = skipped = 0
    async with AsyncSessionLocal() as db:
        for j in job_dicts:
            existing = await db.execute(
                select(Job).where(
                    Job.external_id == j["external_id"],
                    Job.source == j["source"],
                )
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue
            db.add(Job(**{k: v for k, v in j.items()}))
            inserted += 1
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
    return inserted, skipped


# ---------------------------------------------------------------------------
# Prune stale jobs (> 30 days old)
# ---------------------------------------------------------------------------

async def _prune_old_jobs() -> int:
    cutoff = datetime.utcnow() - timedelta(days=30)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.posted_at < cutoff))
        old = result.scalars().all()
        for j in old:
            await db.delete(j)
        await db.commit()
        return len(old)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def scrape_and_store() -> dict:
    """
    Fetch live jobs from all sources, upsert into DB.
    Returns a summary dict.
    """
    logger.info("Job scraper starting…")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        remotive_jobs, arbeitnow_jobs = await asyncio.gather(
            _fetch_remotive(client),
            _fetch_arbeitnow(client),
        )

    all_jobs = remotive_jobs + arbeitnow_jobs
    logger.info("Fetched %d jobs (Remotive=%d, Arbeitnow=%d)",
                len(all_jobs), len(remotive_jobs), len(arbeitnow_jobs))

    ins, skp = await _upsert_jobs(all_jobs)
    pruned   = await _prune_old_jobs()

    summary = {
        "fetched":  len(all_jobs),
        "inserted": ins,
        "skipped":  skp,
        "pruned":   pruned,
        "sources":  {"remotive": len(remotive_jobs), "arbeitnow": len(arbeitnow_jobs)},
    }
    logger.info("Scrape complete: %s", summary)
    return summary


async def get_total_job_count() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job))
        return len(result.scalars().all())
