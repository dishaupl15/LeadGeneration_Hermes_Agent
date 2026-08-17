"""
app/main.py  —  FastAPI application entry point
═══════════════════════════════════════════════════════════════════════════════
Start the server (always binds to 0.0.0.0 so it's reachable from the network):
    uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

Or use the launcher shortcut:
    python run.py

Interactive docs:
    http://localhost:8002/docs
    http://10.YOUR.IP:8002/docs
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env before anything that reads env vars
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.config.mongo import connect_db, close_db
from src.routes import leads_router, history_router
from src.routes.form_leads import admin_router as form_leads_admin_router
from src.routes.form_leads import public_router as form_leads_public_router
from src.schemas import MessageResponse
from google_maps.routes import router as google_maps_router
from people_data_labs.routes import router as pdl_router
from prospeo.routes import router as prospeo_router
from contactout.routes import router as contactout_router
from origami.routes import router as origami_router
from hunter.routes import router as hunter_router


# ── Lifespan: connect DB on startup, close on shutdown ───────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()   # ← opens Motor connection; prints "✅ Connected to MongoDB"
    yield
    await close_db()     # ← closes connection on graceful shutdown


# ── Application factory ───────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Backend API for **LeadCRM** — AI-powered B2B lead generation.\n\n"
        "| Phase | Status | Description |\n"
        "|-------|--------|-------------|\n"
        "| 1 | ✅ Live | Core REST API · MongoDB persistence · dummy lead generation |\n"
        "| 2 | 🔜 Soon | Hermes AI enrichment |"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── CORS middleware ───────────────────────────────────────────────────────────
# Origins are controlled entirely by CORS_ORIGINS in .env.
# Development default: localhost:5173/5174
# Production: add your deployed frontend origin to CORS_ORIGINS in backend/.env
#   e.g. CORS_ORIGINS=https://yourapp.vercel.app,https://www.yourdomain.com
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
# No prefix here — each route carries its full path (/leads/..., /debug/...)
app.include_router(leads_router)

# ── Generation History ────────────────────────────────────────────────────────
app.include_router(history_router)

# ── Form Leads (Social Lead Collection) ──────────────────────────────────────
app.include_router(form_leads_admin_router)
app.include_router(form_leads_public_router)

# ── Social Leads dashboard (Phase 2) ─────────────────────────────────────────
from src.routes.social_leads import router as social_leads_router
app.include_router(social_leads_router)

# ── Google Maps leads module (isolated — does NOT touch existing pipeline) ────
app.include_router(google_maps_router)

# ── People Data Labs contact discovery (isolated — does NOT touch pipeline) ───
app.include_router(pdl_router)

# ── Prospeo people enrichment (standalone — does NOT touch existing pipeline) ─
app.include_router(prospeo_router)

# ── ContactOut people enrichment (standalone — does NOT touch existing pipeline) ─
app.include_router(contactout_router)

# ── Origami people enrichment (standalone — does NOT touch existing pipeline) ──
# To remove: delete this line + the import above + the origami/ folder
app.include_router(origami_router)

# ── Hunter.io email finder (standalone — does NOT touch existing pipeline) ────
# Provides: GET /hunter/health  POST /hunter/email-finder  POST /hunter/domain-search
app.include_router(hunter_router)

# ── Reddit lead generation (standalone — does NOT touch Google Maps pipeline) ─
# To remove: delete backend/reddit/, this block, and the Reddit UI in the frontend
from reddit.routes import router as reddit_router  # noqa: E402
app.include_router(reddit_router)


# ── Health endpoints ──────────────────────────────────────────────────────────

@app.get("/", response_model=MessageResponse, summary="Root health check", tags=["Health"])
def root():
    return {"message": "Lead Generation Backend Running"}


@app.get("/health", response_model=dict, summary="Detailed health status", tags=["Health"])
def health():
    return {
        "status":  "ok",
        "app":     settings.APP_NAME,
        "version": settings.APP_VERSION,
        "debug":   settings.DEBUG,
    }


# ── Dev runner ────────────────────────────────────────────────────────────────
# Run directly:  python -m app.main
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
