import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application configuration. Reads from env vars and Streamlit Secrets."""

    # Storage
    DB_PATH: str = os.getenv("DEVTEAM_DB_PATH", "data/devteam.db")
    PROJECTS_DIR: str = os.getenv("DEVTEAM_PROJECTS_DIR", "data/projects")
    AUDIT_LOG: str = os.getenv("DEVTEAM_AUDIT_LOG", "data/audit.log")

    # Provider defaults
    DEFAULT_PROVIDER: str = os.getenv("DEFAULT_PROVIDER", "gemini")
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gemini-2.0-flash")

    # Retry
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_BASE_DELAY: float = float(os.getenv("RETRY_BASE_DELAY", "1.0"))
    RETRY_MAX_DELAY: float = float(os.getenv("RETRY_MAX_DELAY", "30.0"))

    # Validation
    ENABLE_STATIC_VALIDATION: bool = os.getenv("ENABLE_STATIC_VALIDATION", "true").lower() == "true"
    ENABLE_CODE_EXECUTION: bool = os.getenv("ENABLE_CODE_EXECUTION", "false").lower() == "true"

    # Security
    MAX_PROJECT_SIZE: int = int(os.getenv("MAX_PROJECT_SIZE", str(50 * 1024 * 1024)))
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(10 * 1024 * 1024)))

    # UI
    APP_TITLE: str = "DevTeam AI - Coding Workspace"
    APP_ICON: str = "\U0001f680"

    @classmethod
    def get_secret(cls, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a value from the environment (or .env file)."""
        return os.getenv(key, default)

    @classmethod
    def get_data_dir(cls) -> str:
        """Ensure data directory exists and return its path."""
        os.makedirs("data", exist_ok=True)
        os.makedirs(cls.PROJECTS_DIR, exist_ok=True)
        return "data"


settings = Settings()