"""
Company Reviews Service — Glassdoor-style company insights.

Generates company review summaries using Claude's knowledge,
including pros/cons, culture, interview process, and salary estimates.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

REVIEW_PROMPT = """\
You are a company review analyst. Based on what you know about {company_name}, \
generate a Glassdoor-style review summary.

## Company: {company_name}
## Role Context: {job_title} at {location}
## Job Description excerpt: {description}

Return ONLY a valid JSON object:
{{
  "rating": 3.8,
  "pros": ["pro1", "pro2", "pro3"],
  "cons": ["con1", "con2"],
  "interview_process": "Description of typical interview process",
  "culture": "Brief culture description",
  "work_life_balance": "Assessment of work-life balance",
  "salary_range_estimate": "Estimated salary range for this role"
}}

Rules:
- rating is 1.0-5.0 (one decimal)
- Be balanced and honest
- Base on publicly known information about the company
- If you don't know much about the company, say so honestly in the fields
- Return ONLY the JSON object.
"""


async def get_company_reviews(
    company_name: str,
    job_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a Glassdoor-style company review summary."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return _fallback_reviews(company_name, job_data)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        job_data = job_data or {}
        prompt = REVIEW_PROMPT.format(
            company_name=company_name,
            job_title=job_data.get("title", "General"),
            location=job_data.get("location", "Unknown"),
            description=(job_data.get("description", "") or "")[:600],
        )

        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]
        result = json.loads(raw.strip())
        result["company"] = company_name
        return result

    except Exception as exc:
        logger.warning("Company reviews failed: %s", exc)
        return _fallback_reviews(company_name, job_data)


def _fallback_reviews(
    company_name: str,
    job_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fallback when Claude is unavailable."""
    job_data = job_data or {}
    title = job_data.get("title", "this role")
    return {
        "company": company_name,
        "rating": None,
        "pros": [
            f"Research {company_name} on Glassdoor for employee reviews",
            "Check the company's careers page for culture insights",
            "Look at their LinkedIn page for recent updates",
        ],
        "cons": [
            "AI review unavailable — check glassdoor.com for real reviews",
        ],
        "interview_process": (
            f"Research {company_name}'s interview process on Glassdoor and Blind. "
            f"Typical tech interviews include phone screen, technical assessment, "
            f"and final panel."
        ),
        "culture": (
            f"Visit {company_name}'s careers page and social media for culture "
            f"insights. Look for employee testimonials and team photos."
        ),
        "work_life_balance": (
            "Check employee reviews on Glassdoor for work-life balance details. "
            "Ask about this during your interview."
        ),
        "salary_range_estimate": (
            f"Check levels.fyi or Glassdoor for {title} salary data at {company_name}."
        ),
    }
