from __future__ import annotations
"""All InlineKeyboardMarkup builders used by the bot."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def location_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌍 Remote",  callback_data="loc_remote"),
            InlineKeyboardButton("🏢 On-site", callback_data="loc_onsite"),
        ],
        [
            InlineKeyboardButton("🔄 Hybrid",  callback_data="loc_hybrid"),
            InlineKeyboardButton("✅ Any",      callback_data="loc_any"),
        ],
    ])


def industry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💻 Tech",       callback_data="ind_tech"),
            InlineKeyboardButton("💰 Finance",    callback_data="ind_finance"),
        ],
        [
            InlineKeyboardButton("🏥 Healthcare", callback_data="ind_healthcare"),
            InlineKeyboardButton("📣 Marketing",  callback_data="ind_marketing"),
        ],
        [
            InlineKeyboardButton("🛒 E-commerce", callback_data="ind_ecommerce"),
            InlineKeyboardButton("✅ Any",         callback_data="ind_any"),
        ],
    ])


def company_size_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Startup (1–50)",    callback_data="size_startup"),
            InlineKeyboardButton("🏬 SMB (51–500)",      callback_data="size_smb"),
        ],
        [
            InlineKeyboardButton("🏛️ Enterprise (500+)", callback_data="size_enterprise"),
            InlineKeyboardButton("✅ Any",                callback_data="size_any"),
        ],
    ])


def employment_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💼 Full-time", callback_data="emp_fulltime"),
            InlineKeyboardButton("📋 Contract",  callback_data="emp_contract"),
        ],
        [
            InlineKeyboardButton("⏰ Part-time", callback_data="emp_parttime"),
            InlineKeyboardButton("✅ Any",        callback_data="emp_any"),
        ],
    ])


def confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Looks good!",       callback_data="confirm_yes"),
            InlineKeyboardButton("✏️ Edit preferences", callback_data="confirm_edit"),
        ],
    ])


def apply_matches_keyboard(matches: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for i, match in enumerate(matches[:3], 1):
        buttons.append([
            InlineKeyboardButton(f"✅ Apply #{i}", callback_data=f"apply_{match['id']}"),
            InlineKeyboardButton(f"❌ Skip #{i}",  callback_data=f"skip_{match['id']}"),
        ])
    buttons.append([
        InlineKeyboardButton("🚀 Apply to All", callback_data="apply_all"),
        InlineKeyboardButton("⏭️ Skip All",     callback_data="skip_all"),
    ])
    return InlineKeyboardMarkup(buttons)
