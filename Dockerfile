FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps needed for PDF parsing (pdfplumber) and health checks
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run Alembic migrations then start gunicorn with uvicorn workers
# PORT is set by Render/Railway/Heroku; defaults to 8000 for local Docker
ENV PORT=8000
EXPOSE 8000

CMD sh -c "alembic upgrade head && gunicorn web.app:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT} --timeout 120 --graceful-timeout 30"
