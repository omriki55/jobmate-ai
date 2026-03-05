from __future__ import annotations
"""
Global inline-keyboard callback handlers (active after onboarding ends).
Handles apply / skip actions on job match cards.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from db.database import AsyncSessionLocal
from db.models import Application, CV, Job, User, UserPreferences
from services.job_match import SAMPLE_JOBS, get_top_matches
from bot.keyboards import apply_matches_keyboard
from bot.messages import matches_message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_job(db, job_data: dict) -> Job:
    result = await db.execute(
        select(Job).where(
            Job.external_id == str(job_data["id"]),
            Job.source == job_data.get("source", "sample"),
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        job = Job(
            external_id=str(job_data["id"]),
            source=job_data.get("source", "sample"),
            title=job_data["title"],
            company=job_data["company"],
            location=job_data["location"],
            salary_min=job_data.get("salary_min"),
            salary_max=job_data.get("salary_max"),
            salary_currency=job_data.get("salary_currency", "USD"),
            description=job_data.get("description", ""),
            requirements=job_data.get("requirements", []),
            employment_type=job_data.get("employment_type", "full-time"),
            industry=job_data.get("industry"),
            company_size=job_data.get("company_size"),
            remote=job_data.get("remote", False),
            url=job_data.get("url"),
        )
        db.add(job)
        await db.flush()
    return job


async def _record_application(user_id: int, job_id: int) -> bool:
    """Insert application row; returns True if newly created, False if duplicate."""
    async with AsyncSessionLocal() as db:
        try:
            app = Application(user_id=user_id, job_id=job_id, status="applied")
            db.add(app)
            await db.commit()
            return True
        except IntegrityError:
            await db.rollback()
            return False


async def _get_user_matches(telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    """Regenerate matches for the user from DB preferences."""
    cv_skills = context.user_data.get("cv_skills", [])
    preferences = {
        "locations":     context.user_data.get("locations", []),
        "min_salary":    context.user_data.get("min_salary"),
        "industries":    context.user_data.get("industries", []),
        "company_sizes": context.user_data.get("company_sizes", []),
    }

    # If context is empty (e.g. bot restarted), reload from DB
    if not cv_skills:
        async with AsyncSessionLocal() as db:
            user_result = await db.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_result.scalar_one_or_none()
            if not user:
                return []
            cv_result = await db.execute(
                select(CV).where(CV.user_id == user.id, CV.is_active == True)
            )
            cv = cv_result.scalar_one_or_none()
            cv_skills = cv.parsed_data.get("skills", []) if cv and cv.parsed_data else []

            pref_result = await db.execute(
                select(UserPreferences).where(UserPreferences.user_id == user.id)
            )
            prefs = pref_result.scalar_one_or_none()
            if prefs:
                preferences = {
                    "locations":     prefs.locations or [],
                    "min_salary":    prefs.min_salary,
                    "industries":    prefs.industries or [],
                    "company_sizes": prefs.company_sizes or [],
                }

    return get_top_matches(cv_skills, preferences, limit=5, threshold=50)


# ---------------------------------------------------------------------------
# Apply / Skip handlers
# ---------------------------------------------------------------------------

async def handle_apply_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id

    # Resolve the user's DB id
    async with AsyncSessionLocal() as db:
        user_result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_result.scalar_one_or_none()
    if not user:
        await query.answer("Please /start first.", show_alert=True)
        return

    data = query.data  # e.g. "apply_3", "skip_3", "apply_all", "skip_all"

    # ---- Apply All ----------------------------------------------------------
    if data == "apply_all":
        matches = await _get_user_matches(telegram_id, context)
        applied_names: list[str] = []

        async with AsyncSessionLocal() as db:
            for match in matches[:3]:
                job = await _get_or_create_job(db, match)
                await db.commit()
                created = await _record_application(user.id, job.id)
                if created:
                    applied_names.append(f"{match['title']} @ {match['company']}")

        await query.edit_message_reply_markup(reply_markup=None)
        if applied_names:
            names_str = "\n".join(f"• {n}" for n in applied_names)
            await query.message.reply_text(
                f"✅ Applied to *{len(applied_names)}* role(s):\n{names_str}\n\n"
                "CVs have been tailored for each position. "
                "I'll notify you the moment a company responds.\n\n"
                "Track with /pipeline",
                parse_mode="Markdown",
            )
        else:
            await query.message.reply_text("You've already applied to all of these roles.")
        return

    # ---- Skip All -----------------------------------------------------------
    if data == "skip_all":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "No problem! I'll keep searching.\n\n"
            "Check for matches anytime with /matches"
        )
        return

    # ---- Apply single -------------------------------------------------------
    if data.startswith("apply_"):
        job_id_str = data.removeprefix("apply_")
        job_data = next((j for j in SAMPLE_JOBS if str(j["id"]) == job_id_str), None)
        if not job_data:
            await query.answer("Job not found.", show_alert=True)
            return

        async with AsyncSessionLocal() as db:
            job = await _get_or_create_job(db, job_data)
            await db.commit()

        created = await _record_application(user.id, job.id)
        if created:
            await query.answer(f"✅ Applied to {job_data['title']} @ {job_data['company']}!")
            await query.message.reply_text(
                f"✅ Applied to *{job_data['title']}* @ {job_data['company']}!\n\n"
                "I'll let you know as soon as they respond. Track with /pipeline",
                parse_mode="Markdown",
            )
        else:
            await query.answer("You've already applied to this role.", show_alert=True)
        return

    # ---- Skip single --------------------------------------------------------
    if data.startswith("skip_"):
        await query.answer("Skipped ✓")
        return
