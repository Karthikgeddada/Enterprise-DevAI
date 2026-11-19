import pytest
import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from providers.base import BaseProvider, GenerationRequest, GenerationResponse, ModelInfo
from providers.errors import ProviderError, ErrorCategory, classify_error
from providers.retry import RetryPolicy
from storage.sqlite_repository import SQLiteRepository
from services.project_service import ProjectService


class MockProvider(BaseProvider):
    """Mock provider for deterministic testing."""

    def __init__(self, response_content='{"tasks": []}', usage=None, fail_count=0):
        self._response_content = response_content
        self._usage = usage or {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        self._fail_count = fail_count
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def display_name(self) -> str:
        return "Mock Provider"

    def is_available(self) -> bool:
        return True

    def get_models(self):
        return [ModelInfo(id="mock-model", name="Mock Model", provider="mock", supports_structured=True)]

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise ProviderError("Simulated failure", ErrorCategory.RATE_LIMIT, retryable=True)
        return GenerationResponse(
            content=self._response_content,
            model=request.model,
            provider=self.name,
            usage=self._usage,
            finish_reason="stop",
        )

    async def stream_generate(self, request: GenerationRequest):
        yield self._response_content


class TestMockProvider:
    def test_mock_provider_available(self):
        p = MockProvider()
        assert p.is_available()
        assert p.name == "mock"

    def test_mock_provider_models(self):
        p = MockProvider()
        models = p.get_models()
        assert len(models) == 1
        assert models[0].id == "mock-model"

    def test_mock_provider_generate(self):
        p = MockProvider(response_content='{"tasks": [{"title": "T1"}]}')
        req = GenerationRequest(messages=[{"role": "user", "content": "test"}], model="mock-model")
        resp = asyncio.run(p.generate(req))
        assert resp.content == '{"tasks": [{"title": "T1"}]}'
        assert resp.provider == "mock"
        assert resp.usage["total_tokens"] == 30

    def test_mock_provider_stream(self):
        p = MockProvider(response_content="chunk1")
        req = GenerationRequest(messages=[{"role": "user", "content": "test"}], model="mock-model")

        async def collect():
            chunks = []
            async for c in p.stream_generate(req):
                chunks.append(c)
            return chunks

        chunks = asyncio.run(collect())
        assert chunks == ["chunk1"]

    def test_mock_provider_cost_estimation(self):
        p = MockProvider()
        cost = p.estimate_cost("mock-model", 1000, 2000)
        assert cost == 0.0  # No pricing set on mock


class TestProviderWithRetry:
    def test_retry_succeeds_after_failures(self):
        p = MockProvider(fail_count=2)
        req = GenerationRequest(messages=[{"role": "user", "content": "test"}], model="mock-model")
        retry = RetryPolicy(max_retries=3, base_delay=0.01)

        async def _call():
            return await p.generate(req)

        resp = asyncio.run(retry.execute_with_retry(_call))
        assert resp.content == '{"tasks": []}'
        assert p._call_count == 3  # 2 failures + 1 success

    def test_retry_exhausts_on_persistent_failure(self):
        p = MockProvider(fail_count=10)
        req = GenerationRequest(messages=[{"role": "user", "content": "test"}], model="mock-model")
        retry = RetryPolicy(max_retries=2, base_delay=0.01)

        async def _call():
            return await p.generate(req)

        with pytest.raises(ProviderError) as exc_info:
            asyncio.run(retry.execute_with_retry(_call))
        assert exc_info.value.category == ErrorCategory.RATE_LIMIT

    def test_non_retryable_error_not_retried(self):
        p = MockProvider()
        req = GenerationRequest(messages=[{"role": "user", "content": "test"}], model="mock-model")
        retry = RetryPolicy(max_retries=3, base_delay=0.01)
        call_count = 0

        async def _call():
            nonlocal call_count
            call_count += 1
            raise ProviderError("Auth error", ErrorCategory.AUTH_ERROR, retryable=False)

        with pytest.raises(ProviderError):
            asyncio.run(retry.execute_with_retry(_call))
        assert call_count == 1  # No retries


class TestMissingCredentials:
    def test_gemini_without_key_raises_auth_error(self):
        from providers.gemini_provider import GeminiProvider
        os.environ.pop('GEMINI_API_KEY', None)
        p = GeminiProvider(api_key=None)
        assert not p.is_available()
        req = GenerationRequest(messages=[{"role": "user", "content": "test"}], model="gemini-2.0-flash")
        with pytest.raises(ProviderError) as exc_info:
            asyncio.run(p.generate(req))
        assert exc_info.value.category == ErrorCategory.AUTH_ERROR

    def test_deepseek_without_key_not_available(self):
        from providers.deepseek_provider import DeepSeekProvider
        os.environ.pop('DEEPSEEK_API_KEY', None)
        p = DeepSeekProvider(api_key=None)
        assert not p.is_available()

    def test_qwen_without_key_not_available(self):
        from providers.qwen_provider import QwenProvider
        os.environ.pop('QWEN_API_KEY', None)
        p = QwenProvider(api_key=None)
        assert not p.is_available()

    def test_ollama_always_registered(self):
        from providers.ollama_provider import OllamaProvider
        p = OllamaProvider()
        # Ollama doesn't require an API key, just a server
        assert p.name == "ollama"


class TestFileSearchAndRename:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.projects_dir = os.path.join(self.tmpdir, "projects")
        os.environ['DEVTEAM_DB_PATH'] = self.db_path
        os.environ['DEVTEAM_PROJECTS_DIR'] = self.projects_dir
        os.makedirs(self.projects_dir, exist_ok=True)
        self.repo = SQLiteRepository(self.db_path)
        self.project_service = ProjectService(self.repo)

    def test_search_files(self):
        project = self.project_service.create_project("Test", "Search test")
        self.project_service.save_file(project.id, "src/main.py", "print(1)")
        self.project_service.save_file(project.id, "src/utils.py", "def util(): pass")
        self.project_service.save_file(project.id, "README.md", "# README")

        results = self.project_service.search_files(project.id, "main")
        assert len(results) == 1
        assert results[0]['path'] == 'src/main.py'

        results = self.project_service.search_files(project.id, ".py")
        assert len(results) == 2

        results = self.project_service.search_files(project.id, "readme")
        assert len(results) == 1
        assert results[0]['path'] == 'README.md'

    def test_rename_file(self):
        project = self.project_service.create_project("Test", "Rename test")
        self.project_service.save_file(project.id, "old_name.py", "print('hello')")

        self.project_service.rename_file(project.id, "old_name.py", "new_name.py")

        assert self.project_service.get_file(project.id, "new_name.py") == "print('hello')"
        assert self.project_service.get_file(project.id, "old_name.py") is None or self.project_service.get_file(project.id, "old_name.py") == ''

    def test_rename_file_preserves_content(self):
        project = self.project_service.create_project("Test", "Rename test")
        content = "def hello():\n    return 'world'\n"
        self.project_service.save_file(project.id, "module.py", content)

        self.project_service.rename_file(project.id, "module.py", "src/module.py")

        assert self.project_service.get_file(project.id, "src/module.py") == content


class TestUsageServiceIntegration:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.projects_dir = os.path.join(self.tmpdir, "projects")
        os.environ['DEVTEAM_DB_PATH'] = self.db_path
        os.environ['DEVTEAM_PROJECTS_DIR'] = self.projects_dir
        os.makedirs(self.projects_dir, exist_ok=True)
        self.repo = SQLiteRepository(self.db_path)
        self.project_service = ProjectService(self.repo)

    def test_record_and_retrieve_usage(self):
        from services.usage_service import UsageService
        usage_service = UsageService(self.repo)

        project = self.project_service.create_project("Test", "Usage test")
        record = usage_service.record_usage(
            project_id=project.id, provider="gemini", model="gemini-2.0-flash",
            prompt_tokens=100, completion_tokens=200, total_tokens=300,
            latency_ms=500.0,
        )
        assert record.id is not None
        assert record.estimated_cost >= 0.0  # Cost calculated from registry pricing

        records = usage_service.get_usage(project.id)
        assert len(records) == 1
        assert records[0].prompt_tokens == 100

        summary = usage_service.get_usage_summary(project.id)
        assert summary['total_requests'] == 1
        assert summary['total_tokens'] == 300
        assert summary['avg_latency_ms'] == 500.0

    def test_usage_summary_multiple_records(self):
        from services.usage_service import UsageService
        usage_service = UsageService(self.repo)

        project = self.project_service.create_project("Test", "Usage test")
        for i in range(5):
            usage_service.record_usage(
                project_id=project.id, provider="gemini", model="gemini-2.0-flash",
                prompt_tokens=10 * i, completion_tokens=20 * i, total_tokens=30 * i,
                latency_ms=100.0 * (i + 1),
            )

        summary = usage_service.get_usage_summary(project.id)
        assert summary['total_requests'] == 5
        assert summary['total_tokens'] == sum(30 * i for i in range(5))
        assert 'gemini' in summary['by_provider']
        assert summary['by_provider']['gemini']['requests'] == 5