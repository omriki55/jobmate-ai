"""
Headhunter Finder Service — helps users find specialized recruiters.

Uses Claude to generate tailored strategies for finding recruiters
in the user's specific field, including search queries, outreach templates,
and relevant directories.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

HEADHUNTER_PROMPT = """\
You are a career networking expert helping a job seeker find specialized recruiters
and headhunters in their field.

## Candidate Profile
Domain: {domain}
Seniority: {seniority}
Location: {location}
Key Skills: {skills}
Target Roles: {target_roles}

## Task
Generate a comprehensive recruiter-finding strategy. Return ONLY a valid JSON object:
{{
  "linkedin_search_queries": [
    "3-4 specific LinkedIn search URLs or queries to find relevant recruiters"
  ],
  "strategies": [
    "5-6 specific, actionable strategies for connecting with recruiters in this field"
  ],
  "recruiter_directories": [
    {{"name": "Directory name", "url": "https://...", "notes": "Why this is relevant"}}
  ],
  "cold_outreach_template": "A professional, concise outreach message template (2-3 sentences)",
  "linkedin_connection_template": "A brief LinkedIn connection request message (under 200 chars)",
  "tips": [
    "3-4 pro tips for working with recruiters effectively"
  ]
}}

Rules:
- Be specific to the candidate's domain and seniority level.
- LinkedIn search queries should be actual search strings they can paste.
- Recruiter directories should be real, well-known platforms.
- Templates should be professional but warm, not generic.
- Return ONLY the JSON object.
"""


async def find_headhunters(
    domain: str,
    location: str,
    seniority: str,
    skills: list[str] | None = None,
    target_roles: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a recruiter-finding strategy tailored to the user's field."""
    skills = skills or []
    target_roles = target_roles or []

    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return _fallback_finder(domain, location, seniority, skills)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        prompt = HEADHUNTER_PROMPT.format(
            domain=domain,
            seniority=seniority,
            location=location,
            skills=", ".join(skills[:10]),
            target_roles=", ".join(target_roles[:5]) if target_roles else domain,
        )

        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
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
        logger.warning("Headhunter finder failed: %s", exc)
        return _fallback_finder(domain, location, seniority, skills)


def _fallback_finder(
    domain: str, location: str, seniority: str, skills: list[str]
) -> dict[str, Any]:
    """Keyword-based fallback when Claude is unavailable."""
    return {
        "linkedin_search_queries": [
            f'"recruiter" OR "headhunter" "{domain}" "{location}"',
            f'"talent acquisition" "{domain}" "{seniority}"',
            f'"{domain} recruiter" hiring site:linkedin.com',
        ],
        "strategies": [
            f"Search LinkedIn for recruiters specializing in {domain}",
            "Update your LinkedIn headline to signal you're open to opportunities",
            f"Join {domain}-specific Slack/Discord communities where recruiters post",
            "Attend industry meetups and conferences — recruiters frequent these",
            "Set your LinkedIn profile to 'Open to Work' (visible to recruiters only)",
            "Respond to recruiter InMails promptly, even for roles you're not interested in",
        ],
        "recruiter_directories": [
            {"name": "LinkedIn Recruiter Search", "url": "https://www.linkedin.com/search/results/people/", "notes": f"Search for '{domain} recruiter' in your target location"},
            {"name": "Hired.com", "url": "https://hired.com", "notes": "Tech-focused talent marketplace where companies come to you"},
            {"name": "Wellfound (AngelList)", "url": "https://wellfound.com", "notes": "Startup-focused job platform with direct recruiter connections"},
        ],
        "cold_outreach_template": (
            f"Hi {{name}}, I'm a {seniority} {domain} professional with expertise in "
            f"{', '.join(skills[:3]) if skills else domain}. I'm exploring new opportunities "
            f"and would love to connect about roles you might be working on. Would you be "
            f"open to a brief chat?"
        ),
        "linkedin_connection_template": (
            f"Hi! I'm a {seniority} {domain} professional exploring new opportunities. "
            f"Would love to connect!"
        ),
        "tips": [
            "Always personalize your outreach — mention the recruiter's specialization",
            "Be clear about your salary expectations and location preferences upfront",
            "Follow up once after 5-7 days if you don't hear back, then move on",
            "Keep your LinkedIn profile updated — recruiters check it before responding",
        ],
    }
