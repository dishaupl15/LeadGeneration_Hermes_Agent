"""
Application configuration.
All settings are read from environment variables (with fallback defaults).
The .env file is loaded automatically by python-dotenv via load_dotenv()
called in main.py.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Central settings object.  Add new env variables here as the project grows.
    Each field maps 1-to-1 to a key in .env (case-insensitive).
    """

    # ── Server ────────────────────────────────────────────────────────────────
    APP_NAME: str = "Lead Generation CRM"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins (no spaces around commas)
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://localhost:5174," 
        "http://127.0.0.1:5173,http://127.0.0.1:5174"
    )

    # ── Future integrations (placeholders) ────────────────────────────────────
    # MONGO_URI: str = ""
    # HERMES_API_KEY: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS_ORIGINS as a Python list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Single shared instance — import this everywhere
settings = Settings()
