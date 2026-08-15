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
    PORT: int = 8002

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins.
    # Development default covers Vite dev server on localhost variants.
    # Production: add your deployed frontend origin, e.g.:
    #   CORS_ORIGINS=https://yourapp.vercel.app,https://www.yourdomain.com
    CORS_ORIGINS: str = (
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:5174,"
        "http://127.0.0.1:5174"
    )

    # ── MongoDB ───────────────────────────────────────────────────────────────
    # Set MONGODB_URI in .env to your MongoDB Atlas connection string:
    #   MONGODB_URI=mongodb+srv://<user>:<pass>@cluster0.iuq2qov.mongodb.net/crm?appName=Cluster0
    #
    # The default below is intentionally empty so the app fails fast if MONGODB_URI
    # is not set, rather than silently connecting to a local instance.
    # src/config/mongo.py handles the actual connection using os.getenv("MONGODB_URI").
    MONGODB_URI:   str = ""
    MONGO_DB_NAME: str = "crm"

    # ── Public Form Base URL ──────────────────────────────────────────────────
    # The base URL where the FRONTEND is publicly accessible.
    # Used to generate shareable public form links that work from any device.
    #
    # Development (local Wi-Fi):
    #   PUBLIC_FORM_BASE_URL=http://YOUR_LOCAL_IP:5173
    # Production:
    #   PUBLIC_FORM_BASE_URL=https://YOUR-FRONTEND-DOMAIN.com
    #
    # When not set, falls back to the incoming request base_url (backend URL).
    # That fallback works locally but not in production — always set this in prod.
    PUBLIC_FORM_BASE_URL: str = ""

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
