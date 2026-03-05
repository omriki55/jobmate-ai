"""
Company Research Service — extracts company context from job descriptions.

Used to enrich interview prep with company-specific talking points.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

RESEARCH_PROMPT = """\
You are a company research analyst. Given a job listing, extract what you can
infer about the company.

## Job Listing
Title: {job_title}
Company: {company}
Location: {location}
Description: {description}
Requirements: {requirements}

Return ONLY a valid JSON object — no markdown fences:
{{
  "company_overview": "1-2 sentences about what this company does based on the listing",
  "company_values": ["value1", "value2", "value3"],
  "tech_stack": ["tech1", "tech2"],
  "team_culture_hints": ["hint1", "hint2"],
  "likely_interview_focus": ["area1", "area2", "area3"],
  "talking_points": ["Something specific you could mention about the company in the interview"]
}}

Rules:
- Only include information you can reasonably infer from the listing.
- Be specific, not generic.
- Return ONLY the JSON object.
"""


async def research_company(
    company_name: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    """Extract company context from job description using Claude."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return _fallback_research(company_name, job)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        prompt = RESEARCH_PROMPT.format(
            job_title=job.get("title", ""),
            company=company_name,
            location=job.get("location", ""),
            description=(job.get("description", "") or "")[:1000],
            requirements=", ".join(job.get("requirements", [])[:15]),
        )

        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]
        return json.loads(raw.strip())

    except Exception as exc:
        logger.warning("Company research failed: %s", exc)
        return _fallback_research(company_name, job)


def _fallback_research(company_name: str, job: dict[str, Any]) -> dict[str, Any]:
    """Simple fallback when Claude is unavailable."""
    reqs = job.get("requirements", [])
    return {
        "company_overview": f"{company_name} is hiring for {job.get('title', 'this role')}.",
        "company_values": ["innovation", "collaboration", "growth"],
        "tech_stack": reqs[:5] if reqs else [],
        "team_culture_hints": [
            "Review their careers page for culture details",
            "Check Glassdoor for employee reviews",
        ],
        "likely_interview_focus": reqs[:3] if reqs else ["role-specific skills"],
        "talking_points": [
            f"Express genuine interest in {company_name}'s mission",
            "Ask about team structure and growth opportunities",
        ],
    }
