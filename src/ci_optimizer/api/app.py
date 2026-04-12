"""FastAPI application setup."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ci_optimizer.api.routes import router
from ci_optimizer.db.database import init_db

load_dotenv()

# Configure logging so background task output (from logger.info in
# _run_analysis_task, engines, prefetch, etc.) is visible in the uvicorn
# console. Uvicorn does not touch non-uvicorn loggers by default, so we
# attach a stream handler to the ci_optimizer namespace.
_LOG_LEVEL = os.getenv("CI_AGENT_LOG_LEVEL", "INFO").upper()
_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
_ci_logger = logging.getLogger("ci_optimizer")
if not any(isinstance(h, logging.StreamHandler) for h in _ci_logger.handlers):
    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_log_formatter)
    _ci_logger.addHandler(_stream_handler)
_ci_logger.setLevel(_LOG_LEVEL)
_ci_logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Preload the skill registry singleton so the first request doesn't pay the scan cost.
    from ci_optimizer.agents.skill_registry import get_registry

    skills = get_registry().get_active_skills()
    logging.getLogger("ci_optimizer").info(
        "Skill registry loaded: %d active skill(s): %s",
        len(skills),
        [s.name for s in skills],
    )
    yield


app = FastAPI(
    title="CI Agent",
    description="AI-powered GitHub CI pipeline analyzer and optimizer",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: configurable via CORS_ORIGINS env var (comma-separated)
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["health"])
async def health():
    """Liveness / readiness probe endpoint."""
    return {"status": "ok"}
