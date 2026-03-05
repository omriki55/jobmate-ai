"""
Standalone command handlers active once the user is in ACTIVE state.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from db.database import AsyncSessionLocal
from db.models import Application, CV, Job, User, UserPreferences
from services.job_match import get_top_matches
from bot.keyboards import apply_matches_keyboard
from bot.messages import matches_message, pipeline_message
from sqlalchemy import select

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "🤖 *JobMate AI — Commands*\n\n"
    "*Job Search*\n"
    "/matches — Today's job matches\n"
    "/pipeline — Your application tracker\n"
    "/stats — Search statistics\n\n"
    "*Settings*\n"
    "/settings — View & edit preferences\n"
    "/cv — Re-upload your CV\n\n"
    "*Help*\n"
    "/help — This message\n"
    "/start — Restart onboarding\n"
)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def matches_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
        user_result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_result.scalar_one_or_none()

        if not user or user.state != "ACTIVE":
            await update.message.reply_text("Please complete setup first — type /start")
            return

        cv_result = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_result.scalar_one_or_none()
        cv_skills = cv.parsed_data.get("skills", []) if cv and cv.parsed_data else []

        pref_result = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = pref_result.scalar_one_or_none()
        preferences = {}
        if prefs:
            preferences = {
                "locations":    prefs.locations or [],
                "min_salary":   prefs.min_salary,
                "industries":   prefs.industries or [],
                "company_sizes": prefs.company_sizes or [],
            }

    matches = get_top_matches(cv_skills, preferences, limit=5, threshold=50)
    await update.message.reply_text(
        matches_message(matches),
        parse_mode="Markdown",
        reply_markup=apply_matches_keyboard(matches) if matches else None,
    )


async def pipeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
        user_result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_result.scalar_one_or_none()

        if not user:
            await update.message.reply_text("Please complete setup first — type /start")
            return

        apps_result = await db.execute(
            select(Application, Job)
            .join(Job, Application.job_id == Job.id)
            .where(Application.user_id == user.id)
            .order_by(Application.submitted_at.desc())
        )
        rows = apps_result.all()

    applications = [
        {
            "job_title":    job.title,
            "company":      job.company,
            "status":       app.status,
            "submitted_at": app.submitted_at.strftime("%b %d"),
        }
        for app, job in rows
    ]
    await update.message.reply_text(pipeline_message(applications), parse_mode="Markdown")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
        user_result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_result.scalar_one_or_none()

        if not user:
            await update.message.reply_text("Please complete setup first — type /start")
            return

        apps_result = await db.execute(
            select(Application).where(Application.user_id == user.id)
        )
        apps = apps_result.scalars().all()

    total = len(apps)
    if total == 0:
        await update.message.reply_text(
            "No applications yet.\n\nUse /matches to get started!"
        )
        return

    by_status: dict[str, int] = {}
    for app in apps:
        by_status[app.status] = by_status.get(app.status, 0) + 1

    interviews  = by_status.get("interview", 0) + by_status.get("offer", 0)
    pending     = by_status.get("applied", 0)
    responded   = total - pending
    resp_rate   = round(responded / total * 100) if total else 0
    int_rate    = round(interviews / total * 100) if total else 0

    STATUS_EMOJI = {
        "applied": "📤", "viewed": "👀", "contacted": "💬",
        "interview": "🎯", "offer": "🎉", "rejected": "❌", "withdrawn": "🗑️",
    }
    breakdown = "\n".join(
        f"{STATUS_EMOJI.get(s, '•')} {s.title()}: {c}"
        for s, c in by_status.items()
    )

    msg = (
        f"📊 *Your Job Search Stats*\n\n"
        f"📤 Total Applications: *{total}*\n"
        f"👀 Response Rate: *{resp_rate}%*\n"
        f"🎯 Interview Rate: *{int_rate}%*\n"
        f"🔥 Current Streak: *{user.streak_days} days*\n\n"
        f"*By Status:*\n{breakdown}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
        user_result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_result.scalar_one_or_none()

        if not user:
            await update.message.reply_text("Please complete setup first — type /start")
            return

        pref_result = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = pref_result.scalar_one_or_none()

    if not prefs:
        await update.message.reply_text("No preferences set yet. Type /start to configure them.")
        return

    def fmt(lst: list) -> str:
        return ", ".join(lst).title() if lst else "Any"

    salary_str = f"{prefs.salary_currency} {prefs.min_salary:,}" if prefs.min_salary else "Not specified"

    msg = (
        "⚙️ *Your Current Settings*\n\n"
        f"🎯 *Roles:* {fmt(prefs.target_roles)}\n"
        f"📍 *Locations:* {fmt(prefs.locations)}\n"
        f"💰 *Min Salary:* {salary_str}\n"
        f"🏢 *Industries:* {fmt(prefs.industries)}\n"
        f"📊 *Company Size:* {fmt(prefs.company_sizes)}\n"
        f"💼 *Employment:* {fmt(prefs.employment_types)}\n"
        f"🎯 *Match Threshold:* {prefs.match_threshold}%\n"
        f"📱 *Daily Apply Limit:* {prefs.daily_apply_limit} applications\n\n"
        "_To reset all preferences, type_ /start"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
