from __future__ import annotations
"""
Onboarding ConversationHandler.

Flow:
  /start → AWAITING_CV → AWAITING_ROLE → AWAITING_LOCATION (button)
         → AWAITING_SALARY → AWAITING_INDUSTRY (button)
         → AWAITING_COMPANY_SIZE (button) → AWAITING_EMPLOYMENT_TYPE (button)
         → AWAITING_CONFIRMATION (button) → ACTIVE (END)
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from db.database import AsyncSessionLocal
from db.models import CV, User, UserPreferences
from services.cv_parser import process_cv
from services.job_match import get_top_matches
from bot.states import (
    AWAITING_COMPANY_SIZE,
    AWAITING_CONFIRMATION,
    AWAITING_CV,
    AWAITING_EMPLOYMENT_TYPE,
    AWAITING_INDUSTRY,
    AWAITING_LOCATION,
    AWAITING_ROLE,
    AWAITING_SALARY,
)
from bot.keyboards import (
    apply_matches_keyboard,
    company_size_keyboard,
    confirmation_keyboard,
    employment_type_keyboard,
    industry_keyboard,
    location_keyboard,
)
from bot.messages import (
    CV_PROCESSING,
    ROLE_QUESTION,
    SALARY_QUESTION,
    SETUP_COMPLETE,
    WELCOME,
    cv_score_message,
    matches_message,
    preferences_summary,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_user(telegram_id: int, username: str | None, first_name: str | None) -> User:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name)
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user


def _build_preferences_dict(ud: dict) -> dict:
    return {
        "locations":       ud.get("locations", []),
        "min_salary":      ud.get("min_salary"),
        "salary_currency": ud.get("salary_currency", "USD"),
        "industries":      ud.get("industries", []),
        "company_sizes":   ud.get("company_sizes", []),
    }


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tg_user = update.effective_user
    user = await _get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    # Returning user who already completed onboarding
    if user.state == "ACTIVE":
        await update.message.reply_text(
            f"Welcome back, {tg_user.first_name or 'there'}! 👋\n\n"
            "Use /matches to see today's jobs or /pipeline to check your applications.\n"
            "Type /help to see all commands.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.message.reply_text(WELCOME, parse_mode="Markdown")
    return AWAITING_CV


# ---------------------------------------------------------------------------
# CV ingestion
# ---------------------------------------------------------------------------

async def handle_cv_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle CV sent as a file attachment."""
    doc = update.message.document
    if not doc:
        await update.message.reply_text("Please send your CV as a PDF or DOCX file.")
        return AWAITING_CV

    allowed_exts = (".pdf", ".docx", ".doc", ".txt")
    file_name = doc.file_name or "cv"
    if not any(file_name.lower().endswith(ext) for ext in allowed_exts):
        await update.message.reply_text(
            "Please send a PDF, DOCX, or TXT file. Other formats aren't supported yet."
        )
        return AWAITING_CV

    status_msg = await update.message.reply_text(CV_PROCESSING)
    try:
        tg_file = await doc.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())
        raw_text, parsed_data = await process_cv(file_bytes, file_name)
        await _save_cv(update.effective_user.id, raw_text, parsed_data)
        context.user_data["cv_skills"] = parsed_data.get("skills", [])
        await status_msg.delete()
        await update.message.reply_text(cv_score_message(parsed_data), parse_mode="Markdown")
        await update.message.reply_text(ROLE_QUESTION, parse_mode="Markdown")
        return AWAITING_ROLE
    except Exception as exc:
        logger.exception("CV upload error: %s", exc)
        await status_msg.delete()
        await update.message.reply_text(
            "❌ Couldn't read that file. Please try:\n"
            "• A PDF or DOCX file\n"
            "• Pasting your CV text directly\n\n"
            "If this keeps happening, contact support."
        )
        return AWAITING_CV


async def handle_cv_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle CV pasted as plain text (must be ≥ 200 chars to be treated as a CV)."""
    text = update.message.text or ""
    if len(text) < 200:
        await update.message.reply_text(
            "That looks too short to be a CV.\n\n"
            "Please upload a *PDF or DOCX file*, or paste your full CV text.",
            parse_mode="Markdown",
        )
        return AWAITING_CV

    status_msg = await update.message.reply_text(CV_PROCESSING)
    try:
        raw_text, parsed_data = await process_cv(text.encode(), "cv.txt")
        await _save_cv(update.effective_user.id, raw_text, parsed_data)
        context.user_data["cv_skills"] = parsed_data.get("skills", [])
        await status_msg.delete()
        await update.message.reply_text(cv_score_message(parsed_data), parse_mode="Markdown")
        await update.message.reply_text(ROLE_QUESTION, parse_mode="Markdown")
        return AWAITING_ROLE
    except Exception as exc:
        logger.exception("CV text error: %s", exc)
        await status_msg.delete()
        await update.message.reply_text("❌ Couldn't parse that. Please upload a PDF or DOCX file.")
        return AWAITING_CV


async def _save_cv(telegram_id: int, raw_text: str, parsed_data: dict) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one()
        # Deactivate old CVs
        old_result = await db.execute(select(CV).where(CV.user_id == user.id, CV.is_active == True))
        for old_cv in old_result.scalars():
            old_cv.is_active = False
        cv = CV(
            user_id=user.id,
            raw_text=raw_text,
            parsed_data=parsed_data,
            cv_score=parsed_data.get("cv_score", 0),
            improvement_notes=parsed_data.get("improvement_notes", []),
        )
        db.add(cv)
        await db.commit()


# ---------------------------------------------------------------------------
# Preference steps
# ---------------------------------------------------------------------------

async def handle_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    roles = [r.strip() for r in text.replace(",", "\n").split("\n") if r.strip()]
    context.user_data["target_roles"] = roles
    await update.message.reply_text(
        "📍 *Where do you want to work?*", reply_markup=location_keyboard(), parse_mode="Markdown"
    )
    return AWAITING_LOCATION


async def handle_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    mapping = {
        "loc_remote": ["remote"],
        "loc_onsite": ["on-site"],
        "loc_hybrid": ["hybrid"],
        "loc_any":    ["any"],
    }
    context.user_data["locations"] = mapping.get(query.data, ["any"])
    await query.edit_message_text("📍 Location saved ✅", parse_mode="Markdown")
    await query.message.reply_text(SALARY_QUESTION, parse_mode="Markdown")
    return AWAITING_SALARY


async def handle_salary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "skip":
        context.user_data.update(min_salary=None, salary_currency="USD", salary_display="Not specified")
    else:
        import re
        numbers = re.findall(r"[\d,]+", text)
        if numbers:
            amount = int(numbers[0].replace(",", ""))
            if "k" in text:
                amount *= 1000
            currency = "USD"
            for c in ("USD", "EUR", "GBP", "CAD", "AUD", "CHF", "SGD", "ILS"):
                if c.lower() in text:
                    currency = c
                    break
            context.user_data.update(
                min_salary=amount,
                salary_currency=currency,
                salary_display=f"{currency} {amount:,}",
            )
        else:
            context.user_data.update(min_salary=None, salary_currency="USD", salary_display="Not specified")

    await update.message.reply_text(
        "🏢 *Which industries are you targeting?*",
        reply_markup=industry_keyboard(),
        parse_mode="Markdown",
    )
    return AWAITING_INDUSTRY


async def handle_industry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    mapping = {
        "ind_tech":       ["tech"],
        "ind_finance":    ["finance", "fintech"],
        "ind_healthcare": ["healthcare"],
        "ind_marketing":  ["marketing"],
        "ind_ecommerce":  ["e-commerce"],
        "ind_any":        ["any"],
    }
    context.user_data["industries"] = mapping.get(query.data, ["any"])
    await query.edit_message_text("🏢 Industry saved ✅")
    await query.message.reply_text(
        "📊 *What company size do you prefer?*",
        reply_markup=company_size_keyboard(),
        parse_mode="Markdown",
    )
    return AWAITING_COMPANY_SIZE


async def handle_company_size_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    mapping = {
        "size_startup":    ["startup"],
        "size_smb":        ["smb"],
        "size_enterprise": ["enterprise"],
        "size_any":        ["any"],
    }
    context.user_data["company_sizes"] = mapping.get(query.data, ["any"])
    await query.edit_message_text("📊 Company size saved ✅")
    await query.message.reply_text(
        "💼 *What type of employment?*",
        reply_markup=employment_type_keyboard(),
        parse_mode="Markdown",
    )
    return AWAITING_EMPLOYMENT_TYPE


async def handle_employment_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    mapping = {
        "emp_fulltime": ["full-time"],
        "emp_contract": ["contract"],
        "emp_parttime": ["part-time"],
        "emp_any":      ["any"],
    }
    context.user_data["employment_types"] = mapping.get(query.data, ["full-time"])
    await query.edit_message_text("💼 Employment type saved ✅")

    # Show summary for confirmation
    prefs_display = {
        "roles":            context.user_data.get("target_roles", []),
        "locations":        context.user_data.get("locations", []),
        "salary_display":   context.user_data.get("salary_display", "Not specified"),
        "industries":       context.user_data.get("industries", []),
        "company_sizes":    context.user_data.get("company_sizes", []),
        "employment_types": context.user_data.get("employment_types", []),
    }
    await query.message.reply_text(
        preferences_summary(prefs_display),
        reply_markup=confirmation_keyboard(),
        parse_mode="Markdown",
    )
    return AWAITING_CONFIRMATION


# ---------------------------------------------------------------------------
# Confirmation → save + show first matches
# ---------------------------------------------------------------------------

async def handle_confirmation_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await _save_preferences(update.effective_user.id, context.user_data)
    await query.edit_message_text(SETUP_COMPLETE, parse_mode="Markdown")

    # Immediately show first matches
    cv_skills = context.user_data.get("cv_skills", [])
    preferences = _build_preferences_dict(context.user_data)
    matches = get_top_matches(cv_skills, preferences, limit=5, threshold=50)

    await query.message.reply_text(
        matches_message(matches),
        parse_mode="Markdown",
        reply_markup=apply_matches_keyboard(matches) if matches else None,
    )
    return ConversationHandler.END


async def handle_confirmation_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restart preference collection from scratch."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("No problem — let's redo your preferences.")
    await query.message.reply_text(ROLE_QUESTION, parse_mode="Markdown")
    return AWAITING_ROLE


async def _save_preferences(telegram_id: int, user_data: dict) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one()

        pref_result = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = pref_result.scalar_one_or_none()

        fields = dict(
            target_roles=user_data.get("target_roles", []),
            locations=user_data.get("locations", ["any"]),
            min_salary=user_data.get("min_salary"),
            salary_currency=user_data.get("salary_currency", "USD"),
            industries=user_data.get("industries", ["any"]),
            company_sizes=user_data.get("company_sizes", ["any"]),
            employment_types=user_data.get("employment_types", ["full-time"]),
        )
        if prefs:
            for k, v in fields.items():
                setattr(prefs, k, v)
        else:
            db.add(UserPreferences(user_id=user.id, **fields))

        user.state = "ACTIVE"
        await db.commit()
