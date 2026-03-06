"""
JobMate AI — Web Interface (FastAPI)
Production-ready web API with JWT auth, rate limiting, and security headers.
Run (dev):  uvicorn web.app:app --reload --port 8000
Run (prod): gunicorn web.app:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
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

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware

# Resolve root so imports work whether launched from root or web/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config.settings import (
    CORS_ORIGINS,
    ENVIRONMENT,
    LOG_LEVEL,
    MAX_UPLOAD_MB,
)
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
from web.auth import create_token, get_current_user

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

async def _background_scrape():
    """Run scrape silently in background; repeat every 2 hours."""
    while True:
        try:
            summary = await scrape_and_store()
            logger.info("Background scrape done: %s", summary)
        except Exception as exc:
            logger.warning("Background scrape error: %s", exc)
        await asyncio.sleep(2 * 60 * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(_background_scrape())
    yield


app = FastAPI(title="JobMate AI", lifespan=lifespan)
app.state.limiter = limiter

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ---------------------------------------------------------------------------
# Middleware — CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Middleware — security headers
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------------------------
# Global error handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please slow down."},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    if ENVIRONMENT == "production":
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def _session_to_tid(session_id: str) -> int:
    """Deterministically map a browser session UUID → stable integer telegram_id.
    Used ONLY during initial session creation to generate a user ID."""
    return abs(int(hashlib.sha256(f"web:{session_id}".encode()).hexdigest()[:14], 16))


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


# ---------------------------------------------------------------------------
# Request models (session_id removed — auth is via JWT header)
# ---------------------------------------------------------------------------

class SessionInitBody(BaseModel):
    session_id: str


class PreferencesBody(BaseModel):
    target_roles: list[str]
    locations: list[str]
    min_salary: Optional[int] = None
    salary_currency: str = "USD"
    industries: list[str]
    company_sizes: list[str]
    employment_types: list[str]


class ApplyBody(BaseModel):
    job_ids: list[int]


class TailorBody(BaseModel):
    job_id: int


class InterviewPrepBody(BaseModel):
    job_id: int


class SearchBody(BaseModel):
    keywords: list[str]
    limit: int = 10
    location_filter: Optional[str] = None


class OptimizeBody(BaseModel):
    job_description: str
    job_title: str = ""
    company: str = ""


class UpdateStatusBody(BaseModel):
    application_id: int
    new_status: str
    notes: str = ""


class SimStartBody(BaseModel):
    job_id: int


class SimAnswerBody(BaseModel):
    sim_id: int
    question_index: int
    answer: str


class HeadhunterBody(BaseModel):
    domain: str = ""
    location: str = ""


class CoachBody(BaseModel):
    message: str = ""


# ---------------------------------------------------------------------------
# Routes — static
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Routes — health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check():
    """Health check — verifies DB connectivity."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "healthy", "environment": ENVIRONMENT}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unhealthy"})


# ---------------------------------------------------------------------------
# Routes — session (only endpoint that accepts session_id, returns JWT)
# ---------------------------------------------------------------------------

@app.post("/api/session/init")
@limiter.limit("30/minute")
async def init_session(body: SessionInitBody, request: Request):
    """Upsert a web user; return a signed JWT token."""
    tid = _session_to_tid(body.session_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == tid))
        user = result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=tid, first_name="Web User", username=None)
            db.add(user)
            await db.commit()
            await db.refresh(user)

    token = create_token(user.id)
    return {"token": token, "state": user.state, "streak": user.streak_days}


# ---------------------------------------------------------------------------
# Routes — CV
# ---------------------------------------------------------------------------

@app.post("/api/cv/upload")
@limiter.limit("5/minute")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Accept a CV file, parse it with Claude, persist it."""
    # Validate file extension
    filename = file.filename or "cv.pdf"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{ext}'. Please upload a PDF or DOCX file.")

    # Validate file size
    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {MAX_UPLOAD_MB}MB.")

    try:
        raw_text, parsed = await process_cv(raw_bytes, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user.id))
        db_user = result.scalar_one()

        # Deactivate old CVs
        old = await db.execute(select(CV).where(CV.user_id == db_user.id, CV.is_active == True))
        for old_cv in old.scalars():
            old_cv.is_active = False

        cv = CV(
            user_id=db_user.id,
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
@limiter.limit("10/minute")
async def tailor_cv(
    body: TailorBody,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Tailor CV talking-points for a specific job using Claude."""
    async with AsyncSessionLocal() as db:
        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        job_res = await db.execute(select(Job).where(Job.id == body.job_id))
        db_job = job_res.scalar_one_or_none()

    job_dict = _resolve_job(db_job, body.job_id)
    tailored = await tailor_cv_for_job(cv_data, job_dict)
    return {
        "job":      {"title": job_dict["title"], "company": job_dict["company"]},
        "tailored": tailored,
    }


# ---------------------------------------------------------------------------
# Routes — preferences
# ---------------------------------------------------------------------------

@app.post("/api/preferences")
async def save_preferences(
    body: PreferencesBody,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
        db_user_res = await db.execute(select(User).where(User.id == user.id))
        db_user = db_user_res.scalar_one()

        pref_res = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == db_user.id)
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
            db.add(UserPreferences(user_id=db_user.id, **fields))

        db_user.state = "ACTIVE"
        await db.commit()

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Routes — matches
# ---------------------------------------------------------------------------

@app.get("/api/matches")
async def get_matches(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
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

    matches = await get_top_matches_live(cv_skills, preferences, limit=6, threshold=30)
    total_jobs = await get_total_job_count()
    return {"matches": matches, "total_jobs_indexed": total_jobs}


# ---------------------------------------------------------------------------
# Routes — jobs
# ---------------------------------------------------------------------------

@app.post("/api/jobs/refresh")
@limiter.limit("5/minute")
async def refresh_jobs(request: Request):
    """Manually trigger a job scrape."""
    try:
        summary = await scrape_and_store()
        return {"status": "ok", **summary}
    except Exception:
        raise HTTPException(status_code=500, detail="Job refresh failed")


@app.get("/api/jobs/count")
async def jobs_count():
    n = await get_total_job_count()
    return {"count": n}


# ---------------------------------------------------------------------------
# Routes — apply
# ---------------------------------------------------------------------------

@app.post("/api/apply")
async def apply_to_jobs(
    body: ApplyBody,
    user: User = Depends(get_current_user),
):
    applied, skipped = [], []
    async with AsyncSessionLocal() as db:
        for jid in body.job_ids:
            job_res = await db.execute(select(Job).where(Job.id == jid))
            job = job_res.scalar_one_or_none()

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
async def get_pipeline(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
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
async def get_stats(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
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

@app.post("/api/interview/prep")
@limiter.limit("10/minute")
async def interview_prep(
    body: InterviewPrepBody,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Generate 5 tailored interview Q&A pairs for a job."""
    async with AsyncSessionLocal() as db:
        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        job_res = await db.execute(select(Job).where(Job.id == body.job_id))
        db_job = job_res.scalar_one_or_none()

    job_dict = _resolve_job(db_job, body.job_id)
    questions = await generate_interview_prep(cv_data, job_dict)
    return {"job": {"title": job_dict["title"], "company": job_dict["company"]}, "questions": questions}


# ---------------------------------------------------------------------------
# Routes — CV export
# ---------------------------------------------------------------------------

@app.get("/api/cv/export")
async def export_cv(job_id: int, user: User = Depends(get_current_user)):
    """Generate and stream a tailored .docx CV."""
    async with AsyncSessionLocal() as db:
        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        job_res = await db.execute(select(Job).where(Job.id == job_id))
        db_job = job_res.scalar_one_or_none()

    job_dict = _resolve_job(db_job, job_id)
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
# Routes — digest
# ---------------------------------------------------------------------------

@app.get("/api/digest")
async def get_digest(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
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
async def search_jobs(
    body: SearchBody,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
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
        location_filter=body.location_filter,
    )
    return {"results": results, "query": body.keywords, "count": len(results)}


# ---------------------------------------------------------------------------
# Routes — ATS CV optimization
# ---------------------------------------------------------------------------

@app.post("/api/cv/optimize")
@limiter.limit("10/minute")
async def optimize_cv(
    body: OptimizeBody,
    request: Request,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
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
# Routes — dashboard
# ---------------------------------------------------------------------------

@app.get("/api/dashboard")
async def get_dashboard(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Application, Job)
            .join(Job, Application.job_id == Job.id)
            .where(Application.user_id == user.id)
            .order_by(Application.submitted_at.desc())
        )).all()

        apps_list = [app for app, _ in rows]
        by_status: dict[str, int] = {}
        for a in apps_list:
            by_status[a.status] = by_status.get(a.status, 0) + 1
        total = len(apps_list)
        responded = total - by_status.get("applied", 0)
        interviews = by_status.get("interview", 0) + by_status.get("offer", 0)

        activity_rows = (await db.execute(
            select(ActivityLog)
            .where(ActivityLog.user_id == user.id)
            .order_by(ActivityLog.created_at.desc())
            .limit(20)
        )).scalars().all()

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
async def update_pipeline_status(
    body: UpdateStatusBody,
    user: User = Depends(get_current_user),
):
    valid_statuses = {"applied", "viewed", "contacted", "interview", "offer", "rejected", "withdrawn"}
    if body.new_status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid status. Must be one of: {valid_statuses}")

    async with AsyncSessionLocal() as db:
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
async def get_notifications(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(20)
        )).scalars().all()

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
@limiter.limit("10/minute")
async def start_interview_sim(
    body: SimStartBody,
    request: Request,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
        cv_res = await db.execute(
            select(CV).where(CV.user_id == user.id, CV.is_active == True)
        )
        cv = cv_res.scalar_one_or_none()
        cv_data: dict = cv.parsed_data if cv and cv.parsed_data else {}

        job_res = await db.execute(select(Job).where(Job.id == body.job_id))
        db_job = job_res.scalar_one_or_none()

    job_dict = _resolve_job(db_job, body.job_id)
    company_context = await research_company(job_dict.get("company", ""), job_dict)
    sim_result = await start_simulation(cv_data, job_dict, company_context)

    async with AsyncSessionLocal() as db:
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
@limiter.limit("10/minute")
async def submit_sim_answer(
    body: SimAnswerBody,
    request: Request,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
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
    feedback = await evaluate_answer(cv_data, job_dict, question, body.answer)

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
@limiter.limit("10/minute")
async def find_headhunters_route(
    body: HeadhunterBody,
    request: Request,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
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
# Routes — career coach
# ---------------------------------------------------------------------------

@app.post("/api/coach")
@limiter.limit("10/minute")
async def coaching(
    body: CoachBody,
    request: Request,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
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
@limiter.limit("10/minute")
async def optimize_linkedin(
    request: Request,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
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


# ---------------------------------------------------------------------------
# Mount static files (MUST be after all route definitions)
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
