"""
API endpoint tests for JobMate AI.
Tests core flows: session, auth, uploads, matches, pipeline.
"""
import io
import pytest
from tests.conftest import auth_headers


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


# ---------------------------------------------------------------------------
# Session init
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_init_returns_token(client):
    resp = await client.post("/api/session/init", json={"session_id": "abc-123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "state" in data
    assert len(data["token"]) > 20  # JWT is long


@pytest.mark.asyncio
async def test_session_init_same_session_returns_same_user(client):
    r1 = await client.post("/api/session/init", json={"session_id": "same-user"})
    r2 = await client.post("/api/session/init", json={"session_id": "same-user"})
    # Both should succeed and return tokens for the same user
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["state"] == r2.json()["state"]


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthorized_without_token(client):
    resp = await client.get("/api/matches")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unauthorized_with_bad_token(client):
    resp = await client.get("/api/matches", headers={"Authorization": "Bearer fake.bad.token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_authorized_with_valid_token(client, auth_token):
    resp = await client.get("/api/matches", headers=auth_headers(auth_token))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_matches(client, auth_token):
    resp = await client.get("/api/matches", headers=auth_headers(auth_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "matches" in data
    assert isinstance(data["matches"], list)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pipeline_empty(client, auth_token):
    resp = await client.get("/api/pipeline", headers=auth_headers(auth_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["applications"] == []


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_dashboard(client, auth_token):
    resp = await client.get("/api/dashboard", headers=auth_headers(auth_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "pipeline" in data
    assert "stats" in data
    assert "activity" in data


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stats(client, auth_token):
    resp = await client.get("/api/stats", headers=auth_headers(auth_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["streak"] == 0


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_digest(client, auth_token):
    resp = await client.get("/api/digest", headers=auth_headers(auth_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "streak" in data
    assert "total_apps" in data


# ---------------------------------------------------------------------------
# CV upload validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_wrong_file_type(client, auth_token):
    """Uploading a .exe should return 422."""
    file = io.BytesIO(b"not a real exe")
    resp = await client.post(
        "/api/cv/upload",
        files={"file": ("malware.exe", file, "application/octet-stream")},
        headers=auth_headers(auth_token),
    )
    assert resp.status_code == 422
    assert "Unsupported file type" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_too_large(client, auth_token):
    """Uploading a file over MAX_UPLOAD_MB should return 413."""
    # Create a ~11MB PDF-like file (over the 10MB limit)
    big_data = b"%PDF-1.4 " + (b"x" * (11 * 1024 * 1024))
    resp = await client.post(
        "/api/cv/upload",
        files={"file": ("big.pdf", io.BytesIO(big_data), "application/pdf")},
        headers=auth_headers(auth_token),
    )
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Job search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_search(client, auth_token):
    resp = await client.post(
        "/api/jobs/search",
        json={"keywords": ["python", "remote"]},
        headers=auth_headers(auth_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "count" in data


# ---------------------------------------------------------------------------
# Coach
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_coach(client, auth_token):
    resp = await client.post(
        "/api/coach",
        json={"message": "I'm feeling discouraged"},
        headers=auth_headers(auth_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert "mood" in data


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notifications_empty(client, auth_token):
    resp = await client.get("/api/notifications", headers=auth_headers(auth_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["notifications"] == []


# ---------------------------------------------------------------------------
# Jobs count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jobs_count(client):
    resp = await client.get("/api/jobs/count")
    assert resp.status_code == 200
    assert "count" in resp.json()
