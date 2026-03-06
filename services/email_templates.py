"""
Email Templates Service — generates personalized email templates.

Given CV data and target job info, generates application emails,
follow-ups, thank-you notes, and networking outreach templates.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

EMAIL_PROMPT = """\
You are an expert career communication specialist.
Given a candidate's profile, generate personalized email templates.

## Candidate Profile
Name: {name}
Domain: {primary_domain}
Seniority: {seniority_level}
Years of experience: {total_years_experience}
Skills: {skills}
Summary: {summary}
Target Roles: {target_roles}
{email_line}
## Target
Job Title: {job_title}
Company: {company}
Template Type: {template_type}

## Task
Generate email templates for the specified type.
Return ONLY a valid JSON object — no markdown fences:
{{
  "templates": [
    {{
      "type": "application|follow_up|thank_you|networking",
      "subject": "Email subject line",
      "body": "Full email body with placeholder markers like [Hiring Manager Name]",
      "tips": ["1-2 tips for customizing this template"]
    }}
  ],
  "general_tips": ["3-4 general email etiquette tips for job seekers"],
  "signature_suggestion": "A professional email signature suggestion"
}}

Rules:
- Generate 2-3 templates for the requested type.
- Templates must be professional but not generic.
- Reference the candidate's actual skills and experience.
- Include specific metrics or achievements from their CV where possible.
- Keep emails concise (under 200 words each).
- Return ONLY the JSON object.
"""


async def generate_email_templates(
    cv_data: dict[str, Any],
    target_roles: list[str] | None = None,
    job_title: str = "",
    company: str = "",
    template_type: str = "application",
    email_address: str | None = None,
) -> dict[str, Any]:
    """Generate personalized email templates from CV data."""
    target_roles = target_roles or []

    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return _fallback_templates(cv_data, target_roles, job_title, company, template_type)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        email_line = f"Email: {email_address}\n" if email_address else ""

        prompt = EMAIL_PROMPT.format(
            name=cv_data.get("name", "Candidate"),
            primary_domain=cv_data.get("primary_domain", "professional"),
            seniority_level=cv_data.get("seniority_level", "mid"),
            total_years_experience=cv_data.get("total_years_experience", 0),
            skills=", ".join(cv_data.get("skills", [])[:15]),
            summary=(cv_data.get("summary", "") or "")[:300],
            target_roles=", ".join(target_roles) if target_roles else "Not specified",
            email_line=email_line,
            job_title=job_title or "General",
            company=company or "Target company",
            template_type=template_type,
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
        logger.warning("Email templates generation failed: %s", exc)
        return _fallback_templates(cv_data, target_roles, job_title, company, template_type)


def _fallback_templates(
    cv_data: dict[str, Any],
    target_roles: list[str],
    job_title: str,
    company: str,
    template_type: str,
) -> dict[str, Any]:
    """Fallback when Claude is unavailable."""
    name = cv_data.get("name", "Professional")
    domain = cv_data.get("primary_domain", "professional")
    skills = cv_data.get("skills", [])
    yoe = cv_data.get("total_years_experience", 0)

    templates_map = {
        "application": [
            {
                "type": "application",
                "subject": f"Application for {job_title or 'Open Position'} — {name}",
                "body": (
                    f"Dear [Hiring Manager Name],\n\n"
                    f"I am writing to express my interest in the {job_title or 'open'} position "
                    f"at {company or 'your company'}. With {yoe}+ years of experience in {domain} "
                    f"and strong skills in {', '.join(skills[:3]) if skills else domain}, "
                    f"I am confident I can contribute meaningfully to your team.\n\n"
                    f"[Add 1-2 specific achievements here]\n\n"
                    f"I would welcome the opportunity to discuss how my background aligns with "
                    f"your needs. I've attached my CV for your review.\n\n"
                    f"Best regards,\n{name}"
                ),
                "tips": [
                    "Replace [Hiring Manager Name] with the actual name if possible",
                    "Add a specific achievement with numbers (e.g., 'increased revenue by 30%')",
                ],
            },
            {
                "type": "application",
                "subject": f"Excited about the {job_title or 'role'} opportunity at {company or 'your company'}",
                "body": (
                    f"Hi [Hiring Manager Name],\n\n"
                    f"I recently came across the {job_title or 'open'} role at {company or 'your company'} "
                    f"and felt compelled to reach out. My {yoe}+ years in {domain}, particularly in "
                    f"{', '.join(skills[:2]) if skills else domain}, make me a strong fit.\n\n"
                    f"What excites me most about {company or 'this opportunity'} is [specific reason]. "
                    f"I'd love to share how my experience can help your team achieve its goals.\n\n"
                    f"Would you be open to a brief conversation this week?\n\n"
                    f"Cheers,\n{name}"
                ),
                "tips": [
                    "Research the company and fill in the [specific reason]",
                    "This shorter format works well for startups and tech companies",
                ],
            },
        ],
        "follow_up": [
            {
                "type": "follow_up",
                "subject": f"Following up: {job_title or 'Application'} at {company or 'Your Company'}",
                "body": (
                    f"Dear [Hiring Manager Name],\n\n"
                    f"I hope this message finds you well. I wanted to follow up on my application "
                    f"for the {job_title or 'open'} position submitted on [date].\n\n"
                    f"I remain very enthusiastic about the opportunity to bring my {domain} expertise "
                    f"to {company or 'your team'}. I'd love to discuss how my experience with "
                    f"{', '.join(skills[:2]) if skills else domain} could benefit your goals.\n\n"
                    f"Please let me know if there's any additional information I can provide.\n\n"
                    f"Best regards,\n{name}"
                ),
                "tips": [
                    "Send 1-2 weeks after your initial application",
                    "Keep it brief and restate your enthusiasm",
                ],
            },
        ],
        "thank_you": [
            {
                "type": "thank_you",
                "subject": f"Thank you — {job_title or 'Interview'} discussion",
                "body": (
                    f"Dear [Interviewer Name],\n\n"
                    f"Thank you for taking the time to discuss the {job_title or 'open'} role "
                    f"at {company or 'your company'} today. I enjoyed learning about "
                    f"[specific topic discussed] and am even more excited about the opportunity.\n\n"
                    f"Our conversation reinforced my belief that my experience in {domain} "
                    f"and skills in {', '.join(skills[:2]) if skills else domain} would be a "
                    f"strong fit for your team.\n\n"
                    f"I look forward to hearing about next steps.\n\n"
                    f"Warm regards,\n{name}"
                ),
                "tips": [
                    "Send within 24 hours of the interview",
                    "Reference a specific topic from the conversation",
                ],
            },
        ],
        "networking": [
            {
                "type": "networking",
                "subject": f"Connecting: {domain.title()} professional reaching out",
                "body": (
                    f"Hi [Name],\n\n"
                    f"I came across your profile and was impressed by your work in {domain}. "
                    f"As a {cv_data.get('seniority_level', 'mid')}-level professional with {yoe}+ years "
                    f"in {domain}, I'd love to connect and learn from your experience.\n\n"
                    f"Would you be open to a brief 15-minute chat? I'm particularly interested in "
                    f"[specific area of their work].\n\n"
                    f"Best,\n{name}"
                ),
                "tips": [
                    "Personalize the message by referencing their specific work",
                    "Keep the ask small (15-minute chat, not a job referral)",
                ],
            },
        ],
    }

    return {
        "templates": templates_map.get(template_type, templates_map["application"]),
        "general_tips": [
            "Always personalize the greeting — use the recipient's name",
            "Keep emails under 200 words for maximum impact",
            "Proofread for typos — they signal carelessness",
            "Include a clear call-to-action in every email",
        ],
        "signature_suggestion": (
            f"{name}\n{domain.title()} Professional\n"
            f"[Phone] | [Email] | [LinkedIn URL]"
        ),
    }
