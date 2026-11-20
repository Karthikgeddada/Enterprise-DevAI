"""Tests for POST /export/github and services/github_export.py.

PyGithub is faked via sys.modules so the tests exercise the real export
logic (name sanitization, 422 retry, file pushing) without any network.
"""
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.api as api
from services import generation_service as gs
from services.github_export import (
    open_pull_request,
    push_project_to_github,
    sanitize_repo_name,
)


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    """The per-IP limiter is global; reset it so suite order never matters."""
    from services.guard import reset_rate_limiter

    reset_rate_limiter()
    yield
    reset_rate_limiter()


# ---------------------------------------------------------------- fakes
class FakeGithubException(Exception):
    def __init__(self, status, msg=""):
        super().__init__(msg or f"HTTP {status}")
        self.status = status


class FakeRepo:
    def __init__(self):
        self.files = []
        self.html_url = "https://github.com/testuser/fake-repo"

    def create_file(self, path, message, content, branch=None):
        self.files.append((path, message, content))


class FakeUser:
    login = "testuser"

    def __init__(self, repo, conflict_first=False):
        self.repo = repo
        self.created = []
        self.conflict_first = conflict_first

    def create_repo(self, name, **kwargs):
        self.created.append(name)
        if self.conflict_first and len(self.created) == 1:
            raise FakeGithubException(422, "name already exists")
        return self.repo


def install_fake_github(monkeypatch, user):
    mod = types.ModuleType("github")
    mod.Github = lambda token: types.SimpleNamespace(
        get_user=lambda: user
    )
    mod.GithubException = FakeGithubException
    monkeypatch.setitem(sys.modules, "github", mod)


# ------------------------------------------------------- sanitize tests
def test_sanitize_repo_name():
    assert sanitize_repo_name("My Cool Project!") == "my-cool-project"
    assert sanitize_repo_name("  spaces  ") == "spaces"
    # leading/trailing punctuation stripped; inner underscore is legal on GitHub
    assert sanitize_repo_name("_leading_..dots_") == "leading_.dots"
    assert sanitize_repo_name("") == "devteam-project"
    assert sanitize_repo_name(None) == "devteam-project"
    assert len(sanitize_repo_name("x" * 500)) == 90


# ---------------------------------------------------------- push tests
FILES = [
    {"path": "main.py", "content": "print('hi')"},
    {"path": "README.md", "content": "# hi"},
]


def test_push_creates_repo_and_pushes_all_files(monkeypatch):
    repo = FakeRepo()
    user = FakeUser(repo)
    install_fake_github(monkeypatch, user)

    result = push_project_to_github(FILES, "My App", "tok")

    assert result == {
        "repo_name": "testuser/my-app",
        "repo_url": "https://github.com/testuser/fake-repo",
    }
    assert user.created == ["my-app"]
    assert [p for p, _, _ in repo.files] == ["main.py", "README.md"]
    assert all(m.startswith("feat: add") for _, m, _ in repo.files)


def test_push_retries_with_suffix_on_name_conflict(monkeypatch):
    repo = FakeRepo()
    user = FakeUser(repo, conflict_first=True)
    install_fake_github(monkeypatch, user)

    result = push_project_to_github(FILES, "my-app", "tok")

    assert user.created == ["my-app", "my-app-2"]
    assert result["repo_name"] == "testuser/my-app-2"


# ------------------------------------------------------ endpoint tests
@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _seed_run(run_id="gh1"):
    gs._runs[run_id] = {
        "status": "completed",
        "logs": ["Run started."],
        "files": FILES,
        "prompt": "build an app",
    }


def test_export_endpoint_happy_path(client, monkeypatch):
    _seed_run()

    def fake_push(files, repo_name, token, description=""):
        assert files == FILES
        assert token == "tok"
        assert repo_name == "devteam-ai-gh1"
        return {"repo_name": "u/devteam-ai-gh1", "repo_url": "https://github.com/u/devteam-ai-gh1"}

    monkeypatch.setattr(api, "push_project_to_github", fake_push)

    r = client.post("/export/github", json={"run_id": "gh1", "token": "tok"})
    assert r.status_code == 200
    assert r.json()["repo_url"] == "https://github.com/u/devteam-ai-gh1"


def test_export_endpoint_custom_repo_name(client, monkeypatch):
    _seed_run()
    seen = {}

    def fake_push(files, repo_name, token, description=""):
        seen["repo_name"] = repo_name
        return {"repo_name": "u/x", "repo_url": "https://github.com/u/x"}

    monkeypatch.setattr(api, "push_project_to_github", fake_push)

    r = client.post(
        "/export/github",
        json={"run_id": "gh1", "repo_name": "My Cool App!", "token": "tok"},
    )
    assert r.status_code == 200
    assert seen["repo_name"] == "My Cool App!"  # sanitized server-side


def test_export_endpoint_requires_token(client, monkeypatch):
    _seed_run()
    r = client.post("/export/github", json={"run_id": "gh1"})
    assert r.status_code == 400
    assert "personal access token" in r.json()["detail"]


def test_export_endpoint_unknown_run(client):
    r = client.post("/export/github", json={"run_id": "nope", "token": "tok"})
    assert r.status_code == 404


def test_export_endpoint_maps_bad_credentials(client, monkeypatch):
    _seed_run()

    def fake_push(files, repo_name, token, description=""):
        raise Exception("401 Bad credentials")

    monkeypatch.setattr(api, "push_project_to_github", fake_push)

    r = client.post("/export/github", json={"run_id": "gh1", "token": "bad"})
    assert r.status_code == 401
    assert "rejected" in r.json()["detail"]


def test_export_endpoint_env_token_fallback(client, monkeypatch):
    _seed_run()

    def fake_push(files, repo_name, token, description=""):
        assert token == "env-tok"
        return {"repo_name": "u/x", "repo_url": "https://github.com/u/x"}

    monkeypatch.setattr(api, "push_project_to_github", fake_push)
    monkeypatch.setenv("GITHUB_TOKEN", "env-tok")

    r = client.post("/export/github", json={"run_id": "gh1"})
    assert r.status_code == 200


# ---------------------------------------------------------- PR tests
class FakeGitRef:
    def __init__(self, sha):
        self.object = types.SimpleNamespace(sha=sha)


class FakePrRepo:
    """An existing repo with commits: ref lookup, branch creation,
    per-file commits and PR creation."""
    default_branch = "main"

    def __init__(self, empty=False):
        self.empty = empty
        self.created_ref = None
        self.files = []
        self.prs = []

    def get_git_ref(self, ref):
        if self.empty:
            raise FakeGithubException(404, "no refs")
        return FakeGitRef("base-sha")

    def create_git_ref(self, ref, sha):
        self.created_ref = (ref, sha)

    def create_file(self, path, message, content, branch=None):
        self.files.append((path, content, branch))

    def create_pull(self, title, body, head, base):
        pr = types.SimpleNamespace(
            html_url=f"https://github.com/owner/repo/pull/{len(self.prs) + 1}",
            number=len(self.prs) + 1,
        )
        self.prs.append((title, body, head, base))
        return pr


class FakeGithubClient:
    def __init__(self, repo):
        self.repo = repo

    def get_repo(self, full_name):
        if full_name == "missing/nope":
            raise FakeGithubException(404, "not found")
        return self.repo


def install_fake_github_client(monkeypatch, repo):
    mod = types.ModuleType("github")
    mod.Github = lambda token: FakeGithubClient(repo)
    mod.GithubException = FakeGithubException
    monkeypatch.setitem(sys.modules, "github", mod)


def test_open_pull_request_creates_branch_files_and_pr(monkeypatch):
    repo = FakePrRepo()
    install_fake_github_client(monkeypatch, repo)

    result = open_pull_request(
        FILES, "owner/repo", "tok", pr_title="DevTeam AI: demo", pr_body="body"
    )

    assert result["pr_url"].startswith("https://github.com/owner/repo/pull/")
    assert result["repo_name"] == "owner/repo"
    ref, sha = repo.created_ref
    assert ref.startswith("refs/heads/devteam-ai/") and sha == "base-sha"
    assert [p for p, _, _ in repo.files] == ["main.py", "README.md"]
    assert all(branch.startswith("devteam-ai/") for _, _, branch in repo.files)
    title, body, head, base = repo.prs[0]
    assert title == "DevTeam AI: demo"
    assert head.startswith("devteam-ai/")
    assert base == "main"


def test_open_pull_request_empty_repo_raises_valueerror(monkeypatch):
    install_fake_github_client(monkeypatch, FakePrRepo(empty=True))
    with pytest.raises(ValueError, match="no commits yet"):
        open_pull_request(FILES, "owner/repo", "tok")


def test_open_pull_request_missing_repo_raises_valueerror(monkeypatch):
    install_fake_github_client(monkeypatch, FakePrRepo())
    with pytest.raises(ValueError, match="not found"):
        open_pull_request(FILES, "missing/nope", "tok")


def test_export_pr_endpoint_happy_path(client, monkeypatch):
    _seed_run()
    seen = {}

    def fake_pr(files, full_name, token, pr_title, pr_body):
        seen.update(full_name=full_name, title=pr_title, n=len(files))
        return {"pr_url": "https://github.com/o/r/pull/1", "pr_number": 1,
                "branch": "devteam-ai/x", "repo_name": full_name}

    monkeypatch.setattr(api, "open_pull_request", fake_pr)

    r = client.post(
        "/export/github",
        json={"run_id": "gh1", "repo_name": "owner/repo", "token": "tok", "mode": "pr"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pr_url"] == "https://github.com/o/r/pull/1"
    assert seen["full_name"] == "owner/repo"
    assert seen["n"] == len(FILES)
    assert seen["title"].startswith("DevTeam AI:")


def test_export_pr_endpoint_requires_owner_name(client):
    _seed_run()
    r = client.post(
        "/export/github",
        json={"run_id": "gh1", "repo_name": "just-a-name", "token": "tok", "mode": "pr"},
    )
    assert r.status_code == 400
    assert "owner/name" in r.json()["detail"]


def test_export_pr_endpoint_maps_valueerror(client, monkeypatch):
    _seed_run()

    def fake_pr(files, full_name, token, pr_title, pr_body):
        raise ValueError("'o/r' has no commits yet — push it as a new repo instead of a PR.")

    monkeypatch.setattr(api, "open_pull_request", fake_pr)
    r = client.post(
        "/export/github",
        json={"run_id": "gh1", "repo_name": "o/r", "token": "tok", "mode": "pr"},
    )
    assert r.status_code == 400
    assert "no commits yet" in r.json()["detail"]
