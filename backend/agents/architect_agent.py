import re
from typing import List, Optional

from config.llm_config import generate_response

_MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_mermaid_diagram(text: str) -> Optional[str]:
    """Return the first ```mermaid fenced block from architect output."""
    if not text:
        return None
    m = _MERMAID_RE.search(text)
    if not m:
        return None
    diagram = m.group(1).strip()
    return diagram or None


def architecture_files(text: str) -> List[dict]:
    """Run files for the architecture stage: the full design doc plus the
    Mermaid diagram as a standalone .mmd the frontend renders live.

    Returns [] when the architect produced no mermaid block, so any model,
    any run, degrades gracefully to no extra files.
    """
    diagram = extract_mermaid_diagram(text)
    if not diagram:
        return []
    return [
        {"path": "ARCHITECTURE.md", "content": text.strip() + "\n"},
        {"path": "ARCHITECTURE.mmd", "content": diagram + "\n"},
    ]


async def architect_agent(prompt: str, requirements: str) -> str:
    system_prompt = f"""You are the Architect Agent.
Based on the user's prompt and the extracted requirements, design the project structure, modules, dependencies, and folder tree.
Provide the folder structure and a brief description of each module.

Finally, include a Mermaid diagram of the system in a fenced code block tagged "mermaid" (use "graph TD" or "flowchart TD" with named components and arrows for their relationships). Keep the diagram under 20 lines.

User Prompt: {prompt}
Requirements: {requirements}
"""
    return await generate_response(system_prompt)
