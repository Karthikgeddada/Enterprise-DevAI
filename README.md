# DevTeam AI - Incremental AI Coding Workspace

DevTeam AI is a production-grade, incremental AI coding workspace built on Streamlit. Describe changes in natural language, review proposed diffs, and accept or reject changes safely. All state is persisted to SQLite, enabling session resumption and crash recovery.

## Live Demo

Try the deployed app here: **https://enterprise-dev-ai.vercel.app**

## Features

* **Multi-Provider LLM Support** - Gemini, DeepSeek, Qwen, and Ollama with automatic fallback and retry
* **Incremental Workflow** - Plan tasks, generate per-task file changes, review diffs, accept/reject, validate
* **Durable Persistence** - SQLite database with file versioning, checkpoints, and audit logging
* **Human-in-the-Loop** - Every code change is a diff that must be accepted or rejected before applying
* **Static Validation** - Syntax checking, security pattern detection, and patch integrity verification
* **Path Security** - Path traversal prevention, blocked file extensions, safe ZIP extraction
* **Crash Recovery** - Checkpoint-based task recovery for pause/resume
* **Project Export** - ZIP import/export for project portability

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml and add your GEMINI_API_KEY

# Run the app
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

## Architecture

The system is organized into seven layers:

1. **Storage & Security** - Repository pattern (SQLite), path validation, audit logging
2. **Execution & Validation** - Static validation (Level A), isolated execution stub (Level B)
3. **Providers** - Abstract LLM interface with error normalization and retry policy
4. **Services** - Project, task, diff, checkpoint, usage, and validation services
5. **Agents** - Planner (LLM), context (deterministic), coder (targeted per-task)
6. **Workflow** - Incremental orchestrator with task state machine
7. **UI** - Streamlit workspace with project explorer, editor, chat, task panel, and diff viewer

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

## How It Works

1. **Describe** your change request in the chat panel
2. **Plan** - The planner agent creates a structured task plan with dependencies
3. **Execute** - Each task generates targeted file changes as proposed diffs
4. **Review** - Inspect diffs in the diff viewer
5. **Accept/Reject** - Accepted changes are applied and validated; rejected changes are discarded
6. **Resume** - Paused or failed tasks can be resumed via checkpoints

## Supported Providers

| Provider | Requires | Notes |
|---|---|---|
| Google Gemini | API key | Primary provider |
| DeepSeek | API key | OpenAI-compatible |
| Qwen/DashScope | API key | OpenAI-compatible |
| Ollama | Local server | No key required |

## Testing

```bash
python -m pytest tests/ -v
```

99 tests covering path security, diff creation, provider errors, retry policy, persistence, task states, static validation, archive extraction, and integration.

## Documentation

* [Architecture](docs/ARCHITECTURE.md)
* [Implementation Plan](docs/IMPLEMENTATION_PLAN.md)
* [Implementation Status](docs/IMPLEMENTATION_STATUS.md)
* [Security Model](docs/SECURITY.md)
* [Deployment Guide](docs/DEPLOYMENT.md)

## Tech Stack

* **Frontend:** Streamlit
* **Backend:** Python (async)
* **Database:** SQLite (Repository pattern, swappable)
* **LLM SDKs:** google-genai, openai (for DeepSeek/Qwen)
* **Testing:** pytest, pytest-asyncio

## License

MIT
