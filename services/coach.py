"""
Career Coach Service — emotional support and motivation.

Context-aware coaching that references the user's actual pipeline data
to provide specific, empathetic encouragement during the job search.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

COACH_PROMPT = """\
You are a warm, empathetic career coach embedded in a job search app called JobMate.
You combine emotional support with practical advice.

## User's Current Status
- Applications submitted: {total_apps}
- Response rate: {response_rate}%
- Current streak: {streak} days active
- Interviews scheduled: {interviews}
- Rejections received: {rejections}
- Days since starting: {days_active}

## User's Message
{user_message}

## Your Task
Respond as a supportive career coach. Be warm but not condescending.
Reference their actual data to make it personal.

Return ONLY a valid JSON object:
{{
  "message": "Your 2-3 paragraph coaching response. Be specific and encouraging.",
  "action_items": ["1-3 concrete next steps they can take today"],
  "affirmation": "A brief, genuine affirmation (1 sentence)",
  "mood": "encouraging|celebratory|empathetic|motivating"
}}

Rules:
- If they're struggling (low response rate, many rejections), be empathetic FIRST, then practical.
- If they're doing well (active streak, interviews), celebrate and build momentum.
- Never be dismissive of their feelings.
- Action items must be specific and achievable TODAY.
- Keep the message under 200 words.
- Return ONLY the JSON object.
"""

PROACTIVE_PROMPT = """\
You are a warm, empathetic career coach. Generate a brief, proactive check-in
for a job seeker based on their current status.

## User's Status
- Applications: {total_apps}
- Response rate: {response_rate}%
- Streak: {streak} days
- Rejections: {rejections}
- Interviews: {interviews}

Return ONLY a valid JSON object:
{{
  "message": "1-2 paragraph proactive check-in. Be warm and specific to their data.",
  "action_items": ["1-2 suggested actions for today"],
  "affirmation": "A brief genuine affirmation",
  "mood": "encouraging|celebratory|empathetic|motivating"
}}
"""


async def get_coaching_message(
    user_stats: dict[str, Any],
    user_message: str = "",
) -> dict[str, Any]:
    """Generate a personalized coaching response."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return _fallback_coaching(user_stats, user_message)

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        if user_message.strip():
            prompt = COACH_PROMPT.format(
                total_apps=user_stats.get("total_apps", 0),
                response_rate=user_stats.get("response_rate", 0),
                streak=user_stats.get("streak", 0),
                interviews=user_stats.get("interviews", 0),
                rejections=user_stats.get("rejections", 0),
                days_active=user_stats.get("days_active", 0),
                user_message=user_message[:500],
            )
        else:
            prompt = PROACTIVE_PROMPT.format(
                total_apps=user_stats.get("total_apps", 0),
                response_rate=user_stats.get("response_rate", 0),
                streak=user_stats.get("streak", 0),
                rejections=user_stats.get("rejections", 0),
                interviews=user_stats.get("interviews", 0),
            )

        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
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
        logger.warning("Coach response failed: %s", exc)
        return _fallback_coaching(user_stats, user_message)


def _fallback_coaching(
    user_stats: dict[str, Any],
    user_message: str = "",
) -> dict[str, Any]:
    """Contextual fallback when Claude is unavailable."""
    total = user_stats.get("total_apps", 0)
    streak = user_stats.get("streak", 0)
    rejections = user_stats.get("rejections", 0)
    interviews = user_stats.get("interviews", 0)

    # Determine mood and message based on data
    if interviews > 0:
        mood = "celebratory"
        message = (
            f"You have {interviews} interview{'s' if interviews > 1 else ''} lined up — "
            f"that's amazing progress! Out of {total} applications, you're getting real traction. "
            f"Focus your energy on preparation for these conversations. Each interview is a "
            f"two-way street — you're evaluating them too."
        )
        affirmation = "You've earned these interviews through your hard work."
        actions = [
            "Research each company's recent news and achievements",
            "Practice your 'Tell me about yourself' answer out loud",
            "Prepare 3 thoughtful questions for your interviewer",
        ]
    elif rejections > 2 and total > 0:
        mood = "empathetic"
        message = (
            f"I know {rejections} rejections can feel discouraging — that's completely normal "
            f"and valid. But here's the thing: you've sent {total} applications, which shows "
            f"real determination. Every 'no' gets you closer to the right 'yes'. "
            f"The average job search takes 3-6 months. You're building momentum."
        )
        affirmation = "Your persistence is your superpower. Keep going."
        actions = [
            "Review and update your CV with fresh keywords from recent job posts",
            "Reach out to one person in your network today for a coffee chat",
            "Take a 30-minute break to do something you enjoy — you deserve it",
        ]
    elif streak > 3:
        mood = "motivating"
        message = (
            f"A {streak}-day streak — you're building real momentum! Consistency is "
            f"what separates successful job seekers from the rest. You've submitted "
            f"{total} application{'s' if total != 1 else ''} so far. Keep this energy going "
            f"and the results will follow."
        )
        affirmation = f"{streak} days of consistency shows incredible discipline."
        actions = [
            "Apply to 2-3 more roles today to maintain your momentum",
            "Update your LinkedIn status to signal you're actively looking",
        ]
    else:
        mood = "encouraging"
        message = (
            f"Every expert was once a beginner. You've taken {total} step{'s' if total != 1 else ''} "
            f"in your job search journey so far. The key is to keep showing up consistently. "
            f"Set a small goal for today — even one application or one networking message counts."
        )
        affirmation = "Starting is the hardest part, and you've already done that."
        actions = [
            "Browse today's job matches and apply to your top pick",
            "Set a daily goal: 2 applications per day is a great pace",
            "Use the interview prep tool to build your confidence",
        ]

    return {
        "message": message,
        "action_items": actions,
        "affirmation": affirmation,
        "mood": mood,
    }


# ---------------------------------------------------------------------------
# Daily motivation — curated tips, quotes, and videos
# ---------------------------------------------------------------------------

MOTIVATION_VIDEOS = [
    {"url": "https://www.youtube.com/watch?v=Ks-_Mh1QhMc", "title": "The Power of Believing You Can Improve — Carol Dweck"},
    {"url": "https://www.youtube.com/watch?v=hER0Qp6QJNU", "title": "The Secret to Getting a Job — Mark Leruste"},
    {"url": "https://www.youtube.com/watch?v=PYj8Iq3FwuE", "title": "How to Find a Job You Love — Scott Dinsmore"},
    {"url": "https://www.youtube.com/watch?v=u4ZoJKF_VuA", "title": "Stop Searching for Your Passion — Terri Trespicio"},
    {"url": "https://www.youtube.com/watch?v=iCvmsMzlF7o", "title": "The Surprising Habits of Original Thinkers — Adam Grant"},
    {"url": "https://www.youtube.com/watch?v=H14bBuluwB8", "title": "Grit: The Power of Passion and Perseverance — Angela Duckworth"},
    {"url": "https://www.youtube.com/watch?v=sF6pkBMnS-E", "title": "What Makes a Great Leader — Roselinde Torres"},
    {"url": "https://www.youtube.com/watch?v=RyTQ5-SQYTo", "title": "How to Speak So That People Want to Listen — Julian Treasure"},
    {"url": "https://www.youtube.com/watch?v=arj7oStGLkU", "title": "How Great Leaders Inspire Action — Simon Sinek"},
    {"url": "https://www.youtube.com/watch?v=pN34FNbOKXc", "title": "How to Get Your Brain to Focus — Chris Bailey"},
    {"url": "https://www.youtube.com/watch?v=eIho2S0ZahI", "title": "How to Build Your Creative Confidence — David Kelley"},
    {"url": "https://www.youtube.com/watch?v=w-HYZv6HzAs", "title": "The Happy Secret to Better Work — Shawn Achor"},
    {"url": "https://www.youtube.com/watch?v=Lp7E973zozc", "title": "The Skill of Self Confidence — Dr. Ivan Joseph"},
    {"url": "https://www.youtube.com/watch?v=xO7vp7aGxcM", "title": "Why You Will Fail to Have a Great Career — Larry Smith"},
    {"url": "https://www.youtube.com/watch?v=8KkKuTCFvzI", "title": "10 Ways to Have a Better Conversation — Celeste Headlee"},
    {"url": "https://www.youtube.com/watch?v=vKhGnFkiGCk", "title": "Why the Best Hire Might Not Have the Perfect Resume — Regina Hartley"},
    {"url": "https://www.youtube.com/watch?v=TWlxMDLq0Uw", "title": "The Power of Vulnerability — Brene Brown"},
    {"url": "https://www.youtube.com/watch?v=zLYECIjmnQs", "title": "Why We Do What We Do — Tony Robbins"},
    {"url": "https://www.youtube.com/watch?v=UF8uR6Z6KLc", "title": "The Power of Introverts — Susan Cain"},
    {"url": "https://www.youtube.com/watch?v=5MgBikgcWnY", "title": "Try Something New for 30 Days — Matt Cutts"},
]

TIPS_BY_STAGE = {
    "early": [
        "Focus on quality over quantity in your first applications",
        "Set up job alerts on LinkedIn and Indeed for your target roles",
        "Ask a friend to review your CV before sending it out",
        "Tailor each application — generic CVs get filtered out",
        "Update your LinkedIn headline to signal you're open to opportunities",
        "Research 3 companies you'd love to work for and follow them",
        "Practice your elevator pitch in front of a mirror",
    ],
    "active": [
        "Follow up on applications after 1 week with a brief email",
        "Schedule informational interviews to expand your network",
        "Keep a spreadsheet of applications, contacts, and follow-ups",
        "Prepare a list of questions to ask interviewers",
        "Join industry Slack communities or Discord servers",
        "Post an update on LinkedIn about what you're looking for",
        "Set a daily routine: apply in the morning, network in the afternoon",
    ],
    "intensive": [
        "Take breaks to avoid burnout — your wellbeing matters",
        "Review and refine your approach based on response patterns",
        "Ask for feedback from recruiters who passed on you",
        "Consider broadening your search to adjacent roles",
        "Practice mock interviews with a friend or online tool",
        "Celebrate small wins — every interview is progress",
        "Remember: most job searches take 3-6 months. You're doing fine.",
    ],
}

QUOTES = [
    "The only way to do great work is to love what you do. — Steve Jobs",
    "Success is not final, failure is not fatal. It is the courage to continue that counts. — Winston Churchill",
    "Your time is limited, don't waste it living someone else's life. — Steve Jobs",
    "The future belongs to those who believe in the beauty of their dreams. — Eleanor Roosevelt",
    "It does not matter how slowly you go as long as you do not stop. — Confucius",
    "Believe you can and you're halfway there. — Theodore Roosevelt",
    "Every expert was once a beginner. — Helen Hayes",
    "The best time to plant a tree was 20 years ago. The second best time is now. — Chinese Proverb",
    "Don't watch the clock; do what it does. Keep going. — Sam Levenson",
    "Opportunities don't happen. You create them. — Chris Grosser",
    "The secret of getting ahead is getting started. — Mark Twain",
    "I have not failed. I've just found 10,000 ways that won't work. — Thomas Edison",
    "What lies behind us and what lies before us are tiny matters compared to what lies within us. — Ralph Waldo Emerson",
    "Hard work beats talent when talent doesn't work hard. — Tim Notke",
    "The only impossible journey is the one you never begin. — Tony Robbins",
    "You miss 100% of the shots you don't take. — Wayne Gretzky",
    "Courage is not the absence of fear, but the triumph over it. — Nelson Mandela",
    "Everything you've ever wanted is on the other side of fear. — George Addair",
    "The best revenge is massive success. — Frank Sinatra",
    "Act as if what you do makes a difference. It does. — William James",
]


def get_daily_motivation(user_stats: dict[str, Any]) -> dict[str, Any]:
    """Return a daily motivation package: tip, quote, and video link."""
    from datetime import datetime
    day = datetime.utcnow().timetuple().tm_yday

    total_apps = user_stats.get("total_apps", 0)
    if total_apps <= 5:
        stage = "early"
    elif total_apps <= 20:
        stage = "active"
    else:
        stage = "intensive"

    tips = TIPS_BY_STAGE[stage]
    tip = tips[day % len(tips)]
    video = MOTIVATION_VIDEOS[day % len(MOTIVATION_VIDEOS)]
    quote = QUOTES[(day + 7) % len(QUOTES)]

    return {
        "tip": tip,
        "quote": quote,
        "video_url": video["url"],
        "video_title": video["title"],
        "stage": stage,
    }
