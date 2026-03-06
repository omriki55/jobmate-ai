"""
Job Search Service — Keyword-based job search.

Searches the DB for jobs matching user-supplied keywords against
title, description, and requirements. Re-scores results using the
existing scoring engine.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from db.database import AsyncSessionLocal
from db.models import Job
from services.job_match import _job_to_dict, score_job

logger = logging.getLogger(__name__)


async def search_jobs_by_keywords(
    keywords: list[str],
    cv_skills: list[str] | None = None,
    preferences: dict | None = None,
    limit: int = 10,
    threshold: int = 15,
    location_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    Full-text keyword search against Job.title, description, requirements.
    Results are re-scored using the existing scoring engine for ranking.
    Optionally filter by location: "remote" → remote jobs only,
    specific location → ilike match, None/"any" → no filter.
    """
    if not keywords:
        return []

    cv_skills = cv_skills or []
    preferences = preferences or {}

    cutoff = datetime.utcnow() - timedelta(days=30)

    # Build OR conditions for each keyword across title, description, company
    conditions = []
    for kw in keywords:
        kw_pattern = f"%{kw.strip().lower()}%"
        conditions.append(Job.title.ilike(kw_pattern))
        conditions.append(Job.description.ilike(kw_pattern))
        conditions.append(Job.company.ilike(kw_pattern))
        conditions.append(Job.location.ilike(kw_pattern))

    query = (
        select(Job)
        .where(Job.posted_at >= cutoff)
        .where(or_(*conditions))
    )

    # Apply location filter
    if location_filter and location_filter.lower() not in ("any", ""):
        if location_filter.lower() == "remote":
            query = query.where(Job.remote == True)
        else:
            query = query.where(Job.location.ilike(f"%{location_filter}%"))

    query = query.order_by(Job.posted_at.desc()).limit(200)

    async with AsyncSessionLocal() as db:
        result = await db.execute(query)
        db_jobs = result.scalars().all()

    if not db_jobs:
        return []

    logger.info("Keyword search '%s' matched %d jobs", ", ".join(keywords), len(db_jobs))

    # Score and rank
    scored = []
    for job in db_jobs:
        job_dict = _job_to_dict(job)
        score, reason = score_job(job_dict, cv_skills, preferences)

        # Boost score for keyword relevance
        keyword_bonus = 0
        text = f"{job.title} {job.description or ''} {job.company}".lower()
        for kw in keywords:
            if kw.lower() in text:
                keyword_bonus += 5
        score = min(score + keyword_bonus, 100)

        if score >= threshold:
            scored.append({**job_dict, "match_score": score, "match_reason": reason})

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:limit]
