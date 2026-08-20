# ─────────────────────────────────────────────────────────────────────────────
#  LeadCRM Backend — Production Docker image
#
#  Runs the FastAPI + Uvicorn server on port 8002.
#  All configuration is via environment variables (see .env.example).
#
#  Build:
#    docker build -t leadcrm-backend .
#
#  Run (pass env file or individual vars):
#    docker run -p 8002:8002 --env-file .env leadcrm-backend
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# Prevent .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

EXPOSE 8002

# Bind to 0.0.0.0 so the container port is reachable from outside
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
