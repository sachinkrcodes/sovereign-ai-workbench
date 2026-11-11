"""Application entry point.

Run locally:  uvicorn app.main:app --reload
Interactive API docs:  http://localhost:8000/docs"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routers import agents, audit, auth, documents, health, indexing, search, usage, users

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("started %s v%s (%s)", settings.app_name, settings.app_version, settings.environment)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Private, governed AI workbench - documents, cited answers, governed agents, roles and audit (stage 4).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Give every request an ID and log how long it took (useful later in CloudWatch)."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s -> %s in %.1fms [%s]",
        request.method, request.url.path, response.status_code, elapsed_ms, request_id,
    )
    return response


app.include_router(health.router)
app.include_router(documents.router)
app.include_router(indexing.router)
app.include_router(search.router)
app.include_router(agents.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(audit.router)
app.include_router(usage.router)


@app.get("/", tags=["health"])
def root() -> dict:
    return {"name": settings.app_name, "version": settings.app_version, "docs": "/docs"}
