"""
src/config/settings.py
───────────────────────
Central application configuration.

All values are read from environment variables (case-insensitive).
Defaults make the app runnable out-of-the-box with no .env file.

Usage anywhere in the codebase:
    from src.config import settings
    print(settings.APP_NAME)
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Every environment variable the app needs is declared here.
    Pydantic-settings automatically reads from:
      1. The OS environment
      2. The .env file specified in Config.env_file

    Add new variables as fields and they become available project-wide
    via the shared `settings` singleton at the bottom of this file.
    """

    # ── Application ───────────────────────────────────────────────────────────
    APP_NAME:    str  = "Lead Generation CRM"
    APP_VERSION: str  = "1.0.0"
    DEBUG:       bool = True

    # ── Server ────────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins.
    # Default covers the Vite dev server on both localhost variants.
    CORS_ORIGINS: str = (
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:5174,"
        "http://127.0.0.1:5174"
    )

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGODB_URI:   str = "mongodb://127.0.0.1:27017/crm"
    MONGO_DB_NAME: str = "crm"

    # ── Future: Hermes AI ─────────────────────────────────────────────────────
    # HERMES_API_KEY: str = ""
    # HERMES_API_URL: str = "https://api.hermes.ai/v1"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS string → list of stripped origin strings."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file         = ".env"
        env_file_encoding = "utf-8"
        # Allow extra fields in .env without raising validation errors
        extra = "ignore"


# ── Shared singleton ──────────────────────────────────────────────────────────
# Import this object everywhere — do NOT instantiate Settings() again.
settings = Settings()
