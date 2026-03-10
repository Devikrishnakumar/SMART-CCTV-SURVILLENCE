import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine, AsyncSessionLocal
from app.models import Base
from app.utils.seed import seed_admin
from app.routes import auth, cameras, incidents, ai
from app.routes.websocket import router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up Emergency Dispatch API...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        await seed_admin(db)
    logger.info("Database ready.")
    yield
    # Shutdown
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Emergency Detection & Dispatch API",
    description=(
        "Production-ready backend for AI-powered emergency detection. "
        "Receives YOLO detections, manages incidents, dispatches services, "
        "and streams real-time alerts via WebSocket."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routes ──────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(incidents.router)
app.include_router(ai.router)
app.include_router(ws_router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": "emergency-dispatch-api"}


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse({"message": "Emergency Dispatch API", "docs": "/docs"})
