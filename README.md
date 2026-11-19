# DevTeam AI — Autonomous AI Software Engineer

One prompt becomes a complete project — architecture, code, tests and docs — built end to end by a team of 8 AI specialists, then delivered as a ZIP. FastAPI backend + VS Code-style web IDE, deployed on Render + Vercel.

## Live Demo

* **App:** https://enterprise-dev-ai.vercel.app
* **API:** https://enterprise-devai-les9.onrender.com/api/health

## Project Structure

```
frontend/           # VS Code-style IDE (HTML/CSS/JS) — deployed on Vercel
backend/
  app/              # FastAPI entrypoint (serves the API and the static frontend)
  routes/           # API endpoints: generate, status, files, download, health
  agents/           # 8 pipeline specialists (requirements → docs)
  providers/        # LLM adapters with retry + error normalization
  services/         # generation, diff, projects, tasks, validation, usage
  storage/          # Repository pattern over SQLite (survives worker restarts)
  workflows/        # LangGraph dual-engine pipeline (PIPELINE_ENGINE flag)
  execution/        # Static validation + isolated executor
  security/         # API key guard, per-IP rate limiting, path validation
  tests/            # 142 tests
  requirements*.txt
render.yaml         # Render blueprint (rootDir: backend)
vercel.json         # Vercel config (serves frontend/)
docs/               # Architecture, security model, deployment guide
```

## Quick Start

```bash
cd backend
pip install -r requirements.txt -r requirements-web.txt
cp .env.example .env        # then add your GEMINI_API_KEY
uvicorn app.main:app --reload
# open http://localhost:8000
```

## How It Works

1. **Describe** the project you want to build
2. **Pipeline** — requirements → architecture → code (self-repairing retries) → review ("LGTM" skips the debugger) → tests → docs → package
3. **Watch** each stage stream into the AI panel
4. **Continue building** — iterate on a finished project with diffs against the previous version
5. **Export** the finished project as a ZIP

Dual pipeline engines: the default custom engine or a LangGraph StateGraph (`PIPELINE_ENGINE=langgraph`), with byte-identical output contracts.

## Supported Providers

| Provider | Requires | Notes |
|---|---|---|
| Google Gemini | API key | Default (`gemini-flash-lite-latest`) |
| OpenRouter | API key | OpenAI-compatible |
| Groq | API key | OpenAI-compatible |
| DeepSeek | API key | OpenAI-compatible |
| Ollama | Local server | No key required |

## Testing

```bash
cd backend
python -m pytest -v
```

142 tests covering the dual engine parity, provider adapters and errors, retry policy, API guard, run persistence, diff/patch integrity, path security, static validation, task states, and integration.

## Deployment

* **Backend (Render):** `render.yaml` blueprint — builds from `backend/`, runs `uvicorn app.main:app`. Set `GEMINI_API_KEY` (and optionally `PIPELINE_ENGINE`, `API_KEY`, `ALLOWED_ORIGIN`) in the dashboard.
* **Frontend (Vercel):** serves `frontend/` per `vercel.json`. The FastAPI backend also serves the same frontend at `/`, so one Render deploy alone is a working demo.

## Documentation

* [Architecture](docs/ARCHITECTURE.md)
* [Security Model](docs/SECURITY.md)
* [Deployment Guide](docs/DEPLOYMENT.md)

## Tech Stack

* **Frontend:** Vanilla HTML/CSS/JS (VS Code-style IDE shell, light + dark themes)
* **Backend:** FastAPI (async) with dual pipeline engines (custom + LangGraph)
* **Database:** SQLite via Repository pattern (Postgres drop-in)
* **LLM SDKs:** google-genai, openai
* **Testing:** pytest, pytest-asyncio

## License

MIT
