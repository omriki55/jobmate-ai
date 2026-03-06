"""
LinkedIn Optimizer Service — scans and analyzes LinkedIn profiles section by section.

Accepts pasted LinkedIn profile text, parses it into sections, and generates
specific improvements for each part. Falls back to CV-based tips when no
profile text is provided.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt for scanning actual LinkedIn profile text
# ---------------------------------------------------------------------------

SCAN_PROMPT = """\
You are an expert LinkedIn profile optimizer and ATS specialist.
A user has pasted the text content of their LinkedIn profile page.
Analyze each section and provide specific, actionable improvements.

## Pasted LinkedIn Profile
{profile_text}

## Candidate CV Data (for additional context)
Name: {name}
Domain: {primary_domain}
Seniority: {seniority_level}
Years of experience: {total_years_experience}
Skills from CV: {skills}
Target Roles: {target_roles}

## Task
Analyze the LinkedIn profile section by section. Identify what's there,
what's missing, and how to improve each part.

Return ONLY a valid JSON object — no markdown fences:
{{
  "profile_score": 65,
  "sections": [
    {{
      "name": "Headline",
      "current": "The exact headline text from their profile",
      "improved": "An optimized headline with ATS keywords, under 120 chars",
      "issues": ["Specific issue 1", "Specific issue 2"],
      "priority": "high"
    }},
    {{
      "name": "About",
      "current": "Their current about section text (abbreviated if long)",
      "improved": "A rewritten about section in first person, 300-500 words, keyword-rich",
      "issues": ["Specific issues found"],
      "priority": "high"
    }},
    {{
      "name": "Experience: [Job Title] at [Company]",
      "current": "Their current experience description",
      "improved": "Rewritten with STAR method, metrics, action verbs",
      "issues": ["Missing metrics", "Weak verbs"],
      "priority": "medium"
    }}
  ],
  "missing_sections": ["Sections they should add but don't have"],
  "keyword_gaps": ["Important ATS keywords missing from their profile"],
  "overall_summary": "2-3 sentence summary of key improvements needed"
}}

Rules:
- Analyze EVERY section you can identify in the pasted text.
- For each section, quote their ACTUAL current text (abbreviated to ~100 chars if long).
- Provide a COMPLETE rewritten improved version they can copy-paste.
- Issues should be specific (not generic like "needs improvement").
- Priority: "high" for headline/about, "medium" for experience, "low" for extras.
- Include experience entries for each job found in the profile.
- missing_sections: check for Featured, Volunteer, Certifications, Publications, Projects.
- keyword_gaps: compare against common ATS keywords for their domain.
- Return ONLY the JSON object.
"""

# ---------------------------------------------------------------------------
# Legacy prompt (CV-only, when no profile text provided)
# ---------------------------------------------------------------------------

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
  "profile_score": 50,
  "sections": [
    {{
      "name": "Headline",
      "current": "Unknown — paste your profile for a scan",
      "improved": "3 headline options optimized for ATS",
      "issues": ["Cannot analyze without seeing your actual profile"],
      "priority": "high"
    }}
  ],
  "missing_sections": [],
  "keyword_gaps": ["Keywords to weave throughout the profile"],
  "overall_summary": "Summary of recommended improvements based on your CV",
  "headline_suggestions": [
    "3 headline options, each under 120 characters, optimized for ATS"
  ],
  "about_section": "A compelling About section draft (300-500 words) in first person",
  "skills_to_add": ["10 LinkedIn skills to add for ATS visibility"]
}}

Rules:
- Headlines must include keywords that recruiters search for.
- About section should tell a story, not just list achievements.
- Skills should be ATS-friendly and match common job listing keywords.
- Be specific to their domain and seniority.
- Return ONLY the JSON object.
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def generate_linkedin_optimization(
    cv_data: dict[str, Any],
    target_roles: list[str] | None = None,
    linkedin_url: str | None = None,
    profile_text: str | None = None,
) -> dict[str, Any]:
    """Generate LinkedIn optimization — uses profile text if provided, else CV data."""
    target_roles = target_roles or []

    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return _fallback_optimization(cv_data, target_roles, profile_text)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        if profile_text and len(profile_text.strip()) > 50:
            # ── Profile scan mode: analyze actual LinkedIn content ──
            prompt = SCAN_PROMPT.format(
                profile_text=profile_text[:8000],  # Cap to avoid token limits
                name=cv_data.get("name", "Candidate"),
                primary_domain=cv_data.get("primary_domain", "professional"),
                seniority_level=cv_data.get("seniority_level", "mid"),
                total_years_experience=cv_data.get("total_years_experience", 0),
                skills=", ".join(cv_data.get("skills", [])[:15]),
                target_roles=", ".join(target_roles) if target_roles else "Not specified",
            )
            max_tokens = 3000
        else:
            # ── Legacy mode: generate tips from CV data ──
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
            max_tokens = 2000

        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
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
        return _fallback_optimization(cv_data, target_roles, profile_text)


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def _fallback_optimization(
    cv_data: dict[str, Any],
    target_roles: list[str],
    profile_text: str | None = None,
) -> dict[str, Any]:
    """Fallback when Claude is unavailable."""
    name = cv_data.get("name", "Professional")
    domain = cv_data.get("primary_domain", "professional")
    seniority = cv_data.get("seniority_level", "mid")
    yoe = cv_data.get("total_years_experience", 0)
    skills = cv_data.get("skills", [])

    # If profile text was provided, build sections from it
    sections = []
    if profile_text and len(profile_text.strip()) > 50:
        sections.append({
            "name": "Headline",
            "current": profile_text.strip()[:120].split("\n")[0],
            "improved": f"{seniority.title()} {domain.title()} | {', '.join(skills[:3]).title()} | Open to Opportunities",
            "issues": ["Consider adding ATS keywords", "Include your specialty area"],
            "priority": "high",
        })
        sections.append({
            "name": "About",
            "current": "(See your pasted profile above)",
            "improved": (
                f"With {yoe}+ years of experience in {domain}, I bring a proven track record "
                f"of delivering results through {', '.join(skills[:3]) if skills else 'diverse skill sets'}.\n\n"
                f"Throughout my career, I've focused on creating impact through data-driven decisions "
                f"and collaborative problem-solving. I'm passionate about {domain} and continuously "
                f"learning to stay at the forefront of the field.\n\n"
                f"Core competencies: {', '.join(skills[:8]) if skills else domain}\n\n"
                f"I'm currently exploring new opportunities where I can contribute my expertise "
                f"and grow professionally. Let's connect!"
            ),
            "issues": ["Add quantified achievements", "Include a call-to-action", "Use first person"],
            "priority": "high",
        })
        for exp in cv_data.get("experience", [])[:3]:
            sections.append({
                "name": f"Experience: {exp.get('title', 'Role')} at {exp.get('company', 'Company')}",
                "current": (exp.get("description", "") or "")[:150] or "No description",
                "improved": (
                    f"Led key initiatives as {exp.get('title', 'Role')}, driving measurable results. "
                    f"Improved team efficiency by implementing streamlined processes and leveraging "
                    f"{', '.join(skills[:2]) if skills else domain} expertise."
                ),
                "issues": ["Add specific metrics (%, $, team size)", "Use strong action verbs"],
                "priority": "medium",
            })
    else:
        # No profile text — generic sections from CV
        sections = [
            {
                "name": "Headline",
                "current": "Unknown — paste your profile for a full scan",
                "improved": f"{seniority.title()} {domain.title()} | {', '.join(skills[:3]).title()} | Open to Opportunities",
                "issues": ["Paste your LinkedIn profile for a specific analysis"],
                "priority": "high",
            },
            {
                "name": "About",
                "current": "Unknown — paste your profile for a full scan",
                "improved": (
                    f"With {yoe}+ years of experience in {domain}, I bring a proven track record "
                    f"of delivering results through {', '.join(skills[:3]) if skills else 'diverse skill sets'}.\n\n"
                    f"Core competencies: {', '.join(skills[:8]) if skills else domain}\n\n"
                    f"I'm currently exploring new opportunities. Let's connect!"
                ),
                "issues": ["Paste your LinkedIn profile for a specific analysis"],
                "priority": "high",
            },
        ]

    return {
        "profile_score": min(75, cv_data.get("cv_score", 55) + 10),
        "sections": sections,
        "missing_sections": ["Featured", "Volunteer Experience", "Certifications"],
        "keyword_gaps": [
            domain,
            "project management",
            "data-driven",
            "cross-functional",
        ] + skills[:3],
        "overall_summary": (
            f"Your profile needs ATS-friendly keywords and quantified achievements. "
            f"Focus on your {domain} expertise and add metrics to each experience entry."
        ),
        # Legacy fields for backward compat
        "headline_suggestions": [
            f"{seniority.title()} {domain.title()} | {', '.join(skills[:3]).title()} | Open to Opportunities",
            f"{domain.title()} Expert with {yoe}+ Years | {skills[0].title() if skills else domain.title()} Specialist",
            f"Experienced {domain.title()} Professional | Building Impactful Solutions",
        ],
        "about_section": sections[1]["improved"] if len(sections) > 1 else "",
        "skills_to_add": skills[:10] if skills else [
            domain, "project management", "communication", "teamwork",
            "problem solving", "leadership", "analytics",
        ],
    }
