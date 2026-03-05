# JobMate AI — Step 1 MVP

Telegram bot that onboards job seekers, parses their CV with Claude AI,
collects job preferences, and shows matched roles they can apply to — all
without leaving Telegram.

---

## Quick Start

### 1. Get your tokens

| Token | Where |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Message `@BotFather` on Telegram → `/newbot` |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |

### 2. Install dependencies

```bash
cd jobmate-ai
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your tokens
```

### 4. Run

```bash
python main.py
```

The bot will create `jobmate.db` (SQLite) automatically on first run.

---

## Project Structure

```
jobmate-ai/
├── config/
│   └── settings.py          # Env vars
├── db/
│   ├── models.py            # SQLAlchemy models
│   └── database.py          # Async engine + session
├── services/
│   ├── cv_parser.py         # PDF/DOCX extraction + Claude parse
│   └── job_match.py         # Scoring engine + sample job catalogue
├── bot/
│   ├── states.py            # ConversationHandler state constants
│   ├── keyboards.py         # InlineKeyboardMarkup builders
│   ├── messages.py          # All user-facing strings
│   └── handlers/
│       ├── onboarding.py    # Multi-step onboarding flow
│       ├── commands.py      # /matches /pipeline /stats /settings
│       └── callbacks.py     # Apply/skip inline button handlers
├── main.py                  # Entry point + bot assembly
├── requirements.txt
└── .env.example
```

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Begin onboarding (or restart if already active) |
| `/matches` | See today's job matches |
| `/pipeline` | View your application tracker |
| `/stats` | Search statistics |
| `/settings` | View current preferences |
| `/help` | All commands |

---

## Conversation Flow

```
/start
  └─ Upload CV (PDF/DOCX/text)
       └─ Claude parses → CV Score shown
            └─ Target role?  (free text)
                 └─ Location? (buttons)
                      └─ Min salary? (free text / skip)
                           └─ Industry? (buttons)
                                └─ Company size? (buttons)
                                     └─ Employment type? (buttons)
                                          └─ Confirm summary
                                               └─ ✅ First matches shown
```

---

## What's Stubbed (Phase 2 work)

- **Job scraping** — currently uses 10 hardcoded sample jobs
- **Auto-submit** — apply buttons record the intent in DB but don't file real applications
- **Email monitoring** — pipeline state is manual (no Gmail/Outlook integration yet)
- **Momentum scoring** — streak counter in DB but not yet incremented
