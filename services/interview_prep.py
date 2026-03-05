"""
Interview Prep Service — Phase 3D

Given a parsed CV and target job, Claude generates 5 highly-likely interview
questions with STAR-framework answer guides tailored to the candidate's background.

Falls back to role-generic questions when the API key is absent.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

PREP_PROMPT = """\
You are a world-class interview coach preparing a candidate for an interview.

## Candidate Profile
Name: {name}
Domain: {primary_domain}
Seniority: {seniority_level}
Years of experience: {total_years_experience}
Skills: {skills}
Summary: {summary}

## Target Role
Title: {job_title}
Company: {company}
Requirements: {requirements}

## Task
Generate exactly 5 interview questions this candidate is very likely to face.
Mix behavioral, technical, situational and culture-fit questions.

Return ONLY a valid JSON array — no markdown fences, no explanation:
[
  {{
    "question": "Tell me about yourself",
    "category": "behavioral",
    "answer_guide": "2-3 sentence guide using their actual skills and experience",
    "key_points": ["Specific point 1", "Specific point 2", "Specific point 3"]
  }}
]

Rules:
- answer_guide MUST reference the candidate's specific domain, seniority, or named skills.
- key_points must be concrete, not generic advice.
- category is one of: behavioral | technical | situational | culture
- Return ONLY the JSON array.
"""


async def generate_interview_prep(
    cv_data: dict[str, Any],
    job: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate 5 tailored interview Q&A pairs. Falls back gracefully."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        logger.info("No API key — using fallback interview prep")
        return _fallback_prep(cv_data, job)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        prompt = PREP_PROMPT.format(
            name=cv_data.get("name", "Candidate"),
            primary_domain=cv_data.get("primary_domain", "your field"),
            seniority_level=cv_data.get("seniority_level", "mid"),
            total_years_experience=cv_data.get("total_years_experience", 0),
            skills=", ".join(cv_data.get("skills", [])[:15]),
            summary=(cv_data.get("summary", "") or "")[:300],
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            requirements=", ".join(job.get("requirements", [])[:12]),
        )

        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
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
        logger.warning("Interview prep Claude call failed: %s", exc)
        return _fallback_prep(cv_data, job)


def _fallback_prep(cv_data: dict[str, Any], job: dict[str, Any]) -> list[dict[str, Any]]:
    domain  = cv_data.get("primary_domain", "your field")
    yoe     = cv_data.get("total_years_experience", 0)
    skills  = cv_data.get("skills", [])
    title   = job.get("title", "this role")
    company = job.get("company", "the company")
    reqs    = job.get("requirements", [])

    top_skill = skills[0] if skills else domain
    top_req   = reqs[0]   if reqs   else domain

    return [
        {
            "question": "Tell me about yourself and your professional background.",
            "category": "behavioral",
            "answer_guide": (
                f"Open with your {yoe} years in {domain}, name 2-3 key skills "
                f"({', '.join(skills[:3]) or domain}), then explain why {company} is your next move."
            ),
            "key_points": [
                f"{yoe}+ years specialising in {domain}",
                f"Core strengths: {', '.join(skills[:3]) or top_skill}",
                f"Excited by {company}'s mission and this {title} opportunity",
            ],
        },
        {
            "question": f"Why do you want to work at {company} as a {title}?",
            "category": "culture",
            "answer_guide": (
                f"Research {company}'s product, values, or recent milestones. "
                f"Connect them to your {domain} experience and long-term goals."
            ),
            "key_points": [
                f"Specific thing you admire about {company}",
                f"How your {domain} background maps to their needs",
                "Long-term growth and impact you want to create",
            ],
        },
        {
            "question": f"Describe a challenging project where you applied {top_skill}.",
            "category": "behavioral",
            "answer_guide": (
                "Use the STAR method (Situation → Task → Action → Result). "
                f"Emphasise your use of {top_skill} and quantify the outcome."
            ),
            "key_points": [
                "Set context in 1-2 sentences",
                f"Your specific actions with {top_skill}",
                "Quantified result (%, $, time saved, users impacted)",
            ],
        },
        {
            "question": f"How do you approach learning {top_req}? Walk me through your process.",
            "category": "technical",
            "answer_guide": (
                f"Show curiosity and structured learning. Reference how you picked up "
                f"{top_req or top_skill} and applied it on a real project."
            ),
            "key_points": [
                "Resources and learning method (docs, courses, side projects)",
                "Specific project where you applied it",
                "How you stay current in this area",
            ],
        },
        {
            "question": "Tell me about a time you disagreed with a stakeholder. How did you handle it?",
            "category": "situational",
            "answer_guide": (
                "Pick a real disagreement you resolved professionally. "
                "Show empathy, data-driven reasoning, and a positive outcome."
            ),
            "key_points": [
                "State your position clearly with evidence",
                "Acknowledge the other perspective",
                "Resolution and what you both learned",
            ],
        },
    ]
