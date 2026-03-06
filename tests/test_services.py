"""
Unit tests for service fallback logic.
Tests run without an API key, verifying graceful degradation.
"""
import pytest


# ---------------------------------------------------------------------------
# CV Tailor fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cv_tailor_fallback():
    from services.cv_tailor import _fallback_tailor

    cv_data = {
        "primary_domain": "software engineering",
        "seniority_level": "senior",
        "total_years_experience": 8,
        "skills": ["python", "fastapi", "postgresql", "docker"],
    }
    job = {
        "title": "Backend Engineer",
        "company": "Acme Corp",
        "requirements": ["python", "api design", "sql", "kubernetes"],
    }
    result = _fallback_tailor(cv_data, job)

    assert "tailored_headline" in result
    assert "Acme Corp" in result["tailored_headline"]
    assert "top_skills_to_highlight" in result
    assert "ats_score" in result
    assert isinstance(result["ats_score"], int)
    assert 0 <= result["ats_score"] <= 100
    assert "missing_keywords" in result
    assert "rewritten_bullets" in result


# ---------------------------------------------------------------------------
# Coach fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_coach_fallback_encouraging():
    from services.coach import _fallback_coaching

    stats = {"total_apps": 2, "streak": 1, "rejections": 0, "interviews": 0}
    result = _fallback_coaching(stats)

    assert result["mood"] == "encouraging"
    assert "message" in result
    assert "action_items" in result
    assert len(result["action_items"]) > 0


@pytest.mark.asyncio
async def test_coach_fallback_empathetic():
    from services.coach import _fallback_coaching

    stats = {"total_apps": 10, "streak": 2, "rejections": 5, "interviews": 0}
    result = _fallback_coaching(stats)

    assert result["mood"] == "empathetic"


@pytest.mark.asyncio
async def test_coach_fallback_celebratory():
    from services.coach import _fallback_coaching

    stats = {"total_apps": 15, "streak": 5, "rejections": 3, "interviews": 2}
    result = _fallback_coaching(stats)

    assert result["mood"] == "celebratory"


# ---------------------------------------------------------------------------
# LinkedIn optimizer fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_linkedin_optimizer_fallback():
    from services.linkedin_optimizer import _fallback_optimization

    cv_data = {
        "name": "Jane Doe",
        "primary_domain": "data science",
        "seniority_level": "mid",
        "total_years_experience": 5,
        "skills": ["python", "machine learning", "sql", "tensorflow"],
        "cv_score": 70,
        "experience": [
            {"title": "Data Scientist", "company": "TechCo", "description": "Built ML models"},
        ],
    }
    result = _fallback_optimization(cv_data, ["ML Engineer"])

    assert len(result["headline_suggestions"]) == 3
    assert len(result["about_section"]) > 100
    assert "skills_to_add" in result
    assert "profile_strength_score" in result
    assert "section_checklist" in result
    assert len(result["section_checklist"]) >= 5


# ---------------------------------------------------------------------------
# Headhunter finder fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_headhunter_fallback():
    from services.headhunter_finder import _fallback_finder

    result = _fallback_finder(
        domain="software engineering",
        location="London",
        seniority="senior",
        skills=["python", "aws"],
    )

    assert "linkedin_search_queries" in result
    assert len(result["linkedin_search_queries"]) > 0
    assert "cold_outreach_template" in result
    assert "tips" in result


# ---------------------------------------------------------------------------
# Job match scoring
# ---------------------------------------------------------------------------

def test_job_match_scoring():
    from services.job_match import score_job

    job = {
        "title": "Python Backend Developer",
        "company": "StartupXYZ",
        "location": "Remote",
        "requirements": ["python", "fastapi", "postgresql"],
        "remote": True,
    }
    cv_skills = ["python", "fastapi", "docker", "postgresql"]
    preferences = {
        "locations": ["Remote"],
        "min_salary": None,
        "industries": [],
        "company_sizes": [],
    }

    score, reason = score_job(job, cv_skills, preferences)
    assert isinstance(score, int)
    assert score > 0  # Should match well
    assert isinstance(reason, str)


# ---------------------------------------------------------------------------
# Interview prep fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interview_prep_fallback():
    from services.interview_prep import _fallback_prep

    result = _fallback_prep(
        {"skills": ["python", "sql"], "primary_domain": "engineering"},
        {"title": "Engineer", "company": "Acme", "requirements": ["python"]},
    )

    assert isinstance(result, list)
    assert len(result) == 5
    assert "question" in result[0]
    assert "answer_guide" in result[0]
