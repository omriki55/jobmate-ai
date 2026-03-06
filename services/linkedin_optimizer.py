"""
LinkedIn Optimizer Service — generates a LinkedIn profile optimization guide.

Since LinkedIn API doesn't allow writing to user profiles for most developers,
this generates copyable optimization suggestions based on the user's CV data.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

LINKEDIN_PROMPT = """\
You are an expert LinkedIn profile optimizer and ATS specialist.
Given a candidate's CV data, generate specific LinkedIn optimization advice.

## Candidate Profile
Name: {name}
Domain: {primary_domain}
Seniority: {seniority_level}
Years of experience: {total_years_experience}
Skills: {skills}
Summary: {summary}
Target Roles: {target_roles}
{linkedin_line}
## Experience
{experience}

## Task
Generate a comprehensive LinkedIn optimization guide.
Return ONLY a valid JSON object — no markdown fences:
{{
  "headline_suggestions": [
    "3 headline options, each under 120 characters, optimized for ATS"
  ],
  "about_section": "A compelling About section draft (300-500 words) in first person",
  "experience_tips": [
    {{
      "role": "Job title from their CV",
      "current": "Their current description (brief)",
      "suggested": "Optimized version with metrics and keywords"
    }}
  ],
  "skills_to_add": ["10 LinkedIn skills to add for ATS visibility"],
  "keyword_optimization": ["Keywords to weave throughout the profile"],
  "profile_strength_score": 72,
  "section_checklist": [
    {{
      "section": "Headline",
      "status": "needs_improvement|good|missing",
      "action": "Specific action to take"
    }}
  ]
}}

Rules:
- Headlines must include keywords that recruiters search for.
- About section should tell a story, not just list achievements.
- Experience tips should add quantified metrics where possible.
- Skills should be ATS-friendly and match common job listing keywords.
- Be specific to their domain and seniority.
- Return ONLY the JSON object.
"""


async def generate_linkedin_optimization(
    cv_data: dict[str, Any],
    target_roles: list[str] | None = None,
    linkedin_url: str | None = None,
) -> dict[str, Any]:
    """Generate a LinkedIn optimization guide from CV data."""
    target_roles = target_roles or []

    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return _fallback_optimization(cv_data, target_roles)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        # Format experience for the prompt
        exp_lines = []
        for exp in cv_data.get("experience", [])[:5]:
            exp_lines.append(
                f"- {exp.get('title', '')} at {exp.get('company', '')} "
                f"({exp.get('start_date', '')} - {exp.get('end_date', '')}): "
                f"{(exp.get('description', '') or '')[:200]}"
            )

        linkedin_line = f"LinkedIn Profile: {linkedin_url}\n" if linkedin_url else ""

        prompt = LINKEDIN_PROMPT.format(
            name=cv_data.get("name", "Candidate"),
            primary_domain=cv_data.get("primary_domain", "professional"),
            seniority_level=cv_data.get("seniority_level", "mid"),
            total_years_experience=cv_data.get("total_years_experience", 0),
            skills=", ".join(cv_data.get("skills", [])[:15]),
            summary=(cv_data.get("summary", "") or "")[:300],
            target_roles=", ".join(target_roles) if target_roles else "Not specified",
            linkedin_line=linkedin_line,
            experience="\n".join(exp_lines) if exp_lines else "No experience data available",
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
        logger.warning("LinkedIn optimization failed: %s", exc)
        return _fallback_optimization(cv_data, target_roles)


def _fallback_optimization(
    cv_data: dict[str, Any],
    target_roles: list[str],
) -> dict[str, Any]:
    """Fallback when Claude is unavailable."""
    name = cv_data.get("name", "Professional")
    domain = cv_data.get("primary_domain", "professional")
    seniority = cv_data.get("seniority_level", "mid")
    yoe = cv_data.get("total_years_experience", 0)
    skills = cv_data.get("skills", [])

    return {
        "headline_suggestions": [
            f"{seniority.title()} {domain.title()} | {', '.join(skills[:3]).title()} | Open to Opportunities",
            f"{domain.title()} Expert with {yoe}+ Years | {skills[0].title() if skills else domain.title()} Specialist",
            f"Experienced {domain.title()} Professional | Building Impactful Solutions",
        ],
        "about_section": (
            f"With {yoe}+ years of experience in {domain}, I bring a proven track record "
            f"of delivering results through {', '.join(skills[:3]) if skills else 'diverse skill sets'}.\n\n"
            f"Throughout my career, I've focused on creating impact through data-driven decisions "
            f"and collaborative problem-solving. I'm passionate about {domain} and continuously "
            f"learning to stay at the forefront of the field.\n\n"
            f"Core competencies: {', '.join(skills[:8]) if skills else domain}\n\n"
            f"I'm currently exploring new opportunities where I can contribute my expertise "
            f"and grow professionally. Let's connect!"
        ),
        "experience_tips": [
            {
                "role": exp.get("title", "Role"),
                "current": (exp.get("description", "") or "")[:100],
                "suggested": f"Add quantified results: 'Improved X by Y%', 'Led team of N', 'Delivered project Z ahead of schedule'",
            }
            for exp in cv_data.get("experience", [])[:3]
        ] if cv_data.get("experience") else [
            {"role": "All roles", "current": "No descriptions found", "suggested": "Add 3-5 bullet points per role with measurable achievements"}
        ],
        "skills_to_add": (skills[:10] if skills else [
            domain, "project management", "communication", "teamwork",
            "problem solving", "leadership", "analytics",
        ]),
        "keyword_optimization": [
            f"Include '{domain}' in headline and about section",
            "Add industry-specific certifications if you have them",
            "Use exact phrases from target job descriptions",
            "Include both abbreviations and full terms (e.g., 'ML / Machine Learning')",
        ],
        "profile_strength_score": min(75, cv_data.get("cv_score", 55) + 10),
        "section_checklist": [
            {"section": "Profile Photo", "status": "missing" if not cv_data.get("name") else "good", "action": "Add a professional headshot with good lighting"},
            {"section": "Headline", "status": "needs_improvement", "action": "Replace default title with keyword-rich headline"},
            {"section": "About", "status": "needs_improvement", "action": "Write a compelling 300+ word About section"},
            {"section": "Experience", "status": "needs_improvement", "action": "Add quantified achievements to each role"},
            {"section": "Skills", "status": "needs_improvement", "action": "Add at least 15 relevant skills"},
            {"section": "Recommendations", "status": "missing", "action": "Request 2-3 recommendations from colleagues"},
        ],
    }
