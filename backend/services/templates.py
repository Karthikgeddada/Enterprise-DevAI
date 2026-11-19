"""Prompt templates for the one-click gallery under the prompt box.

Each entry fills the prompt textarea when clicked; the pipeline treats
them exactly like hand-typed prompts. Keep prompts short and specific —
they must produce a small, complete project on free-tier models.
"""
from typing import List, Dict

PROJECT_TEMPLATES: List[Dict[str, str]] = [
    {
        "id": "todo",
        "icon": "✅",
        "name": "Todo App",
        "prompt": (
            "Build a todo list web app with a single-page HTML/CSS/JS "
            "interface. Features: add tasks, mark complete, delete, and a "
            "task counter. Persist tasks in localStorage."
        ),
    },
    {
        "id": "restapi",
        "icon": "🔌",
        "name": "REST API",
        "prompt": (
            "Build a FastAPI REST API for managing books with in-memory "
            "storage. Endpoints: list, get by id, create, update, delete. "
            "Include Pydantic models, error handling, and unit tests with "
            "pytest."
        ),
    },
    {
        "id": "landing",
        "icon": "🚀",
        "name": "Landing Page",
        "prompt": (
            "Build a modern product landing page: hero section with a "
            "headline and call-to-action, features grid, pricing table, "
            "and footer. Responsive, single HTML file with embedded CSS."
        ),
    },
    {
        "id": "dashboard",
        "icon": "📊",
        "name": "Dashboard",
        "prompt": (
            "Build an analytics dashboard web page with pure HTML/CSS/JS: "
            "a sidebar, four KPI cards, a bar chart and a line chart drawn "
            "on canvas from sample data, and a sortable data table."
        ),
    },
    {
        "id": "chat",
        "icon": "💬",
        "name": "Chat UI",
        "prompt": (
            "Build a chat application UI in a single HTML file: message "
            "list with bubbles, input box, send button, and canned bot "
            "replies (no backend needed). Clean, modern styling."
        ),
    },
    {
        "id": "cli",
        "icon": "⌨️",
        "name": "CLI Tool",
        "prompt": (
            "Build a Python CLI password generator with argparse: options "
            "for length and character sets, strength meter output, and "
            "unit tests with pytest."
        ),
    },
]


def get_templates() -> List[Dict[str, str]]:
    return PROJECT_TEMPLATES
