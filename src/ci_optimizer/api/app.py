"""FastAPI application setup."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ci_optimizer.api.routes import router
from ci_optimizer.db.database import init_db

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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
