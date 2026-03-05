"""
JobMate AI — Telegram Bot Entry Point

Run:
    python main.py
"""
import asyncio
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config.settings import TELEGRAM_BOT_TOKEN, CHECKIN_HOUR
from db.database import init_db
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
from bot.handlers.onboarding import (
    start,
    handle_cv_upload,
    handle_cv_text,
    handle_role,
    handle_location_callback,
    handle_salary,
    handle_industry_callback,
    handle_company_size_callback,
    handle_employment_type_callback,
    handle_confirmation_yes,
    handle_confirmation_edit,
)
from bot.handlers.commands import (
    help_command,
    matches_command,
    pipeline_command,
    stats_command,
    settings_command,
)
from bot.handlers.callbacks import handle_apply_skip_callback

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Daily check-in job (runs via PTB's built-in JobQueue)
# ---------------------------------------------------------------------------

async def daily_checkin(context) -> None:
    """Send morning check-in to all active users."""
    from db.database import AsyncSessionLocal
    from db.models import User, CV, UserPreferences
    from services.job_match import get_top_matches
    from bot.messages import morning_checkin_message
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.state == "ACTIVE"))
        users = result.scalars().all()

    for user in users:
        try:
            async with AsyncSessionLocal() as db:
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
                        "locations":     prefs.locations or [],
                        "min_salary":    prefs.min_salary,
                        "industries":    prefs.industries or [],
                        "company_sizes": prefs.company_sizes or [],
                    }

            matches = get_top_matches(cv_skills, preferences, limit=3, threshold=50)
            msg = morning_checkin_message(user.streak_days, matches)
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=msg,
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.warning("Failed to send check-in to %s: %s", user.telegram_id, exc)


# ---------------------------------------------------------------------------
# Application builder
# ---------------------------------------------------------------------------

def build_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Check your .env file.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ------------------------------------------------------------------
    # Onboarding ConversationHandler
    # ------------------------------------------------------------------
    onboarding = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AWAITING_CV: [
                MessageHandler(filters.Document.ALL, handle_cv_upload),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cv_text),
            ],
            AWAITING_ROLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_role),
            ],
            AWAITING_LOCATION: [
                CallbackQueryHandler(handle_location_callback, pattern=r"^loc_"),
            ],
            AWAITING_SALARY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_salary),
            ],
            AWAITING_INDUSTRY: [
                CallbackQueryHandler(handle_industry_callback, pattern=r"^ind_"),
            ],
            AWAITING_COMPANY_SIZE: [
                CallbackQueryHandler(handle_company_size_callback, pattern=r"^size_"),
            ],
            AWAITING_EMPLOYMENT_TYPE: [
                CallbackQueryHandler(handle_employment_type_callback, pattern=r"^emp_"),
            ],
            AWAITING_CONFIRMATION: [
                CallbackQueryHandler(handle_confirmation_yes,  pattern=r"^confirm_yes$"),
                CallbackQueryHandler(handle_confirmation_edit, pattern=r"^confirm_edit$"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
        # Persist conversation state across restarts (optional; omit for simplicity)
    )
    app.add_handler(onboarding)

    # ------------------------------------------------------------------
    # Global callback handlers (apply/skip buttons on match cards)
    # ------------------------------------------------------------------
    app.add_handler(
        CallbackQueryHandler(
            handle_apply_skip_callback,
            pattern=r"^(apply_|skip_)",
        )
    )

    # ------------------------------------------------------------------
    # Standalone commands
    # ------------------------------------------------------------------
    app.add_handler(CommandHandler("help",     help_command))
    app.add_handler(CommandHandler("matches",  matches_command))
    app.add_handler(CommandHandler("pipeline", pipeline_command))
    app.add_handler(CommandHandler("stats",    stats_command))
    app.add_handler(CommandHandler("settings", settings_command))

    # ------------------------------------------------------------------
    # Daily check-in scheduler (every day at CHECKIN_HOUR UTC)
    # ------------------------------------------------------------------
    app.job_queue.run_daily(
        daily_checkin,
        time=__import__("datetime").time(hour=CHECKIN_HOUR, minute=0),
    )

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    await init_db()
    logger.info("Database ready.")

    app = build_app()
    logger.info("JobMate AI bot starting (polling)...")

    async with app:
        await app.start()
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info("Bot is live. Press Ctrl+C to stop.")
        await asyncio.Event().wait()   # run until interrupted


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
