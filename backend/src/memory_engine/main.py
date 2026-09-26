"""FastAPI application entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from memory_engine import __version__
from memory_engine.api.v1.router import api_router
from memory_engine.api.v2.router import api_v2_router
from memory_engine.api.aml.router import aml_router
from memory_engine.config import get_settings
from memory_engine.core.exceptions import ValidationError
from memory_engine.core.user_api_errors import UserApiError
from memory_engine.schemas.user_api_response import user_api_error
from memory_engine.consumers.runner import start_kafka_consumers, stop_kafka_consumers
from memory_engine.integrations.qdrant_index_queue import (
    start_qdrant_index_worker,
    stop_qdrant_index_worker,
)
from memory_engine.integrations import qdrant_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("MongoDB config: %s", settings.mongodb_startup_diag())
    if not settings.mongodb_has_credentials:
        logger.error(
            "MongoDB has no credentials (MONGODB_USER/MONGODB_PASSWORD not in Pod?). "
            "Add them to the API Deployment environment variables."
        )

    def _ping_mongo() -> None:
        from pymongo import MongoClient

        client = MongoClient(settings.mongodb_dsn, serverSelectionTimeoutMS=8000)
        client.admin.command("ping")

    try:
        await asyncio.to_thread(_ping_mongo)
        logger.info("MongoDB ping ok")
    except Exception as exc:
        logger.error(
            "MongoDB ping failed (%s). Check MONGODB_URI (no embedded wrong password), "
            "MONGODB_USER, MONGODB_PASSWORD, MONGODB_AUTH_SOURCE in the pipeline.",
            exc,
        )

    logger.info("Qdrant config: %s", settings.qdrant_startup_diag())
    qdrant_ok, qdrant_err = await qdrant_store.ping_qdrant()
    if qdrant_ok:
        logger.info("Qdrant ping ok")
    else:
        logger.error(
            "Qdrant ping failed (%s). Check QDRANT_URL (cluster-internal :6333 or https ingress), "
            "QDRANT_API_KEY, and network policy. Vector index will be skipped until reachable.",
            qdrant_err,
        )

    start_qdrant_index_worker()
    try:
        await start_kafka_consumers()
    except Exception:
        logger.warning("Kafka consumers not started (is Kafka running?)")
    yield
    await stop_kafka_consumers()
    await stop_qdrant_index_worker()


app = FastAPI(title="MemoryEngine", version=__version__, lifespan=lifespan)


@app.exception_handler(UserApiError)
async def user_api_error_handler(_request: Request, exc: UserApiError) -> JSONResponse:
    body = user_api_error(exc.res_code, exc.res_message)
    return JSONResponse(status_code=200, content=body.model_dump())


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if request.url.path.startswith("/api/v1/data/user/"):
        msg = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg', '')}"
            for err in exc.errors()[:3]
        )
        body = user_api_error("ILLEGAL_ARGUMENT", msg or "参数不合法")
        return JSONResponse(status_code=200, content=body.model_dump())
    if request.url.path.startswith("/api/v1/memory/candidates/"):
        safe_errors = [
            {
                "location": ".".join(str(part) for part in error.get("loc", ())),
                "type": error.get("type", ""),
                "message": error.get("msg", ""),
            }
            for error in exc.errors()
        ]
        logger.warning(
            "Memory candidate request validation failed: path=%s errors=%s",
            request.url.path,
            safe_errors,
        )
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


@app.exception_handler(ValidationError)
async def candidate_validation_error_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    if request.url.path.startswith("/api/v1/memory/candidates/"):
        logger.warning(
            "Memory candidate request rejected: path=%s detail=%s",
            request.url.path,
            exc.detail,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(api_v2_router)
app.include_router(aml_router)


def _mongo_ping_sync() -> tuple[bool, str]:
    """Return (ok, error_message) for MongoDB admin ping."""
    from pymongo import MongoClient

    settings = get_settings()
    try:
        client = MongoClient(settings.mongodb_dsn, serverSelectionTimeoutMS=8000)
        client.admin.command("ping")
        return True, ""
    except Exception as exc:
        return False, str(exc)[:300]


@app.get("/health")
async def health(mongo: bool = False, qdrant: bool = False) -> dict[str, str | bool]:
    """Liveness; ``?mongo=1`` / ``?qdrant=1`` add dependency checks (no secrets)."""
    out: dict[str, str | bool] = {"status": "ok", "version": __version__}
    if mongo:
        settings = get_settings()
        out["mongo"] = settings.mongodb_startup_diag()
        out["mongo_creds_ok"] = settings.mongodb_has_credentials
        ok, err = await asyncio.to_thread(_mongo_ping_sync)
        out["mongo_ping_ok"] = ok
        if not ok:
            out["mongo_ping_error"] = err
    if qdrant:
        settings = get_settings()
        out["qdrant"] = settings.qdrant_startup_diag()
        out["qdrant_configured"] = bool(settings.qdrant_url)
        ok, err = await qdrant_store.ping_qdrant(record_failure=False)
        out["qdrant_ping_ok"] = ok
        if not ok:
            out["qdrant_ping_error"] = err
    return out
