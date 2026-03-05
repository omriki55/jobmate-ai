"""
Interview Simulation Service — multi-turn mock interviews.

Generates interview questions one at a time, evaluates user answers,
provides feedback and improved answer suggestions.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

START_PROMPT = """\
You are a senior interviewer at {company} conducting a mock interview for a {job_title} position.

## Candidate Profile
Name: {name}
Domain: {primary_domain}
Seniority: {seniority_level}
Years of experience: {total_years_experience}
Skills: {skills}

## Company Context
{company_context}

## Task
Generate 5 interview questions that this candidate would likely face in a real interview
for this specific role at this company. Mix behavioral, technical, and situational questions.

Return ONLY a valid JSON array — no markdown fences:
[
  {{
    "question": "The interview question",
    "category": "behavioral|technical|situational|culture",
    "what_they_look_for": "Brief note on what interviewers evaluate with this question"
  }}
]
"""

EVALUATE_PROMPT = """\
You are a senior interviewer at {company} evaluating a candidate's answer.

## Context
Role: {job_title}
Question: {question}
Category: {category}
What interviewers look for: {what_they_look_for}

## Candidate's Answer
{answer}

## Candidate Profile
Domain: {primary_domain}, {seniority_level} level, {total_years_experience} years experience

## Task
Evaluate the answer and provide constructive feedback.

Return ONLY a valid JSON object — no markdown fences:
{{
  "score": 7,
  "feedback": "2-3 sentences of specific, constructive feedback",
  "strengths": ["What they did well"],
  "improvements": ["What could be better"],
  "improved_answer": "A model answer (3-4 sentences) showing how to improve"
}}

Rules:
- score is 1-10
- Be encouraging but honest
- Reference the specific role and company
- improved_answer should be realistic, not perfect
"""


async def start_simulation(
    cv_data: dict[str, Any],
    job: dict[str, Any],
    company_context: dict[str, Any],
) -> dict[str, Any]:
    """Generate 5 interview questions for a mock interview session."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return {"questions": _fallback_questions(cv_data, job)}

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        context_str = "\n".join(
            f"- {k}: {v}" for k, v in company_context.items()
            if isinstance(v, str) and v
        )

        prompt = START_PROMPT.format(
            company=job.get("company", "the company"),
            job_title=job.get("title", "this role"),
            name=cv_data.get("name", "Candidate"),
            primary_domain=cv_data.get("primary_domain", "your field"),
            seniority_level=cv_data.get("seniority_level", "mid"),
            total_years_experience=cv_data.get("total_years_experience", 0),
            skills=", ".join(cv_data.get("skills", [])[:12]),
            company_context=context_str or "No additional context available.",
        )

        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]
        questions = json.loads(raw.strip())
        return {"questions": questions}

    except Exception as exc:
        logger.warning("Interview sim start failed: %s", exc)
        return {"questions": _fallback_questions(cv_data, job)}


async def evaluate_answer(
    cv_data: dict[str, Any],
    job: dict[str, Any],
    question: dict[str, Any],
    user_answer: str,
) -> dict[str, Any]:
    """Evaluate a candidate's answer and provide feedback."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return _fallback_evaluation(user_answer)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        prompt = EVALUATE_PROMPT.format(
            company=job.get("company", "the company"),
            job_title=job.get("title", "this role"),
            question=question.get("question", ""),
            category=question.get("category", "general"),
            what_they_look_for=question.get("what_they_look_for", ""),
            answer=user_answer[:1500],
            primary_domain=cv_data.get("primary_domain", "your field"),
            seniority_level=cv_data.get("seniority_level", "mid"),
            total_years_experience=cv_data.get("total_years_experience", 0),
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
        return json.loads(raw.strip())

    except Exception as exc:
        logger.warning("Interview sim evaluation failed: %s", exc)
        return _fallback_evaluation(user_answer)


def _fallback_questions(cv_data: dict[str, Any], job: dict[str, Any]) -> list[dict]:
    """Fallback questions when Claude is unavailable."""
    title = job.get("title", "this role")
    company = job.get("company", "the company")
    skills = cv_data.get("skills", [])
    top_skill = skills[0] if skills else "your primary skill"

    return [
        {
            "question": f"Tell me about yourself and why you're interested in the {title} role at {company}.",
            "category": "behavioral",
            "what_they_look_for": "Clear narrative, enthusiasm, relevance to role",
        },
        {
            "question": f"Describe a challenging project where you used {top_skill}. What was the outcome?",
            "category": "technical",
            "what_they_look_for": "Technical depth, problem-solving, measurable results",
        },
        {
            "question": "Tell me about a time you had to work with a difficult stakeholder. How did you handle it?",
            "category": "situational",
            "what_they_look_for": "Communication skills, empathy, conflict resolution",
        },
        {
            "question": f"What do you know about {company}, and what excites you most about working here?",
            "category": "culture",
            "what_they_look_for": "Research effort, genuine interest, cultural alignment",
        },
        {
            "question": "Where do you see yourself in 3 years, and how does this role fit into that plan?",
            "category": "behavioral",
            "what_they_look_for": "Ambition, realistic planning, commitment",
        },
    ]


def _fallback_evaluation(user_answer: str) -> dict[str, Any]:
    """Fallback evaluation when Claude is unavailable."""
    word_count = len(user_answer.split())
    score = min(7, max(3, word_count // 10 + 3))
    return {
        "score": score,
        "feedback": (
            "Good start! Try to structure your answer using the STAR method "
            "(Situation, Task, Action, Result) for behavioral questions, "
            "and include specific metrics or outcomes where possible."
        ),
        "strengths": ["You provided a response — that's the first step!"],
        "improvements": [
            "Add specific examples from your experience",
            "Include quantified results (%, $, time saved)",
            "Keep answers to 2-3 minutes in a real interview",
        ],
        "improved_answer": (
            "A strong answer would start with a brief context (1 sentence), "
            "describe your specific actions (2-3 sentences), and end with "
            "a measurable result. Practice this structure with your real experiences."
        ),
    }
