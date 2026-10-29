import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routes.api import router

app = FastAPI(title="DevTeam AI", description="Autonomous AI Software Engineer Platform")

# API routes first so they take precedence over the static frontend
app.include_router(router)

# Serve the static web UI from webui/ (index.html at /, assets alongside it).
# Mounted AFTER the router so /generate, /status/... are matched first.
_WEBUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webui")
app.mount("/", StaticFiles(directory=_WEBUI_DIR, html=True), name="webui")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
