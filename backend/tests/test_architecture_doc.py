"""Tests for architect output -> ARCHITECTURE.md/.mmd project files.

The architect is now prompted to include a Mermaid diagram; the pipelines
extract it into ARCHITECTURE.mmd (rendered live by the frontend) and keep the
full design text in ARCHITECTURE.md. No mermaid block -> no extra files, so
any model degrades gracefully and engine parity is preserved.
"""
from agents.architect_agent import architecture_files, extract_mermaid_diagram
from services.generation_service import _dedupe_files

ARCH_TEXT = """Folder tree:
- app/
  - main.py

Modules:
- app: entry point

```mermaid
graph TD
    A[app] --> B[(SQLite)]
    A --> C[API]
```
"""


def test_extracts_first_mermaid_block():
    d = extract_mermaid_diagram(ARCH_TEXT)
    assert d is not None
    assert "graph TD" in d
    assert "SQLite" in d


def test_no_block_returns_none():
    assert extract_mermaid_diagram("no diagram here") is None
    assert extract_mermaid_diagram("") is None
    assert extract_mermaid_diagram(None) is None


def test_architecture_files_md_and_mmd():
    files = architecture_files(ARCH_TEXT)
    assert [f["path"] for f in files] == ["ARCHITECTURE.md", "ARCHITECTURE.mmd"]
    assert "graph TD" in files[1]["content"]
    assert "Folder tree" in files[0]["content"]


def test_architecture_files_empty_without_diagram():
    assert architecture_files("plain text, no diagram") == []


def test_dedupe_files_first_occurrence_wins():
    files = [
        {"path": "ARCHITECTURE.md", "content": "new"},
        {"path": "main.py", "content": "code"},
        {"path": "ARCHITECTURE.md", "content": "old-copy"},
    ]
    deduped = _dedupe_files(files)
    assert [f["path"] for f in deduped] == ["ARCHITECTURE.md", "main.py"]
    assert deduped[0]["content"] == "new"
