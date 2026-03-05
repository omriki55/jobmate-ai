"""
CV Tailoring Service — Phase 2B

Given a parsed CV and a job dict, asks Claude to:
  1. Write a punchy tailored headline for this specific application
  2. Identify the top 3 skills/experiences to lead with
  3. Draft 3 concise cover talking-points (achievement → requirement mapping)
  4. Flag ≤2 skill gaps to address in the interview

Falls back gracefully to keyword-based logic when the API key is absent.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

TAILOR_PROMPT = """\
You are an expert career coach and CV writer helping a candidate stand out.

## Candidate Profile
Name: {name}
Domain: {primary_domain}
Seniority: {seniority_level}
Years of experience: {total_years_experience}
Skills: {skills}
Professional summary: {summary}

## Target Role
Title: {job_title}
Company: {company}
Location: {location}
Description: {description}
Requirements: {requirements}

## Your Task
Analyse the fit and return ONLY a valid JSON object with these exact keys:
{{
  "tailored_headline": "Punchy 8-12 word headline written for THIS specific application",
  "match_narrative": "One compelling sentence on why this candidate is a strong fit",
  "top_skills_to_highlight": ["skill1", "skill2", "skill3"],
  "cover_points": [
    "Achievement or experience that directly maps to requirement 1",
    "Achievement or experience that directly maps to requirement 2",
    "Achievement or experience that directly maps to requirement 3"
  ],
  "skill_gaps": ["gap1", "gap2"],
  "ats_score": 78,
  "missing_keywords": ["keyword from JD not found in CV", "another missing keyword"],
  "rewritten_bullets": [
    "Original: 'Managed deployments' → Optimized: 'Managed cloud deployments using CI/CD pipelines, reducing release cycles by 40%'"
  ]
}}

Rules:
- Be specific — reference the company name and role title.
- cover_points must start with an action verb and include a concrete outcome.
- skill_gaps should be honest but brief (max 2 items; empty list [] if no gaps).
- ats_score 0-100: how well the CV would pass an ATS for this specific role.
- missing_keywords: important terms from the job description absent from the CV (max 5).
- rewritten_bullets: 2-3 CV bullet rewrites incorporating missing keywords (format: "Original: '...' → Optimized: '...'").
- Return ONLY the JSON object — no markdown fences, no explanation.
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def tailor_cv_for_job(
    cv_data: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    """
    Call Claude to tailor CV talking-points for a specific job.
    Falls back to keyword-based heuristics when Claude is unavailable.
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        logger.info("No API key — using fallback CV tailoring")
        return _fallback_tailor(cv_data, job)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        prompt = TAILOR_PROMPT.format(
            name=cv_data.get("name", "Candidate"),
            primary_domain=cv_data.get("primary_domain", "your field"),
            seniority_level=cv_data.get("seniority_level", "mid"),
            total_years_experience=cv_data.get("total_years_experience", 0),
            skills=", ".join(cv_data.get("skills", [])[:20]),
            summary=(cv_data.get("summary", "") or "")[:400],
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            description=(job.get("description", "") or "")[:800],
            requirements=", ".join(job.get("requirements", [])[:15]),
        )

        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # Strip optional markdown fences just in case
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]

        return json.loads(raw.strip())

    except Exception as exc:
        logger.warning("CV tailoring Claude call failed: %s", exc)
        return _fallback_tailor(cv_data, job)


# ---------------------------------------------------------------------------
# Keyword-based fallback
# ---------------------------------------------------------------------------

def _fallback_tailor(cv_data: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Simple overlap-based fallback when Claude is unavailable."""
    cv_skills_lower = [s.lower() for s in cv_data.get("skills", [])]
    job_reqs        = [r.lower() for r in job.get("requirements", [])]

    matched = [
        r for r in job_reqs
        if any(r in s or s in r for s in cv_skills_lower)
    ]
    gaps = [r for r in job_reqs if r not in matched][:2]

    domain   = cv_data.get("primary_domain", "professional")
    seniority = cv_data.get("seniority_level", "experienced")
    yoe      = cv_data.get("total_years_experience", 0)
    company  = job.get("company", "the company")
    title    = job.get("title", "this role")

    return {
        "tailored_headline": f"{seniority.title()} {domain.title()} ready to drive impact at {company}",
        "match_narrative": (
            f"Your {yoe}-year background in {domain} maps directly to what {company} "
            f"needs for this {title} role."
        ),
        "top_skills_to_highlight": (matched[:3] or cv_skills_lower[:3]),
        "cover_points": [
            f"Bring {yoe}+ years of {domain} experience that aligns with the core requirements.",
            f"Proven proficiency in {', '.join(matched[:2]) if matched else domain} — skills central to this role.",
            f"Track record of delivering results at {seniority} level in fast-paced environments.",
        ],
        "skill_gaps": gaps,
        "ats_score": min(85, len(matched) * 15 + 30) if job_reqs else 60,
        "missing_keywords": gaps[:5],
        "rewritten_bullets": [
            f"Add quantified results to your {domain} experience bullets",
            f"Include keywords: {', '.join(gaps[:3])}" if gaps else "Your skills align well with this role",
        ],
    }
