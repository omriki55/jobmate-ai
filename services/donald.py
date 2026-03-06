"""
Donald — AI Career Advisor chat engine.

Conversational layer that wraps all existing services behind a warm,
supportive career advisor persona.  Donald understands free-text input,
provides emotional support, and triggers existing service actions when needed.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)


def _get_client():
    """Lazy client creation — avoids module-level import timing issues."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return None
    from anthropic import AsyncAnthropic
    return AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# ---------------------------------------------------------------------------
# System prompt — Donald's personality + available actions
# ---------------------------------------------------------------------------

DONALD_SYSTEM = """\
You are **Donald**, a warm, experienced career advisor who genuinely cares \
about the people you help.  You speak in a friendly, direct way — like a \
trusted mentor over coffee.  You mix emotional support with practical advice.

## About you
- You're positive but honest — you don't sugarcoat, but you never crush hope.
- You celebrate small wins enthusiastically.
- When someone is stressed or discouraged, you empathise FIRST, then offer steps.
- You keep messages concise (2-4 sentences usually, up to a short paragraph for \
  emotional moments).  Never write walls of text.
- You naturally weave in the user's data when relevant.

## User context
{user_context}

## Actions you can trigger
When the user's intent clearly maps to one of these, include the tag AT THE \
VERY END of your message on its own line.  Only use ONE tag per message.  \
If the conversation is just chatting / emotional support, do NOT include a tag.

[ACTION:improve_cv] — generate detailed CV improvement plan
[ACTION:linkedin] — scan & optimise LinkedIn profile
[ACTION:matches] — show top job matches
[ACTION:search_jobs:<keywords>] — search jobs by keywords (replace <keywords>)
[ACTION:dashboard] — show application dashboard & stats
[ACTION:pipeline] — show application pipeline
[ACTION:coach] — deep emotional coaching session
[ACTION:email_templates] — generate email templates
[ACTION:interview_prep] — interview preparation tips
[ACTION:headhunters] — find recruiters in their field
[ACTION:calendar] — scheduling & interview prep calendar
[ACTION:refresh_jobs] — scrape fresh job listings

## Rules
- Always respond in the SAME LANGUAGE the user writes in.
- Be concise.  Chat, don't lecture.
- If someone greets you, greet back warmly and ask how you can help today.
- If you don't know something, say so honestly.
- Never fabricate job listings or company data.
"""


def _build_user_context(
    cv_data: dict | None,
    stats: dict | None,
    prefs: dict | None,
) -> str:
    """Build a concise summary of the user's situation for Donald's system prompt."""
    parts: list[str] = []

    if cv_data:
        name = cv_data.get("name", "")
        score = cv_data.get("cv_score", "?")
        domain = cv_data.get("primary_domain", "")
        seniority = cv_data.get("seniority_level", "")
        skills = ", ".join(cv_data.get("skills", [])[:6])
        yrs = cv_data.get("total_years_experience", "?")
        parts.append(
            f"Name: {name} | CV score: {score}/100 | "
            f"{seniority} {domain} | {yrs}yr exp | Skills: {skills}"
        )
    else:
        parts.append("No CV uploaded yet.")

    if stats:
        parts.append(
            f"Applications: {stats.get('total_apps', 0)} | "
            f"Response rate: {stats.get('response_rate', 0)}% | "
            f"Interviews: {stats.get('interviews', 0)} | "
            f"Rejections: {stats.get('rejections', 0)} | "
            f"Streak: {stats.get('streak', 0)} days"
        )

    if prefs:
        roles = ", ".join(prefs.get("target_roles", [])[:3]) or "not set"
        locs = ", ".join(prefs.get("locations", [])[:3]) or "not set"
        parts.append(f"Target roles: {roles} | Locations: {locs}")

    return "\n".join(parts) if parts else "New user — no data yet."


def _parse_action(text: str) -> tuple[str, str | None, str | None]:
    """
    Strip [ACTION:...] tag from Donald's response.
    Returns (clean_message, action_name, action_arg).
    """
    import re
    m = re.search(r"\[ACTION:(\w+)(?::([^\]]*))?\]\s*$", text)
    if not m:
        return text.strip(), None, None
    clean = text[: m.start()].strip()
    return clean, m.group(1), m.group(2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def chat_with_donald(
    user_message: str,
    cv_data: dict | None = None,
    stats: dict | None = None,
    prefs: dict | None = None,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Send a message to Donald and get a conversational reply.

    Returns::

        {
            "message": "Donald's text reply",
            "action":  "improve_cv" | None,
            "action_arg": "optional arg" | None,
        }
    """
    client = _get_client()
    if not client:
        logger.warning("Donald: no client (ANTHROPIC_API_KEY=%s)",
                        repr(ANTHROPIC_API_KEY[:10]) if ANTHROPIC_API_KEY else "empty")
        return _fallback(user_message)

    ctx = _build_user_context(cv_data, stats, prefs)
    system = DONALD_SYSTEM.replace("{user_context}", ctx)

    # Build messages list with recent history (keep last 10 turns)
    messages: list[dict] = []
    if history:
        for h in history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        resp = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=system,
            messages=messages,
        )
        raw = resp.content[0].text.strip()
        message, action, action_arg = _parse_action(raw)
        return {"message": message, "action": action, "action_arg": action_arg}

    except Exception as exc:
        logger.error("Donald chat failed: %s — %s", type(exc).__name__, exc)
        return _fallback(user_message)


def _fallback(user_message: str) -> dict[str, Any]:
    """Fallback when Claude is unavailable."""
    low = user_message.lower()
    if any(w in low for w in ("cv", "resume", "improve")):
        return {
            "message": "Let me pull up your CV improvement plan!",
            "action": "improve_cv",
            "action_arg": None,
        }
    if "linkedin" in low:
        return {
            "message": "Let's optimise your LinkedIn profile!",
            "action": "linkedin",
            "action_arg": None,
        }
    if any(w in low for w in ("match", "job")):
        return {
            "message": "Here are your top job matches:",
            "action": "matches",
            "action_arg": None,
        }
    return {
        "message": (
            "Hey! I'm Donald, your career advisor. I'm having a bit of "
            "trouble connecting right now, but I'm still here for you. "
            "Try asking me about your CV, LinkedIn, job matches, or "
            "just tell me how you're feeling today."
        ),
        "action": None,
        "action_arg": None,
    }
