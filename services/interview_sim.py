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

# ---------------------------------------------------------------------------
# Interview format definitions
# ---------------------------------------------------------------------------

INTERVIEW_FORMATS = {
    "phone": {
        "count": 5,
        "focus": (
            "Phone screening — shorter, communication-focused questions. "
            "Assess verbal clarity, enthusiasm, and quick thinking. "
            "Questions should be answerable in 1-2 minutes each."
        ),
        "criteria": "Communication clarity, concise answers, phone presence",
    },
    "video": {
        "count": 5,
        "focus": (
            "Video interview — questions with body language and presentation awareness. "
            "Include tips on visual presence. Questions should test structured thinking."
        ),
        "criteria": "Presentation, structured answers, professional demeanor, eye contact awareness",
    },
    "task": {
        "count": 4,
        "focus": (
            "Task-based/technical interview — problem-solving scenarios, case studies, "
            "and practical exercises. Focus on analytical thinking and hands-on skills."
        ),
        "criteria": "Problem decomposition, technical accuracy, thinking out loud, practical solutions",
    },
    "frontal": {
        "count": 5,
        "focus": (
            "In-person frontal interview — behavioral depth, cultural fit, leadership potential. "
            "STAR-method friendly questions. Mix of behavioral, technical, and situational."
        ),
        "criteria": "Depth of experience, cultural fit, leadership, self-awareness",
    },
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

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

## Interview Format
{interview_format}

## Task
Generate {question_count} interview questions that this candidate would likely face.

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

## Interview Format Criteria
{format_criteria}

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
    interview_type: str = "frontal",
) -> dict[str, Any]:
    """Generate interview questions for a mock interview session."""
    fmt = INTERVIEW_FORMATS.get(interview_type, INTERVIEW_FORMATS["frontal"])

    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return {"questions": _fallback_questions(cv_data, job, interview_type)}

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
            interview_format=fmt["focus"],
            question_count=fmt["count"],
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
        return {"questions": _fallback_questions(cv_data, job, interview_type)}


async def evaluate_answer(
    cv_data: dict[str, Any],
    job: dict[str, Any],
    question: dict[str, Any],
    user_answer: str,
    interview_type: str = "frontal",
) -> dict[str, Any]:
    """Evaluate a candidate's answer and provide feedback."""
    fmt = INTERVIEW_FORMATS.get(interview_type, INTERVIEW_FORMATS["frontal"])

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
            format_criteria=fmt["criteria"],
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


def _fallback_questions(
    cv_data: dict[str, Any],
    job: dict[str, Any],
    interview_type: str = "frontal",
) -> list[dict]:
    """Fallback questions when Claude is unavailable."""
    title = job.get("title", "this role")
    company = job.get("company", "the company")
    skills = cv_data.get("skills", [])
    top_skill = skills[0] if skills else "your primary skill"
    second_skill = skills[1] if len(skills) > 1 else "teamwork"

    if interview_type == "phone":
        return [
            {"question": f"Tell me briefly about yourself and why you applied for {title} at {company}.", "category": "behavioral", "what_they_look_for": "Concise self-intro, enthusiasm"},
            {"question": "What are you looking for in your next role?", "category": "behavioral", "what_they_look_for": "Clarity of goals, alignment with role"},
            {"question": f"What's your experience with {top_skill}?", "category": "technical", "what_they_look_for": "Relevant experience, communication clarity"},
            {"question": "What's your availability and salary expectations?", "category": "situational", "what_they_look_for": "Straightforward, realistic expectations"},
            {"question": "Do you have any questions about the role or company?", "category": "culture", "what_they_look_for": "Genuine curiosity, preparation"},
        ]
    elif interview_type == "video":
        return [
            {"question": f"Walk me through your background and how it led you to apply for {title}.", "category": "behavioral", "what_they_look_for": "Structured narrative, on-camera presence"},
            {"question": f"Describe a project where you demonstrated {top_skill}. What was the impact?", "category": "technical", "what_they_look_for": "Technical depth, visual engagement"},
            {"question": "Tell me about a time you led a cross-functional initiative.", "category": "situational", "what_they_look_for": "Leadership, clear communication"},
            {"question": f"Why {company}? What about our mission resonates with you?", "category": "culture", "what_they_look_for": "Research, authenticity, eye contact"},
            {"question": "How do you prioritize when you have multiple competing deadlines?", "category": "behavioral", "what_they_look_for": "Organization, composure under pressure"},
        ]
    elif interview_type == "task":
        return [
            {"question": f"Design a system architecture for a key feature related to {title}. Walk me through your approach.", "category": "technical", "what_they_look_for": "System thinking, technical breadth"},
            {"question": f"Given a bug in a {top_skill} component that only appears in production, how would you debug it?", "category": "technical", "what_they_look_for": "Debugging methodology, practical skills"},
            {"question": f"Write pseudocode for a common task in {second_skill}. Explain your trade-offs.", "category": "technical", "what_they_look_for": "Code quality, trade-off analysis"},
            {"question": "You discover a critical issue right before a release. What's your action plan?", "category": "situational", "what_they_look_for": "Decision-making under pressure, communication"},
        ]
    else:  # frontal
        return [
            {"question": f"Tell me about yourself and why you're interested in the {title} role at {company}.", "category": "behavioral", "what_they_look_for": "Clear narrative, enthusiasm, relevance to role"},
            {"question": f"Describe a challenging project where you used {top_skill}. What was the outcome?", "category": "technical", "what_they_look_for": "Technical depth, problem-solving, measurable results"},
            {"question": "Tell me about a time you had to work with a difficult stakeholder. How did you handle it?", "category": "situational", "what_they_look_for": "Communication skills, empathy, conflict resolution"},
            {"question": f"What do you know about {company}, and what excites you most about working here?", "category": "culture", "what_they_look_for": "Research effort, genuine interest, cultural alignment"},
            {"question": "Where do you see yourself in 3 years, and how does this role fit into that plan?", "category": "behavioral", "what_they_look_for": "Ambition, realistic planning, commitment"},
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
