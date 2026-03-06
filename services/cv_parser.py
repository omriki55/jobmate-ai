"""
CV Parser — extracts raw text from PDF/DOCX then calls Claude to produce
a structured JSON profile used throughout the app.
"""
from __future__ import annotations

import io
import json
import asyncio
import logging
import re

import pdfplumber
from docx import Document
from anthropic import AsyncAnthropic

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# ---------------------------------------------------------------------------
# Text extraction helpers (sync — run in thread pool)
# ---------------------------------------------------------------------------

def _extract_pdf(file_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    return "\n".join(pages).strip()


def _extract_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()


def extract_linkedin_url(text: str) -> str | None:
    """Find a LinkedIn profile URL in raw CV text."""
    m = re.search(
        r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-%.]+",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    url = m.group(0)
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


# ---------------------------------------------------------------------------
# Claude parsing
# ---------------------------------------------------------------------------

PARSE_PROMPT = """You are a professional CV/resume parser. Analyze the CV below and return ONLY a valid JSON object — no markdown, no explanation.

CV:
{cv_text}

Return this exact JSON structure (use null where information is absent):
{{
  "name": "Full name",
  "email": "email or null",
  "phone": "phone or null",
  "location": "city/country or null",
  "summary": "1-2 sentence professional summary",
  "experience": [
    {{
      "company": "Company name",
      "title": "Job title",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or present",
      "description": "Key responsibilities and achievements",
      "skills_used": ["skill1", "skill2"]
    }}
  ],
  "education": [
    {{
      "institution": "Name",
      "degree": "Degree",
      "field": "Field of study",
      "year": "Graduation year or null"
    }}
  ],
  "skills": ["skill1", "skill2"],
  "languages": ["English - Native"],
  "total_years_experience": 5,
  "seniority_level": "junior|mid|senior|lead|executive",
  "primary_domain": "software engineering|product management|marketing|sales|design|finance|customer success|data science|devops|other",
  "cv_score": 72,
  "improvement_notes": [
    "Add quantified results to bullet points (e.g. 'increased revenue by 20%')",
    "Add a concise professional summary at the top",
    "Include more ATS-friendly keywords from your target job descriptions"
  ]
}}

Rules:
- cv_score 0-100: based on completeness, quantified achievements, ATS readiness, clarity.
- Do NOT invent information not present in the CV.
- Return ONLY the JSON object, nothing else."""


def _mock_parsed(cv_text: str) -> dict:
    """Best-effort keyword parse when Claude is unavailable."""
    import re
    lines = [l.strip() for l in cv_text.splitlines() if l.strip()]
    name = lines[0] if lines else "Candidate"
    years = 0
    m = re.search(r"(\d{1,2})\s*\+?\s*year", cv_text, re.I)
    if m:
        years = int(m.group(1))
    tech_kw = ["python","javascript","react","sql","java","typescript","aws","docker","kubernetes",
                "product","design","marketing","sales","data","machine learning","devops"]
    skills = [k for k in tech_kw if k in cv_text.lower()][:10]
    return {
        "name": name, "email": None, "phone": None, "location": None,
        "summary": f"Experienced professional with background in {', '.join(skills[:3]) or 'various domains'}.",
        "experience": [], "education": [], "skills": skills, "languages": [],
        "total_years_experience": years, "seniority_level": "mid",
        "primary_domain": skills[0] if skills else "professional",
        "cv_score": 55,
        "improvement_notes": [
            "Add your Anthropic API key to .env to enable full AI-powered CV analysis.",
            "Quantify achievements with metrics (e.g. 'increased revenue by 30%').",
            "Add a concise professional summary at the top.",
        ],
    }


async def parse_cv_with_claude(cv_text: str) -> dict:
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        logger.info("No API key — using keyword-based CV parsing")
        return _mock_parsed(cv_text)
    try:
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": PARSE_PROMPT.format(cv_text=cv_text[:12000])}],
        )
        raw = message.content[0].text.strip()

        # Strip optional markdown code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]

        return json.loads(raw.strip())
    except Exception as exc:
        logger.warning("Claude CV parsing failed (%s) — using keyword fallback", exc)
        return _mock_parsed(cv_text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def process_cv(file_bytes: bytes, file_name: str) -> tuple[str, dict]:
    """
    Extract text from a CV file and parse it with Claude.
    Returns (raw_text, parsed_data).  parsed_data includes 'linkedin_url'
    if one was found in the CV text.
    Raises ValueError for unreadable/too-short content.
    """
    loop = asyncio.get_event_loop()
    name_lower = file_name.lower()

    if name_lower.endswith(".pdf"):
        raw_text = await loop.run_in_executor(None, _extract_pdf, file_bytes)
    elif name_lower.endswith((".docx", ".doc")):
        raw_text = await loop.run_in_executor(None, _extract_docx, file_bytes)
    else:
        # Treat as plain text
        raw_text = file_bytes.decode("utf-8", errors="ignore")

    raw_text = raw_text.strip()
    if len(raw_text) < 100:
        raise ValueError(
            "Could not extract meaningful text from your CV. "
            "Please send a PDF or DOCX file, or paste the CV text directly."
        )

    parsed_data = await parse_cv_with_claude(raw_text)

    # Extract LinkedIn URL from CV text if present
    li_url = extract_linkedin_url(raw_text)
    if li_url:
        parsed_data["linkedin_url"] = li_url

    return raw_text, parsed_data
