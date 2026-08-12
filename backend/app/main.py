"""
app/main.py  —  FastAPI application entry point
═══════════════════════════════════════════════════════════════════════════════
Start the server:
    uvicorn app.main:app --reload

Interactive docs:
    http://127.0.0.1:8000/docs
    http://127.0.0.1:8000/redoc
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env before anything that reads env vars
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.config.mongo import connect_db, close_db
from src.routes import leads_router
from src.schemas import MessageResponse
from google_maps.routes import router as google_maps_router
from people_data_labs.routes import router as pdl_router
from prospeo.routes import router as prospeo_router
from contactout.routes import router as contactout_router


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1):(5173|5174)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
# No prefix here — each route carries its full path (/leads/..., /debug/...)
app.include_router(leads_router)

# ── Google Maps leads module (isolated — does NOT touch existing pipeline) ────
app.include_router(google_maps_router)

# ── People Data Labs contact discovery (isolated — does NOT touch pipeline) ───
app.include_router(pdl_router)

# ── Prospeo people enrichment (standalone — does NOT touch existing pipeline) ─
app.include_router(prospeo_router)

# ── ContactOut people enrichment (standalone — does NOT touch existing pipeline) ─
app.include_router(contactout_router)


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
