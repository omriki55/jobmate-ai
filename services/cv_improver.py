"""
CV Improver Service — generates detailed CV improvement suggestions.

Given a parsed CV, asks Claude to:
  1. Rewrite the professional summary
  2. Improve experience bullet points with metrics and action verbs
  3. Suggest skills to add
  4. Provide formatting tips
  5. Estimate an improved score

Falls back gracefully to template-based suggestions when the API key is absent.
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

IMPROVE_PROMPT = """\
You are an expert CV writer and career coach. The candidate wants to improve their CV.
Analyze the CV and provide concrete, copy-ready improvements.

## Candidate CV
Name: {name}
Domain: {primary_domain}
Seniority: {seniority_level}
Years of experience: {total_years_experience}
Current CV Score: {cv_score}/100
Skills: {skills}

## Current Summary
{summary}

## Experience
{experience}

## Education
{education}

## Task
Rewrite and improve the CV. Return ONLY a valid JSON object — no markdown fences:
{{
  "improved_summary": "A polished, compelling 3-4 sentence professional summary that highlights key strengths and value proposition",
  "original_summary": "The original summary for comparison",
  "rewritten_experience": [
    {{
      "company": "Company name",
      "title": "Job title",
      "original": "Their original description (abbreviated)",
      "improved": "Rewritten with strong action verbs, quantified metrics, and achievement-focused language",
      "changes": ["Specific improvement made", "Another improvement"]
    }}
  ],
  "skills_to_add": ["skill1", "skill2", "skill3", "skill4", "skill5"],
  "formatting_tips": ["tip1", "tip2", "tip3"],
  "overall_improvement": "Brief 1-2 sentence explanation of the key changes and why they matter",
  "improved_score": 85
}}

Rules:
- improved_summary must be substantially better than the original — add keywords, metrics, specifics.
- For each experience entry, rewrite the description with STAR method (Situation, Task, Action, Result).
- Add specific numbers/percentages where plausible (e.g. "managed team of 5", "improved efficiency by 30%").
- skills_to_add should be in-demand skills the candidate likely has but didn't list.
- formatting_tips: practical advice like "use consistent date formats", "add a Skills section header".
- improved_score should be realistic (typically 10-20 points above current score).
- Return ONLY the JSON object.
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def generate_cv_improvement(cv_data: dict[str, Any]) -> dict[str, Any]:
    """
    Call Claude to generate detailed CV improvements.
    Falls back to template-based suggestions when Claude is unavailable.
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        logger.info("No API key — using fallback CV improvement")
        return _fallback_improvement(cv_data)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        # Format experience for the prompt
        exp_lines = []
        for exp in cv_data.get("experience", [])[:5]:
            exp_lines.append(
                f"- {exp.get('title', '')} at {exp.get('company', '')} "
                f"({exp.get('start_date', '')} - {exp.get('end_date', '')}): "
                f"{(exp.get('description', '') or '')[:300]}"
            )

        # Format education
        edu_lines = []
        for edu in cv_data.get("education", [])[:3]:
            edu_lines.append(
                f"- {edu.get('degree', '')} in {edu.get('field', '')} "
                f"from {edu.get('institution', '')} ({edu.get('year', '')})"
            )

        prompt = IMPROVE_PROMPT.format(
            name=cv_data.get("name", "Candidate"),
            primary_domain=cv_data.get("primary_domain", "professional"),
            seniority_level=cv_data.get("seniority_level", "mid"),
            total_years_experience=cv_data.get("total_years_experience", 0),
            cv_score=cv_data.get("cv_score", 50),
            skills=", ".join(cv_data.get("skills", [])[:20]),
            summary=(cv_data.get("summary", "") or "") or "No summary provided",
            experience="\n".join(exp_lines) if exp_lines else "No experience data",
            education="\n".join(edu_lines) if edu_lines else "No education data",
        )

        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # Strip optional markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]

        return json.loads(raw.strip())

    except Exception as exc:
        logger.warning("CV improvement Claude call failed: %s", exc)
        return _fallback_improvement(cv_data)


# ---------------------------------------------------------------------------
# Template-based fallback
# ---------------------------------------------------------------------------

def _fallback_improvement(cv_data: dict[str, Any]) -> dict[str, Any]:
    """Provide generic but useful improvement suggestions when Claude is unavailable."""
    name = cv_data.get("name", "Candidate")
    domain = cv_data.get("primary_domain", "professional")
    seniority = cv_data.get("seniority_level", "mid")
    yoe = cv_data.get("total_years_experience", 0)
    skills = cv_data.get("skills", [])
    summary = cv_data.get("summary", "") or ""
    cv_score = cv_data.get("cv_score", 50)

    # Build improved experience entries from existing experience
    rewritten = []
    for exp in cv_data.get("experience", [])[:3]:
        title = exp.get("title", "Role")
        company = exp.get("company", "Company")
        original = (exp.get("description", "") or "")[:200]
        rewritten.append({
            "company": company,
            "title": title,
            "original": original or "No description provided",
            "improved": (
                f"Led key initiatives as {title}, driving measurable results through "
                f"data-driven strategies and cross-functional collaboration. "
                f"Improved team efficiency by implementing streamlined processes "
                f"and leveraging {', '.join(skills[:2]) if skills else domain} expertise."
            ),
            "changes": [
                "Added quantified impact metrics",
                "Used strong action verbs (Led, Drove, Improved)",
                "Highlighted cross-functional collaboration",
            ],
        })

    if not rewritten:
        rewritten = [{
            "company": "Your Company",
            "title": f"{seniority.title()} {domain.title()}",
            "original": "No experience descriptions found in CV",
            "improved": (
                f"Contributed to high-impact {domain} projects, "
                f"collaborating with stakeholders to deliver measurable results. "
                f"Applied expertise in {', '.join(skills[:3]) if skills else domain} "
                f"to improve processes and drive team success."
            ),
            "changes": [
                "Added specific, achievement-focused language",
                "Included relevant technical skills",
                "Emphasized collaboration and results",
            ],
        }]

    # Build improved summary
    improved_summary = (
        f"Results-driven {seniority} {domain} professional with {yoe}+ years of experience "
        f"delivering high-impact solutions. Expertise in {', '.join(skills[:4]) if skills else domain}, "
        f"with a proven track record of driving efficiency and innovation. "
        f"Passionate about leveraging technical skills to solve complex problems and create value."
    )

    # Skills suggestions based on domain
    domain_skills_map = {
        "software": ["CI/CD", "Agile/Scrum", "System Design", "API Development", "Cloud Architecture"],
        "product": ["Roadmap Planning", "A/B Testing", "User Research", "OKRs", "Stakeholder Management"],
        "data": ["SQL", "Data Visualization", "Statistical Analysis", "ETL Pipelines", "Machine Learning"],
        "design": ["Figma", "User Testing", "Design Systems", "Accessibility", "Prototyping"],
        "marketing": ["SEO/SEM", "Analytics", "Content Strategy", "Growth Hacking", "Campaign Management"],
    }
    domain_key = next((k for k in domain_skills_map if k in domain.lower()), None)
    suggested_skills = domain_skills_map.get(domain_key, [
        "Project Management", "Data Analysis", "Communication", "Problem Solving", "Leadership"
    ])

    return {
        "improved_summary": improved_summary,
        "original_summary": summary or "No summary in current CV",
        "rewritten_experience": rewritten,
        "skills_to_add": suggested_skills,
        "formatting_tips": [
            "Use consistent date formats throughout (e.g., 'Jan 2020 - Present')",
            "Add a 'Key Skills' section near the top for ATS scanners",
            "Keep bullet points to 1-2 lines max with quantified results",
            "Use reverse-chronological order for experience",
        ],
        "overall_improvement": (
            f"Focus on adding quantified achievements and ATS-friendly keywords. "
            f"Your {domain} experience is strong — the improvements highlight your impact more clearly."
        ),
        "improved_score": min(95, cv_score + 15),
    }
