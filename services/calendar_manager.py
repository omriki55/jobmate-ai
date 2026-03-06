"""
Calendar Manager Service — generates interview scheduling advice.

Given CV data and job info, generates interview prep schedules,
time-blocking suggestions, and follow-up reminder schedules.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

CALENDAR_PROMPT = """\
You are an expert career strategist and time management coach.
Given a candidate's profile, generate scheduling advice for their job search.

## Candidate Profile
Name: {name}
Domain: {primary_domain}
Seniority: {seniority_level}
Target Roles: {target_roles}
{calendar_line}
## Context
Job Title: {job_title}
Company: {company}
Interview Date: {interview_date}

## Task
Generate comprehensive scheduling and preparation advice.
Return ONLY a valid JSON object — no markdown fences:
{{
  "prep_schedule": [
    {{
      "day_offset": -3,
      "title": "Research phase",
      "tasks": ["Task 1", "Task 2"],
      "duration_minutes": 60
    }}
  ],
  "time_blocks": [
    {{
      "block": "Morning (9-11am)",
      "activity": "Active job searching and applications",
      "rationale": "Why this time slot works best"
    }}
  ],
  "follow_up_reminders": [
    {{
      "day_offset": 1,
      "action": "Send thank-you email",
      "template": "Brief template or guidance"
    }}
  ],
  "weekly_schedule": {{
    "monday": "Focus area for Monday",
    "tuesday": "Focus area for Tuesday",
    "wednesday": "Focus area for Wednesday",
    "thursday": "Focus area for Thursday",
    "friday": "Focus area for Friday"
  }},
  "tips": ["3-4 time management tips for job seekers"]
}}

Rules:
- day_offset is relative to the interview date (negative = before, positive = after).
- If no interview date, generate a general job search weekly schedule.
- Be specific to their domain and seniority level.
- Time blocks should account for realistic daily routines.
- Return ONLY the JSON object.
"""


async def generate_calendar_advice(
    cv_data: dict[str, Any],
    target_roles: list[str] | None = None,
    job_title: str = "",
    company: str = "",
    interview_date: str | None = None,
    calendar_url: str | None = None,
) -> dict[str, Any]:
    """Generate calendar/scheduling advice from CV data."""
    target_roles = target_roles or []

    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return _fallback_advice(cv_data, target_roles, job_title, company, interview_date)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        calendar_line = f"Calendar: {calendar_url}\n" if calendar_url else ""

        prompt = CALENDAR_PROMPT.format(
            name=cv_data.get("name", "Candidate"),
            primary_domain=cv_data.get("primary_domain", "professional"),
            seniority_level=cv_data.get("seniority_level", "mid"),
            target_roles=", ".join(target_roles) if target_roles else "Not specified",
            calendar_line=calendar_line,
            job_title=job_title or "General",
            company=company or "Target company",
            interview_date=interview_date or "Not scheduled yet",
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
        logger.warning("Calendar advice generation failed: %s", exc)
        return _fallback_advice(cv_data, target_roles, job_title, company, interview_date)


def _fallback_advice(
    cv_data: dict[str, Any],
    target_roles: list[str],
    job_title: str,
    company: str,
    interview_date: str | None,
) -> dict[str, Any]:
    """Fallback when Claude is unavailable."""
    domain = cv_data.get("primary_domain", "professional")
    seniority = cv_data.get("seniority_level", "mid")

    prep_schedule = [
        {
            "day_offset": -3,
            "title": "Research phase",
            "tasks": [
                f"Research {company or 'the company'} culture and recent news",
                "Review the job description and match your skills",
            ],
            "duration_minutes": 60,
        },
        {
            "day_offset": -2,
            "title": "Practice phase",
            "tasks": [
                "Practice STAR-method answers for behavioral questions",
                f"Review your {domain} technical fundamentals",
            ],
            "duration_minutes": 90,
        },
        {
            "day_offset": -1,
            "title": "Final prep",
            "tasks": [
                "Prepare 3-5 questions to ask the interviewer",
                "Lay out interview outfit, test tech setup if virtual",
                "Get a good night's sleep",
            ],
            "duration_minutes": 45,
        },
        {
            "day_offset": 0,
            "title": "Interview day",
            "tasks": [
                "Review your notes 30 minutes before",
                "Arrive/log in 10 minutes early",
                "Bring copies of your CV",
            ],
            "duration_minutes": 30,
        },
    ]

    return {
        "prep_schedule": prep_schedule if interview_date else prep_schedule[:2],
        "time_blocks": [
            {
                "block": "Morning (9-11am)",
                "activity": "Active job searching and applications",
                "rationale": "Peak energy for focused work; companies review morning applications first",
            },
            {
                "block": "Midday (11am-1pm)",
                "activity": "Networking and outreach",
                "rationale": "Good time to send LinkedIn messages and follow-up emails",
            },
            {
                "block": "Afternoon (2-4pm)",
                "activity": "Skill building and interview prep",
                "rationale": "Use post-lunch energy dip for learning rather than high-stakes tasks",
            },
            {
                "block": "Evening (7-8pm)",
                "activity": "CV tailoring and research",
                "rationale": "Quieter time for focused writing and company research",
            },
        ],
        "follow_up_reminders": [
            {
                "day_offset": 1,
                "action": "Send thank-you email",
                "template": f"Thank the interviewer for the {job_title or 'role'} discussion, reference a specific topic",
            },
            {
                "day_offset": 7,
                "action": "Follow-up if no response",
                "template": "Brief check-in expressing continued interest",
            },
            {
                "day_offset": 14,
                "action": "Second follow-up or move on",
                "template": "Final follow-up; begin focusing on other opportunities",
            },
        ],
        "weekly_schedule": {
            "monday": "Review new job postings, submit 3-5 targeted applications",
            "tuesday": "Networking: reach out to 2-3 contacts, attend virtual events",
            "wednesday": "Skill building: online courses, portfolio updates",
            "thursday": "Interview prep: practice questions, research companies",
            "friday": "Follow-ups: check application statuses, send thank-you notes",
        },
        "tips": [
            f"Block 2-3 hours daily for your job search — treat it like a {seniority}-level project",
            "Use the Pomodoro technique: 25 minutes focused work, 5 minutes break",
            "Track all applications in one place to avoid duplicates",
            "Schedule networking calls early in the week when people are most responsive",
        ],
    }
