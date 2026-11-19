import os
import threading
import json
from contextvars import ContextVar
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# LLM Provider Configuration
# -----------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter").lower()

# Per-run provider override (Feature 8: multi-model). set_run_provider()
# is called at run start BEFORE asyncio.create_task, so the value is
# inherited by the whole pipeline task — every agent's generate_response
# call sees it without a single agent signature change.
_run_provider: ContextVar[str] = ContextVar("run_provider", default="")


def set_run_provider(name: str) -> None:
    """Set the provider for the current run task chain; "" clears it."""
    _run_provider.set(name or "")


def get_run_provider() -> str:
    """Per-run override if set, else "" (caller falls back to LLM_PROVIDER)."""
    return _run_provider.get()


def provider_choices() -> list:
    """Provider options a client may choose per run: 'auto' plus every
    provider with credentials configured on this deployment."""
    choices = [{"id": "auto", "label": f"Auto ({LLM_PROVIDER})"}]
    if os.getenv("GEMINI_API_KEY"):
        choices.append({"id": "gemini", "label": "Gemini"})
    if os.getenv("OPENROUTER_API_KEY"):
        choices.append({"id": "openrouter", "label": "OpenRouter"})
    if os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY"):
        choices.append({"id": "groq", "label": "Groq"})
    if LLM_PROVIDER == "ollama" or os.getenv("OLLAMA_BASE_URL"):
        choices.append({"id": "ollama", "label": "Ollama (local)"})
    return choices


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")  # keep current: Google retires -latest aliases
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "llama-3.3-70b-versatile" if LLM_PROVIDER == "groq" else "llama3:8b")

# -----------------------------
# API Key Rotation (Groq only)
# -----------------------------
def _load_keys():
    raw_keys = os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY") or ""
    keys = [k.strip().strip('"').strip("'") for k in raw_keys.split(",") if k.strip()]
    return keys

API_KEYS = _load_keys()
_key_index = 0
_lock = threading.Lock()

def get_async_client():
    if LLM_PROVIDER == "openrouter":
        from openai import AsyncOpenAI
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise Exception("OPENROUTER_API_KEY is missing! Get one at https://openrouter.ai/keys and set it in your environment (or .env / Streamlit Secrets).")
        return AsyncOpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL), "openrouter"

    if LLM_PROVIDER == "ollama":
        from openai import AsyncOpenAI
        return AsyncOpenAI(
            api_key="ollama", # Ignored by Ollama
            base_url=OLLAMA_BASE_URL
        ), "ollama"
    
    # Default to Groq
    global _key_index
    if not API_KEYS:
        raise Exception("GROQ_API_KEY is missing! Please set it in Streamlit Secrets or your .env file.")
    
    with _lock:
        key = API_KEYS[_key_index]
        _key_index = (_key_index + 1) % len(API_KEYS)
    
    from groq import AsyncGroq
    return AsyncGroq(api_key=key), "groq"

async def generate_response(prompt_or_messages) -> str:
    """
    Unified ASYNC LLM generation supporting Groq (Free Tier) and Ollama (Local).
    """
    if isinstance(prompt_or_messages, str):
        messages = [{"role": "user", "content": prompt_or_messages}]
    else:
        messages = prompt_or_messages

    # Per-run override (Feature 8) falls back to the deployment default.
    provider = get_run_provider() or LLM_PROVIDER

    # For Local Ollama, we don't need failover
    if provider == "ollama":
        try:
            client, _ = get_async_client()
            response = await client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=messages,
                temperature=0.2,
                max_tokens=4096
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"Local LLM failed. Ensure Ollama is running at {OLLAMA_BASE_URL}. Original error: {str(e)}")

    # Gemini (Google - hosted, cheap flash-lite models)
    if provider == "gemini":
        from providers.gemini_provider import GeminiProvider
        from providers.base import GenerationRequest
        from providers.retry import RetryPolicy

        provider = GeminiProvider()
        # Demand spikes ("503 ... high demand") are common on the free tier;
        # bounded backoff retries them instead of failing the whole run.
        retry = RetryPolicy(max_retries=4)

        async def _gemini_call() -> str:
            response = await provider.generate(GenerationRequest(
                messages=messages,
                model=GEMINI_MODEL,
                temperature=0.2,
                max_tokens=4096,
            ))
            return response.content

        try:
            return await retry.execute_with_retry(_gemini_call)
        except Exception as e:
            raise Exception(f"Gemini API error: {str(e)}")  # same error surface as before

    # OpenRouter (default): one key, many models
    if provider == "openrouter":
        from providers.errors import ProviderError, classify_error
        from providers.retry import RetryPolicy

        retry = RetryPolicy(max_retries=4)

        async def _openrouter_call() -> str:
            try:
                client, _ = get_async_client()
                response = await client.chat.completions.create(
                    model=OPENROUTER_MODEL,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=4096
                )
                return response.choices[0].message.content
            except ProviderError:
                raise
            except Exception as e:
                raise classify_error(e)  # normalize so retryability applies

        try:
            return await retry.execute_with_retry(_openrouter_call)
        except Exception as e:
            raise Exception(f"OpenRouter API error: {str(e)}")  # same error surface as before

    # Groq Key Failover Logic
    last_error = "Unknown error"
    
    for _ in range(max(1, len(API_KEYS))):
        try:
            client, _ = get_async_client()
            response = await client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=messages,
                temperature=0.2,
                max_tokens=3500
            )
            return response.choices[0].message.content
        except Exception as e:
            last_error = str(e)
            print(f"API Attempt failed: {last_error}")
            if "invalid_api_key" in last_error.lower() or "401" in last_error or "organization_restricted" in last_error.lower() or "rate_limit" in last_error.lower() or "connection" in last_error.lower():
                continue
            raise Exception(f"Groq API Error: {last_error}")
            
    raise Exception(f"Groq API Error: {last_error}")
