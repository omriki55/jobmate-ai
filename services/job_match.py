"""
Job matching engine — Phase 2.

Scoring breakdown:
  - Skill overlap      40 pts
  - Location match     20 pts
  - Salary match       20 pts
  - Industry match     10 pts
  - Company size match 10 pts

get_top_matches()       → uses SAMPLE_JOBS (offline / testing)
get_top_matches_live()  → queries DB (real scraped jobs, falls back to samples)
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sample job catalogue (replace with DB query + scraper in Phase 2)
# ---------------------------------------------------------------------------

SAMPLE_JOBS: list[dict[str, Any]] = [
    {
        "id": 1,
        "title": "Senior Product Manager",
        "company": "Notion",
        "location": "Remote",
        "salary_min": 130_000,
        "salary_max": 180_000,
        "salary_currency": "USD",
        "remote": True,
        "employment_type": "full-time",
        "industry": "tech",
        "company_size": "startup",
        "requirements": [
            "product management", "roadmap", "agile", "data analysis",
            "stakeholder management", "user research", "okrs",
        ],
        "description": "Lead product strategy for the core editor experience.",
        "url": "https://notion.so/careers",
        "source": "sample",
    },
    {
        "id": 2,
        "title": "Backend Software Engineer",
        "company": "Stripe",
        "location": "San Francisco, CA",
        "salary_min": 160_000,
        "salary_max": 220_000,
        "salary_currency": "USD",
        "remote": False,
        "employment_type": "full-time",
        "industry": "fintech",
        "company_size": "enterprise",
        "requirements": [
            "python", "java", "distributed systems", "api design",
            "postgresql", "redis", "microservices",
        ],
        "description": "Build and scale payment infrastructure handling millions of transactions daily.",
        "url": "https://stripe.com/jobs",
        "source": "sample",
    },
    {
        "id": 3,
        "title": "Customer Success Manager",
        "company": "HubSpot",
        "location": "Remote",
        "salary_min": 70_000,
        "salary_max": 95_000,
        "salary_currency": "USD",
        "remote": True,
        "employment_type": "full-time",
        "industry": "saas",
        "company_size": "enterprise",
        "requirements": [
            "customer success", "saas", "crm", "onboarding",
            "retention", "stakeholder management", "upsell",
        ],
        "description": "Own a portfolio of 50+ accounts, drive adoption and expansion.",
        "url": "https://hubspot.com/jobs",
        "source": "sample",
    },
    {
        "id": 4,
        "title": "UX Designer",
        "company": "Figma",
        "location": "London, UK",
        "salary_min": 80_000,
        "salary_max": 110_000,
        "salary_currency": "GBP",
        "remote": False,
        "employment_type": "full-time",
        "industry": "tech",
        "company_size": "startup",
        "requirements": [
            "figma", "user research", "prototyping", "design systems",
            "usability testing", "interaction design",
        ],
        "description": "Design intuitive interfaces for a collaborative design platform.",
        "url": "https://figma.com/jobs",
        "source": "sample",
    },
    {
        "id": 5,
        "title": "Data Scientist",
        "company": "Spotify",
        "location": "Remote",
        "salary_min": 120_000,
        "salary_max": 160_000,
        "salary_currency": "USD",
        "remote": True,
        "employment_type": "full-time",
        "industry": "tech",
        "company_size": "enterprise",
        "requirements": [
            "python", "machine learning", "sql", "statistics",
            "a/b testing", "spark", "scikit-learn",
        ],
        "description": "Drive personalization algorithms powering 600M+ listeners.",
        "url": "https://spotify.com/jobs",
        "source": "sample",
    },
    {
        "id": 6,
        "title": "Growth Marketing Manager",
        "company": "Canva",
        "location": "Remote",
        "salary_min": 90_000,
        "salary_max": 120_000,
        "salary_currency": "USD",
        "remote": True,
        "employment_type": "full-time",
        "industry": "tech",
        "company_size": "startup",
        "requirements": [
            "digital marketing", "content strategy", "seo",
            "analytics", "growth", "brand", "paid acquisition",
        ],
        "description": "Own growth marketing for the SMB segment across EMEA.",
        "url": "https://canva.com/jobs",
        "source": "sample",
    },
    {
        "id": 7,
        "title": "Frontend Engineer",
        "company": "Linear",
        "location": "Remote",
        "salary_min": 140_000,
        "salary_max": 190_000,
        "salary_currency": "USD",
        "remote": True,
        "employment_type": "full-time",
        "industry": "tech",
        "company_size": "startup",
        "requirements": [
            "react", "typescript", "css", "performance optimisation",
            "testing", "design systems", "graphql",
        ],
        "description": "Build the fastest issue tracker in the industry on a small, high-output team.",
        "url": "https://linear.app/jobs",
        "source": "sample",
    },
    {
        "id": 8,
        "title": "Sales Development Representative",
        "company": "Salesforce",
        "location": "New York, NY",
        "salary_min": 55_000,
        "salary_max": 75_000,
        "salary_currency": "USD",
        "remote": False,
        "employment_type": "full-time",
        "industry": "saas",
        "company_size": "enterprise",
        "requirements": [
            "sales", "crm", "outbound", "cold calling",
            "lead generation", "salesforce", "pipeline management",
        ],
        "description": "Drive pipeline generation for the enterprise sales team.",
        "url": "https://salesforce.com/jobs",
        "source": "sample",
    },
    {
        "id": 9,
        "title": "Platform / DevOps Engineer",
        "company": "GitLab",
        "location": "Remote",
        "salary_min": 130_000,
        "salary_max": 175_000,
        "salary_currency": "USD",
        "remote": True,
        "employment_type": "full-time",
        "industry": "tech",
        "company_size": "enterprise",
        "requirements": [
            "kubernetes", "terraform", "aws", "ci/cd",
            "docker", "python", "go", "observability",
        ],
        "description": "Build and maintain the infrastructure powering GitLab.com.",
        "url": "https://gitlab.com/jobs",
        "source": "sample",
    },
    {
        "id": 10,
        "title": "Product Designer",
        "company": "Loom",
        "location": "Remote",
        "salary_min": 100_000,
        "salary_max": 140_000,
        "salary_currency": "USD",
        "remote": True,
        "employment_type": "full-time",
        "industry": "tech",
        "company_size": "startup",
        "requirements": [
            "product design", "figma", "user research",
            "interaction design", "visual design", "prototyping",
        ],
        "description": "Shape the future of async video communication.",
        "url": "https://loom.com/jobs",
        "source": "sample",
    },
]


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

def _skill_score(job_requirements: list[str], cv_skills: list[str]) -> tuple[int, list[str]]:
    """Return (score 0-40, list of matching skills)."""
    if not job_requirements:
        return 20, []
    cv_lower = [s.lower() for s in cv_skills]
    matches = [
        req for req in job_requirements
        if any(req in cv_s or cv_s in req for cv_s in cv_lower)
    ]
    ratio = len(matches) / len(job_requirements)
    return int(ratio * 40), matches


def _location_score(job: dict, pref_locations: list[str]) -> int:
    if not pref_locations or "any" in pref_locations:
        return 20
    if "remote" in pref_locations and job.get("remote"):
        return 20
    if any(loc in job["location"].lower() for loc in pref_locations):
        return 20
    if job.get("remote"):
        return 10   # remote is always a partial match
    return 0


def _salary_score(job: dict, min_salary: Optional[int]) -> int:
    if not min_salary or not job.get("salary_max"):
        return 10   # no data → neutral
    if job["salary_max"] >= min_salary:
        return 20
    if job["salary_max"] >= min_salary * 0.85:
        return 10
    return 0


def _industry_score(job: dict, pref_industries: list[str]) -> int:
    if not pref_industries or "any" in pref_industries:
        return 10
    return 10 if job.get("industry", "").lower() in pref_industries else 0


def _size_score(job: dict, pref_sizes: list[str]) -> int:
    if not pref_sizes or "any" in pref_sizes:
        return 10
    return 10 if job.get("company_size", "").lower() in pref_sizes else 0


def score_job(job: dict, cv_skills: list[str], preferences: dict) -> tuple[int, str]:
    """Return (match_score 0-100, human-readable reason)."""
    skill_pts, matched_skills = _skill_score(job.get("requirements", []), cv_skills)
    loc_pts   = _location_score(job, preferences.get("locations", []))
    sal_pts   = _salary_score(job, preferences.get("min_salary"))
    ind_pts   = _industry_score(job, preferences.get("industries", []))
    size_pts  = _size_score(job, preferences.get("company_sizes", []))

    total = min(skill_pts + loc_pts + sal_pts + ind_pts + size_pts, 100)

    # Build a concise reason string
    parts: list[str] = []
    if matched_skills:
        parts.append(f"Skills: {', '.join(matched_skills[:3])}")
    if job.get("remote") and "remote" in preferences.get("locations", []):
        parts.append("Remote ✓")
    if job.get("salary_max") and preferences.get("min_salary"):
        parts.append(
            f"{job['salary_currency']} {job['salary_min']:,}–{job['salary_max']:,}"
        )
    reason = " · ".join(parts) if parts else "General match"
    return total, reason


def get_top_matches(
    cv_skills: list,
    preferences: dict,
    limit: int = 5,
    threshold: int = 50,
) -> list:
    """Score SAMPLE_JOBS — used for offline testing / Telegram bot fallback."""
    scored = []
    for job in SAMPLE_JOBS:
        score, reason = score_job(job, cv_skills, preferences)
        if score >= threshold:
            scored.append({**job, "match_score": score, "match_reason": reason})
    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:limit]


def _job_to_dict(job) -> dict:
    """Convert a SQLAlchemy Job ORM object to the dict format score_job() expects."""
    return {
        "id":               job.id,
        "title":            job.title,
        "company":          job.company,
        "location":         job.location,
        "remote":           job.remote,
        "salary_min":       job.salary_min,
        "salary_max":       job.salary_max,
        "salary_currency":  job.salary_currency or "USD",
        "requirements":     job.requirements or [],
        "industry":         job.industry or "",
        "company_size":     job.company_size or "",
        "employment_type":  job.employment_type or "full-time",
        "description":      job.description or "",
        "url":              job.url or "",
        "source":           job.source or "",
        "posted_at":        job.posted_at.isoformat() if job.posted_at else "",
    }


async def get_top_matches_live(
    cv_skills: list,
    preferences: dict,
    limit: int = 6,
    threshold: int = 30,
) -> list:
    """
    Query DB for recent jobs, score them, return best matches.
    Falls back to SAMPLE_JOBS if DB is empty.
    """
    from db.database import AsyncSessionLocal
    from db.models import Job
    from sqlalchemy import select

    cutoff = datetime.utcnow() - timedelta(days=30)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Job)
            .where(Job.posted_at >= cutoff)
            .order_by(Job.posted_at.desc())
            .limit(500)
        )
        db_jobs = result.scalars().all()

    if not db_jobs:
        logger.info("DB empty — falling back to sample jobs")
        return get_top_matches(cv_skills, preferences, limit=limit, threshold=threshold)

    logger.info("Scoring %d DB jobs for user", len(db_jobs))
    scored = []
    for job in db_jobs:
        job_dict = _job_to_dict(job)
        score, reason = score_job(job_dict, cv_skills, preferences)
        if score >= threshold:
            scored.append({**job_dict, "match_score": score, "match_reason": reason})

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:limit]
