import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routes.api import router

app = FastAPI(title="DevTeam AI", description="Autonomous AI Software Engineer Platform")

# CORS: the Vercel frontend calls this API cross-origin. Without this the
# browser blocks every request ("Failed to fetch").
# ALLOWED_ORIGIN env: "*" (default) allows all origins; a comma-separated
# list (e.g. "https://your-app.vercel.app") locks it down.
_allowed_origin = os.getenv("ALLOWED_ORIGIN", "*")
_origins = [o.strip().rstrip("/") for o in _allowed_origin.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes first so they take precedence over the static frontend
app.include_router(router)

# Serve the static web UI from webui/ (index.html at /, assets alongside it).
# Mounted AFTER the router so /generate, /status/... are matched first.
_WEBUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webui")
app.mount("/", StaticFiles(directory=_WEBUI_DIR, html=True), name="webui")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
