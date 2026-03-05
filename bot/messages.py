from __future__ import annotations
"""All user-facing message strings and template functions."""

# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

WELCOME = (
    "👋 Welcome to *JobMate AI* — your AI career companion.\n\n"
    "I'll help you:\n"
    "• Tailor your CV for every role\n"
    "• Match and apply to jobs early\n"
    "• Track every application\n"
    "• Prepare you for interviews\n\n"
    "Let's get you hired. 🎯\n\n"
    "*Send me your CV* to get started — PDF, DOCX, or paste the text."
)

CV_PROCESSING = "⏳ Reading your CV... ~10 seconds."

ROLE_QUESTION = (
    "🎯 *What roles are you targeting?*\n\n"
    "Type the job title(s) you want. Be specific — it helps me match better.\n\n"
    "_Examples: Senior Product Manager, Backend Engineer, Customer Success Manager_"
)

SALARY_QUESTION = (
    "💰 *What's your minimum salary expectation?*\n\n"
    "Type an amount and currency.\n"
    "_Examples: 80000 USD · 65000 GBP · 90000 EUR_\n\n"
    "Or type *skip* if you don't have a minimum."
)

SETUP_COMPLETE = (
    "🎉 *You're all set!*\n\n"
    "Here's what happens next:\n"
    "• Every morning I'll send your top matches\n"
    "• I tailor your CV per role before applying\n"
    "• I track every application automatically\n\n"
    "Let me find your first matches now... 🔍"
)


# ---------------------------------------------------------------------------
# Dynamic templates
# ---------------------------------------------------------------------------

def cv_score_message(parsed: dict) -> str:
    score     = parsed.get("cv_score", 0)
    name      = parsed.get("name", "there")
    domain    = parsed.get("primary_domain", "your field")
    years     = parsed.get("total_years_experience", 0)
    seniority = parsed.get("seniority_level", "mid")
    skills    = parsed.get("skills", [])[:6]

    indicator = "🟢" if score >= 75 else "🟡" if score >= 55 else "🔴"

    skills_str = ", ".join(skills) if skills else "—"
    notes = parsed.get("improvement_notes", [])
    notes_str = "\n".join(f"{i}. {n}" for i, n in enumerate(notes[:3], 1))

    return (
        f"✅ CV received, {name}!\n\n"
        f"*CV Score: {score}/100 {indicator}*\n\n"
        f"I see you as a *{seniority}-level {domain}* professional "
        f"with *{years} year(s)* of experience.\n\n"
        f"*Top skills detected:* {skills_str}\n\n"
        f"*3 things I'll improve per application:*\n{notes_str}\n\n"
        "Now let's set your job search preferences 👇"
    )


def preferences_summary(prefs: dict) -> str:
    def fmt(lst: list, default: str = "Any") -> str:
        return ", ".join(lst).title() if lst else default

    return (
        "📋 *Your Job Search Profile*\n\n"
        f"🎯 *Roles:* {fmt(prefs.get('roles', []))}\n"
        f"📍 *Location:* {fmt(prefs.get('locations', []))}\n"
        f"💰 *Min Salary:* {prefs.get('salary_display', 'Not specified')}\n"
        f"🏢 *Industries:* {fmt(prefs.get('industries', []))}\n"
        f"📊 *Company Size:* {fmt(prefs.get('company_sizes', []))}\n"
        f"💼 *Employment:* {fmt(prefs.get('employment_types', []))}\n\n"
        "Does this look right?"
    )


def matches_message(matches: list[dict]) -> str:
    if not matches:
        return (
            "😔 No matches found for your current filters.\n\n"
            "Try broadening your search with /settings"
        )

    header = f"🔍 *{len(matches)} match{'es' if len(matches) != 1 else ''} for you:*\n\n"
    lines = []
    for i, job in enumerate(matches, 1):
        sal = ""
        if job.get("salary_min") and job.get("salary_max"):
            sal = f" · {job['salary_currency']} {job['salary_min']:,}–{job['salary_max']:,}"
        remote_tag = " 🌍" if job.get("remote") else ""
        lines.append(
            f"*{i}. {job['title']} @ {job['company']}*{remote_tag}\n"
            f"📍 {job['location']}{sal}\n"
            f"🎯 {job['match_score']}% match · _{job['match_reason']}_\n"
        )
    return header + "\n".join(lines)


def pipeline_message(applications: list[dict]) -> str:
    if not applications:
        return "📭 No applications yet.\n\nUse /matches to find jobs and start applying!"

    STATUS_EMOJI = {
        "applied":   "📤",
        "viewed":    "👀",
        "contacted": "💬",
        "interview": "🎯",
        "offer":     "🎉",
        "rejected":  "❌",
        "withdrawn": "🗑️",
    }

    lines = [f"📊 *Application Pipeline ({len(applications)} total)*\n"]
    for app in applications:
        emoji = STATUS_EMOJI.get(app["status"], "📤")
        lines.append(
            f"{emoji} *{app['job_title']}* @ {app['company']}\n"
            f"   {app['status'].title()} · Applied {app['submitted_at']}\n"
        )
    return "\n".join(lines)


def morning_checkin_message(streak: int, matches: list[dict]) -> str:
    streak_line = f"🔥 {streak}-day streak!" if streak >= 3 else f"Day {streak} of your job search."
    msg = f"Good morning! ☀️ {streak_line}\n\n"

    if matches:
        msg += f"I found *{len(matches)} new match{'es' if len(matches) != 1 else ''}* for you:\n\n"
        for i, job in enumerate(matches[:3], 1):
            remote = " (Remote)" if job.get("remote") else ""
            msg += f"*{i}.* {job['title']} @ {job['company']}{remote} — {job['match_score']}% match\n"
        msg += "\nReady to apply? Use /matches to review and apply."
    else:
        msg += (
            "No new matches today matching your criteria. I'll keep scanning.\n\n"
            "Want to broaden your search? Use /settings"
        )
    return msg
