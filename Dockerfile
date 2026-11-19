# DevTeam AI — one image: FastAPI backend + static frontend.
#
# Build:  docker build -t devteam-ai .
# Run:    docker run -p 8000:8000 -e GEMINI_API_KEY=your_key -v devteam-data:/data devteam-ai
#
# The server expects to run with cwd = backend/ (same as Render's rootDir),
# and serves the repo-root frontend/ directory at / (see app/main.py).
FROM python:3.12-slim

WORKDIR /app/backend

# Dependencies first so this layer caches across code changes.
COPY backend/requirements-web.txt ./requirements-web.txt
RUN pip install --no-cache-dir -r requirements-web.txt

# App code, then the sibling frontend/ the app mounts at /.
COPY backend/ ./
COPY frontend/ /app/frontend/

# Run state (SQLite history) lives on the /data volume so it survives
# container restarts — unlike on free PaaS disks, which wipe on redeploy.
ENV RUNS_DB=/data/runs.db \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data
VOLUME /data

EXPOSE 8000

# curl isn't in python:*-slim; use stdlib urllib for the healthcheck.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
