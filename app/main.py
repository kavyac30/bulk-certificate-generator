"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import init_db
from app.routers import jobs
from app.services.dispatcher import recover_unfinished_jobs, shutdown_executor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.processing_mode == "background":
        recover_unfinished_jobs()
    yield
    shutdown_executor()


app = FastAPI(
    title="Bulk Certificate Generator",
    description="Submit many recipients in one request; certificates are generated in the "
    "background. Track progress and download PDFs / a ZIP.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(jobs.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
