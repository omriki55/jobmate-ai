"""
JobMate AI — Web Interface (FastAPI)
Mirrors the Telegram bot experience in a browser.
Run: uvicorn web.app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

# Resolve root so imports work whether launched from root or web/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from db.database import AsyncSessionLocal, init_db
from db.models import (
    ActivityLog, Application, CV, InterviewSession, Job,
    Notification, User, UserPreferences,
)
from services.coach import get_coaching_message
from services.company_research import research_company
from services.cv_export import generate_tailored_cv_docx
from services.cv_parser import process_cv
from services.cv_tailor import tailor_cv_for_job
from services.headhunter_finder import find_headhunters
from services.interview_prep import generate_interview_prep
from services.interview_sim import start_simulation, evaluate_answer
from services.job_match import SAMPLE_JOBS, get_top_matches, get_top_matches_live
from services.job_search import search_jobs_by_keywords
from services.job_scraper import scrape_and_store, get_total_job_count
from services.linkedin_optimizer import generate_linkedin_optimization

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App lifecycle — init DB then kick off background scrape
# ---------------------------------------------------------------------------

async def _background_scrape():
    """Run scrape silently in background; repeat every 2 hours."""
    while True:
        try:
            summary = await scrape_and_store()
            logger.info("Background scrape done: %s", summary)
        except Exception as exc:
            logger.warning("Background scrape error: %s", exc)
        await asyncio.sleep(2 * 60 * 60)   # 2 hours


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Fire-and-forget background scrape (first run + recurring)
    asyncio.create_task(_background_scrape())
    yield


app = FastAPI(title="JobMate AI", lifespan=lifespan)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_to_tid(session_id: str) -> int:
    """Deterministically map a browser session UUID → stable integer telegram_id."""
    return abs(int(hashlib.sha256(f"web:{session_id}".encode()).hexdigest()[:14], 16))


async def _get_user(db, session_id: str) -> User:
    tid = _session_to_tid(session_id)
    result = await db.execute(select(User).where(User.telegram_id == tid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Session not initialised — call /api/session/init first")
    return user


async def _get_or_create_job(db, job_data: dict) -> Job:
    result = await db.execute(
        select(Job).where(Job.external_id == str(job_data["id"]), Job.source == "sample")
    )
    job = result.scalar_one_or_none()
    if not job:
        job = Job(
            external_id=str(job_data["id"]),
            source="sample",
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


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SessionBody(BaseModel):
    session_id: str


class PreferencesBody(BaseModel):
    session_id: str
    target_roles: list[str]
    locations: list[str]
    min_salary: Optional[int] = None
    salary_currency: str = "USD"
    industries: list[str]
    company_sizes: list[str]
    employment_types: list[str]


class ApplyBody(BaseModel):
    session_id: str
    job_ids: list[int]


class TailorBody(BaseModel):
    session_id: str
    job_id: int


class InterviewPrepBody(BaseModel):
    session_id: str
    job_id: int


class SearchBody(BaseModel):
    session_id: str
    keywords: list[str]
    limit: int = 10


class OptimizeBody(BaseModel):
    session_id: str
    job_description: str
    job_title: str = ""
    company: str = ""


class UpdateStatusBody(BaseModel):
    session_id: str
    application_id: int
    new_status: str
    notes: str = ""


class SimStartBody(BaseModel):
    session_id: str
    job_id: int


class SimAnswerBody(BaseModel):
    session_id: str
    sim_id: int
    question_index: int
    answer: str


class HeadhunterBody(BaseModel):
    session_id: str
    domain: str = ""
    location: str = ""


class CoachBody(BaseModel):
    session_id: str
    message: str = ""


# ---------------------------------------------------------------------------
# Routes — static
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Routes — session
# ---------------------------------------------------------------------------

@app.post("/api/session/init")
async def init_session(body: SessionBody):
    """Upsert a web user; return their current onboarding state."""
    tid = _session_to_tid(body.session_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == tid))
        user = result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=tid, first_name="Web User", username=None)
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return {"state": user.state, "streak": user.streak_days}


# ---------------------------------------------------------------------------
# Routes — CV
# ---------------------------------------------------------------------------

@app.post("/api/cv/upload")
async def upload_cv(session_id: str = Form(...), file: UploadFile = File(...)):
    """Accept a CV file, parse it with Claude, persist it."""
    raw_bytes = await file.read()
    try:
        raw_text, parsed = await process_cv(raw_bytes, file.filename or "cv.pdf")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    async with AsyncSessionLocal() as db:
        user = await _get_user(db, session_id)

        # Deactivate old CVs
        old = await db.execute(select(CV).where(CV.user_id == user.id, CV.is_active == True))
        for old_cv in old.scalars():
            old_cv.is_active = False

        cv = CV(
            user_id=user.id,
            raw_text=raw_text,
            parsed_data=parsed,
            cv_score=parsed.get("cv_score", 0),
            improvement_notes=parsed.get("improvement_notes", []),
        )
        db.add(cv)
        await db.commit()

    return {
        "cv_score":              parsed.get("cv_score", 0),
        "name":                  parsed.get("name", ""),
        "seniority_level":       parsed.get("seniority_level", "mid"),
        "primary_domain":        parsed.get("primary_domain", ""),
        "total_years_experience": parsed.get("total_years_experience", 0),
        "skills":                parsed.get("skills", [])[:8],
        "improvement_notes":     parsed.get("improvement_notes", [])[:3],
        "summary":               parsed.get("summary", ""),
    }


@app.post("/api/cv/tailor")
async def tailor_cv(body: TailorBody):
    """
    Tailor CV talking-points for a specific job using Claude.
    Works even without an uploaded CV (returns generic talking points).
    """
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)

        # Fetch active CV (may be None for users who skipped upload)
        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        # Fetch job from DB first, then fall back to sample catalogue
        job_res = await db.execute(select(Job).where(Job.id == body.job_id))
        db_job  = job_res.scalar_one_or_none()

    if db_job:
        job_dict = {
            "title":        db_job.title,
            "company":      db_job.company,
            "location":     db_job.location,
            "description":  db_job.description or "",
            "requirements": db_job.requirements or [],
        }
    else:
        sample = next((j for j in SAMPLE_JOBS if j["id"] == body.job_id), None)
        if not sample:
            raise HTTPException(status_code=404, detail="Job not found")
        job_dict = {
            "title":        sample["title"],
            "company":      sample["company"],
            "location":     sample["location"],
            "description":  sample.get("description", ""),
            "requirements": sample.get("requirements", []),
        }

    tailored = await tailor_cv_for_job(cv_data, job_dict)
    return {
        "job":     {"title": job_dict["title"], "company": job_dict["company"]},
        "tailored": tailored,
    }


# ---------------------------------------------------------------------------
# Routes — preferences
# ---------------------------------------------------------------------------

@app.post("/api/preferences")
async def save_preferences(body: PreferencesBody):
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)

        pref_res = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = pref_res.scalar_one_or_none()
        fields = dict(
            target_roles=body.target_roles,
            locations=body.locations,
            min_salary=body.min_salary,
            salary_currency=body.salary_currency,
            industries=body.industries,
            company_sizes=body.company_sizes,
            employment_types=body.employment_types,
        )
        if prefs:
            for k, v in fields.items():
                setattr(prefs, k, v)
        else:
            db.add(UserPreferences(user_id=user.id, **fields))

        user.state = "ACTIVE"
        await db.commit()

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Routes — matches
# ---------------------------------------------------------------------------

@app.get("/api/matches")
async def get_matches(session_id: str):
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, session_id)

        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_skills = cv.parsed_data.get("skills", []) if cv and cv.parsed_data else []

        pref_res = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = pref_res.scalar_one_or_none()
        preferences = {}
        if prefs:
            preferences = {
                "locations":     prefs.locations or [],
                "min_salary":    prefs.min_salary,
                "industries":    prefs.industries or [],
                "company_sizes": prefs.company_sizes or [],
            }

    # Use live DB jobs (falls back to samples if DB empty)
    matches = await get_top_matches_live(cv_skills, preferences, limit=6, threshold=30)
    total_jobs = await get_total_job_count()
    return {"matches": matches, "total_jobs_indexed": total_jobs}


# ---------------------------------------------------------------------------
# Routes — jobs refresh (manual trigger)
# ---------------------------------------------------------------------------

@app.post("/api/jobs/refresh")
async def refresh_jobs():
    """Manually trigger a job scrape. Returns summary."""
    try:
        summary = await scrape_and_store()
        return {"status": "ok", **summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/jobs/count")
async def jobs_count():
    n = await get_total_job_count()
    return {"count": n}


# ---------------------------------------------------------------------------
# Routes — apply (works for both sample and DB job IDs)
# ---------------------------------------------------------------------------

@app.post("/api/apply")
async def apply_to_jobs(body: ApplyBody):
    applied, skipped = [], []
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)
        for jid in body.job_ids:
            # Look up job in DB by primary key first
            job_res = await db.execute(select(Job).where(Job.id == jid))
            job = job_res.scalar_one_or_none()

            # Fallback: sample jobs catalogue
            if not job:
                job_data = next((j for j in SAMPLE_JOBS if j["id"] == jid), None)
                if job_data:
                    job = await _get_or_create_job(db, job_data)
                else:
                    continue

            try:
                db.add(Application(user_id=user.id, job_id=job.id, status="applied"))
                await db.flush()
                applied.append({"title": job.title, "company": job.company})
            except IntegrityError:
                await db.rollback()
                skipped.append(job.title)
        await db.commit()
    return {"applied": applied, "skipped": skipped}


# ---------------------------------------------------------------------------
# Routes — pipeline
# ---------------------------------------------------------------------------

@app.get("/api/pipeline")
async def get_pipeline(session_id: str):
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, session_id)
        rows = (await db.execute(
            select(Application, Job)
            .join(Job, Application.job_id == Job.id)
            .where(Application.user_id == user.id)
            .order_by(Application.submitted_at.desc())
        )).all()

    return {"applications": [
        {
            "id":           app.id,
            "job_id":       job.id,
            "job_title":    job.title,
            "company":      job.company,
            "location":     job.location,
            "remote":       job.remote,
            "status":       app.status,
            "submitted_at": app.submitted_at.strftime("%b %d"),
        }
        for app, job in rows
    ]}


# ---------------------------------------------------------------------------
# Routes — stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def get_stats(session_id: str):
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, session_id)
        apps = (await db.execute(
            select(Application).where(Application.user_id == user.id)
        )).scalars().all()

    by_status: dict[str, int] = {}
    for a in apps:
        by_status[a.status] = by_status.get(a.status, 0) + 1

    total      = len(apps)
    responded  = total - by_status.get("applied", 0)
    interviews = by_status.get("interview", 0) + by_status.get("offer", 0)
    return {
        "total":          total,
        "by_status":      by_status,
        "streak":         user.streak_days,
        "response_rate":  round(responded  / total * 100) if total else 0,
        "interview_rate": round(interviews  / total * 100) if total else 0,
    }


# ---------------------------------------------------------------------------
# Routes — interview prep
# ---------------------------------------------------------------------------

def _resolve_job(db_job, job_id: int) -> dict:
    """Convert DB job ORM or sample-catalogue entry → plain dict."""
    if db_job:
        return {
            "title":        db_job.title,
            "company":      db_job.company,
            "location":     db_job.location,
            "description":  db_job.description or "",
            "requirements": db_job.requirements or [],
        }
    sample = next((j for j in SAMPLE_JOBS if j["id"] == job_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "title":        sample["title"],
        "company":      sample["company"],
        "location":     sample["location"],
        "description":  sample.get("description", ""),
        "requirements": sample.get("requirements", []),
    }


@app.post("/api/interview/prep")
async def interview_prep(body: InterviewPrepBody):
    """Generate 5 tailored interview Q&A pairs for a job using Claude."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)

        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        job_res = await db.execute(select(Job).where(Job.id == body.job_id))
        db_job  = job_res.scalar_one_or_none()

    job_dict = _resolve_job(db_job, body.job_id)
    questions = await generate_interview_prep(cv_data, job_dict)
    return {"job": {"title": job_dict["title"], "company": job_dict["company"]}, "questions": questions}


# ---------------------------------------------------------------------------
# Routes — CV export (.docx download)
# ---------------------------------------------------------------------------

@app.get("/api/cv/export")
async def export_cv(session_id: str, job_id: int):
    """
    Generate and stream a tailored .docx CV for the given job.
    The browser triggers a file download automatically.
    """
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, session_id)

        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        job_res = await db.execute(select(Job).where(Job.id == job_id))
        db_job  = job_res.scalar_one_or_none()

    job_dict = _resolve_job(db_job, job_id)

    # Re-run tailoring to get the most recent talking-points
    tailored = await tailor_cv_for_job(cv_data, job_dict)

    docx_bytes = generate_tailored_cv_docx(cv_data, tailored, job_dict)

    safe_company = "".join(c for c in job_dict["company"] if c.isalnum() or c in "- ")
    safe_title   = "".join(c for c in job_dict["title"]   if c.isalnum() or c in "- ")
    filename = f"CV_{safe_company}_{safe_title}.docx".replace(" ", "_")

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Routes — digest (morning check-in summary for returning users)
# ---------------------------------------------------------------------------

@app.get("/api/digest")
async def get_digest(session_id: str):
    """
    Return a lightweight digest for returning users:
    streak, total apps, and how many new jobs were indexed since the last check-in.
    """
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, session_id)
        total_apps = (await db.execute(
            select(Application).where(Application.user_id == user.id)
        )).scalars().all()

    total_jobs = await get_total_job_count()
    return {
        "streak":      user.streak_days,
        "total_apps":  len(total_apps),
        "total_jobs":  total_jobs,
    }


# ---------------------------------------------------------------------------
# Routes — keyword job search
# ---------------------------------------------------------------------------

@app.post("/api/jobs/search")
async def search_jobs(body: SearchBody):
    """Search jobs by keywords against title, description, company."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)

        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_skills = cv.parsed_data.get("skills", []) if cv and cv.parsed_data else []

        pref_res = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = pref_res.scalar_one_or_none()
        preferences = {}
        if prefs:
            preferences = {
                "locations":     prefs.locations or [],
                "min_salary":    prefs.min_salary,
                "industries":    prefs.industries or [],
                "company_sizes": prefs.company_sizes or [],
            }

    results = await search_jobs_by_keywords(
        keywords=body.keywords,
        cv_skills=cv_skills,
        preferences=preferences,
        limit=body.limit,
    )
    return {"results": results, "query": body.keywords, "count": len(results)}


# ---------------------------------------------------------------------------
# Routes — ATS CV optimization
# ---------------------------------------------------------------------------

@app.post("/api/cv/optimize")
async def optimize_cv(body: OptimizeBody):
    """ATS-optimize CV against a raw job description text."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)
        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

    job_dict = {
        "title":        body.job_title,
        "company":      body.company,
        "location":     "",
        "description":  body.job_description,
        "requirements": [],
    }
    tailored = await tailor_cv_for_job(cv_data, job_dict)
    return {"job": {"title": body.job_title, "company": body.company}, "tailored": tailored}


# ---------------------------------------------------------------------------
# Routes — dashboard (combined view)
# ---------------------------------------------------------------------------

@app.get("/api/dashboard")
async def get_dashboard(session_id: str):
    """Combined dashboard: pipeline + stats + recent activity."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, session_id)

        # Pipeline
        rows = (await db.execute(
            select(Application, Job)
            .join(Job, Application.job_id == Job.id)
            .where(Application.user_id == user.id)
            .order_by(Application.submitted_at.desc())
        )).all()

        # Stats
        apps_list = [app for app, _ in rows]
        by_status: dict[str, int] = {}
        for a in apps_list:
            by_status[a.status] = by_status.get(a.status, 0) + 1
        total = len(apps_list)
        responded = total - by_status.get("applied", 0)
        interviews = by_status.get("interview", 0) + by_status.get("offer", 0)

        # Recent activity
        activity_rows = (await db.execute(
            select(ActivityLog)
            .where(ActivityLog.user_id == user.id)
            .order_by(ActivityLog.created_at.desc())
            .limit(20)
        )).scalars().all()

        # Unread notifications
        notif_count = (await db.execute(
            select(func.count(Notification.id))
            .where(Notification.user_id == user.id, Notification.is_read == False)
        )).scalar() or 0

    total_jobs = await get_total_job_count()

    return {
        "pipeline": [
            {
                "id":           app.id,
                "job_id":       job.id,
                "job_title":    job.title,
                "company":      job.company,
                "location":     job.location,
                "remote":       job.remote,
                "status":       app.status,
                "submitted_at": app.submitted_at.strftime("%b %d"),
                "notes":        app.notes or "",
            }
            for app, job in rows
        ],
        "stats": {
            "total":          total,
            "by_status":      by_status,
            "streak":         user.streak_days,
            "response_rate":  round(responded / total * 100) if total else 0,
            "interview_rate": round(interviews / total * 100) if total else 0,
        },
        "activity": [
            {
                "action":     a.action,
                "detail":     a.detail,
                "created_at": a.created_at.strftime("%b %d %H:%M"),
            }
            for a in activity_rows
        ],
        "unread_notifications": notif_count,
        "total_jobs": total_jobs,
    }


# ---------------------------------------------------------------------------
# Routes — pipeline status update
# ---------------------------------------------------------------------------

@app.post("/api/pipeline/update")
async def update_pipeline_status(body: UpdateStatusBody):
    """Update an application's status."""
    valid_statuses = {"applied", "viewed", "contacted", "interview", "offer", "rejected", "withdrawn"}
    if body.new_status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid status. Must be one of: {valid_statuses}")

    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)
        app_res = await db.execute(
            select(Application).where(
                Application.id == body.application_id,
                Application.user_id == user.id,
            )
        )
        app = app_res.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")

        old_status = app.status
        app.status = body.new_status
        app.last_status_change_at = datetime.utcnow()
        if body.notes:
            app.notes = body.notes

        # Log the activity
        db.add(ActivityLog(
            user_id=user.id,
            action="status_change",
            detail={"application_id": app.id, "from": old_status, "to": body.new_status},
        ))
        await db.commit()

    return {"status": "ok", "old_status": old_status, "new_status": body.new_status}


# ---------------------------------------------------------------------------
# Routes — notifications
# ---------------------------------------------------------------------------

@app.get("/api/notifications")
async def get_notifications(session_id: str):
    """Return unread notifications for the user."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, session_id)
        rows = (await db.execute(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(20)
        )).scalars().all()

        # Mark as read
        for n in rows:
            if not n.is_read:
                n.is_read = True
        await db.commit()

    return {"notifications": [
        {
            "id":         n.id,
            "type":       n.type,
            "data":       n.data,
            "is_read":    n.is_read,
            "created_at": n.created_at.strftime("%b %d %H:%M"),
        }
        for n in rows
    ]}


# ---------------------------------------------------------------------------
# Routes — interview simulation
# ---------------------------------------------------------------------------

@app.post("/api/interview/simulate/start")
async def start_interview_sim(body: SimStartBody):
    """Start a mock interview simulation for a specific job."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)

        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        job_res = await db.execute(select(Job).where(Job.id == body.job_id))
        db_job = job_res.scalar_one_or_none()

    job_dict = _resolve_job(db_job, body.job_id)

    # Research the company
    company_context = await research_company(job_dict.get("company", ""), job_dict)

    # Generate simulation questions
    sim_result = await start_simulation(cv_data, job_dict, company_context)

    # Persist the simulation session
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)
        session = InterviewSession(
            user_id=user.id,
            job_id=body.job_id,
            questions=sim_result["questions"],
            answers=[],
        )
        db.add(session)
        db.add(ActivityLog(
            user_id=user.id,
            action="interview_sim",
            detail={"job_id": body.job_id, "job_title": job_dict["title"]},
        ))
        await db.commit()
        await db.refresh(session)
        sim_id = session.id

    return {
        "sim_id": sim_id,
        "job": {"title": job_dict["title"], "company": job_dict["company"]},
        "company_context": company_context,
        "questions": sim_result["questions"],
    }


@app.post("/api/interview/simulate/answer")
async def submit_sim_answer(body: SimAnswerBody):
    """Submit an answer for a mock interview question and get feedback."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)

        sim_res = await db.execute(
            select(InterviewSession).where(
                InterviewSession.id == body.sim_id,
                InterviewSession.user_id == user.id,
            )
        )
        sim = sim_res.scalar_one_or_none()
        if not sim:
            raise HTTPException(status_code=404, detail="Simulation session not found")

        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        job_res = await db.execute(select(Job).where(Job.id == sim.job_id))
        db_job = job_res.scalar_one_or_none()

    job_dict = _resolve_job(db_job, sim.job_id)

    questions = sim.questions or []
    if body.question_index < 0 or body.question_index >= len(questions):
        raise HTTPException(status_code=422, detail="Invalid question index")

    question = questions[body.question_index]

    # Evaluate the answer
    feedback = await evaluate_answer(cv_data, job_dict, question, body.answer)

    # Persist answer + feedback
    async with AsyncSessionLocal() as db:
        sim_res = await db.execute(
            select(InterviewSession).where(InterviewSession.id == body.sim_id)
        )
        sim = sim_res.scalar_one_or_none()
        answers = list(sim.answers or [])
        answers.append({
            "question_index": body.question_index,
            "answer": body.answer,
            "feedback": feedback,
        })
        sim.answers = answers

        # Calculate overall score if all questions answered
        if len(answers) >= len(questions):
            scores = [a["feedback"].get("score", 5) for a in answers if "feedback" in a]
            sim.overall_score = round(sum(scores) / len(scores)) if scores else 5

        await db.commit()

    is_last = body.question_index >= len(questions) - 1
    return {
        "feedback": feedback,
        "question_index": body.question_index,
        "is_last": is_last,
        "overall_score": sim.overall_score if is_last else None,
    }


# ---------------------------------------------------------------------------
# Routes — headhunter discovery
# ---------------------------------------------------------------------------

@app.post("/api/headhunters/find")
async def find_headhunters_route(body: HeadhunterBody):
    """Find headhunters/recruiters specialized in the user's field."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)

        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        pref_res = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = pref_res.scalar_one_or_none()

    domain = body.domain or cv_data.get("primary_domain", "professional")
    location = body.location or (prefs.locations[0] if prefs and prefs.locations else "Remote")
    seniority = cv_data.get("seniority_level", "mid")
    skills = cv_data.get("skills", [])
    target_roles = prefs.target_roles if prefs else []

    result = await find_headhunters(
        domain=domain,
        location=location,
        seniority=seniority,
        skills=skills,
        target_roles=target_roles,
    )
    return result


# ---------------------------------------------------------------------------
# Routes — career coach (emotional support)
# ---------------------------------------------------------------------------

@app.post("/api/coach")
async def coaching(body: CoachBody):
    """Get a personalized coaching message based on pipeline data."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)
        apps = (await db.execute(
            select(Application).where(Application.user_id == user.id)
        )).scalars().all()

    by_status: dict[str, int] = {}
    for a in apps:
        by_status[a.status] = by_status.get(a.status, 0) + 1

    total = len(apps)
    responded = total - by_status.get("applied", 0)

    user_stats = {
        "total_apps":    total,
        "response_rate": round(responded / total * 100) if total else 0,
        "streak":        user.streak_days,
        "interviews":    by_status.get("interview", 0) + by_status.get("offer", 0),
        "rejections":    by_status.get("rejected", 0),
        "days_active":   (datetime.utcnow() - user.created_at).days if user.created_at else 0,
    }

    result = await get_coaching_message(user_stats, body.message)
    return result


# ---------------------------------------------------------------------------
# Routes — LinkedIn optimization
# ---------------------------------------------------------------------------

@app.post("/api/linkedin/optimize")
async def optimize_linkedin(body: SessionBody):
    """Generate LinkedIn profile optimization guide from CV data."""
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, body.session_id)

        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        pref_res = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = pref_res.scalar_one_or_none()
        target_roles = prefs.target_roles if prefs else []

    result = await generate_linkedin_optimization(cv_data, target_roles)
    return result
