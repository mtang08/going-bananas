from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from ipaddress import ip_address
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import calendar_models, checkin_models, coach_v2_models, fit_models, metric_models, planning_models  # noqa: F401
from app.api.anchors import router as anchors_router
from app.api.calendar import router as calendar_router
from app.api.checkins import router as checkins_router
from app.api.coach import router as coach_router
from app.api.coach_chat import get_chat_gateway
from app.api.coach_chat import router as coach_chat_router
from app.api.core import router as core_router
from app.api.exceptions import router as exceptions_router
from app.api.metrics import router as metrics_router
from app.api.planning import router as planning_router
from app.api.sync import router as sync_router
from app.api.travel import router as travel_router
from app.config import settings
from app.db import SessionLocal, get_revision, get_session, global_write_lock
from app.errors import fail
from app.logs import configure, request_error
from app.migrations_head import EXPECTED_HEAD
from app.services import derived

configure(settings.private_dir)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await get_chat_gateway().shutdown()


app = FastAPI(title="Going Bananas Analytics", docs_url=None, redoc_url=None, lifespan=lifespan)
STATUS_CODES = {404: "not_found", 405: "method_not_allowed"}
COACH_CHAT_PATH = "/api/v1/coach/chat"


def error_response(request: Request, code: str, message: str, status: int, fields=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": status >= 500,
                "request_id": getattr(request.state, "request_id", ""),
                "fields": fields or [],
            }
        },
    )


def local_peer(request: Request) -> bool:
    peer = request.client.host if request.client else ""
    if settings.app_mode == "test" and peer == "testclient":
        return True
    try:
        return ip_address(peer).is_loopback
    except ValueError:
        return False


@app.middleware("http")
async def local_security(request: Request, call_next):
    request.state.request_id = secrets.token_hex(8)
    host = request.headers.get("host", "")
    allowed_hosts = {
        f"127.0.0.1:{settings.port}",
        f"localhost:{settings.port}",
        f"127.0.0.1:{settings.vite_port}",
        f"localhost:{settings.vite_port}",
        "127.0.0.1",
        "localhost",
        "testserver",
    }
    if host not in allowed_hosts:
        return error_response(request, "invalid_host", "Local host required", 403)
    if request.url.path == COACH_CHAT_PATH or request.url.path.startswith(f"{COACH_CHAT_PATH}/"):
        if not local_peer(request) or request.headers.get("sec-fetch-site") == "cross-site":
            return error_response(request, "local_coach_required", "Local coach request required", 403)
    origin = request.headers.get("origin")
    allowed_origins = {f"http://{host}"}
    if host in {f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"}:
        allowed_origins.update({f"http://127.0.0.1:{settings.vite_port}", f"http://localhost:{settings.vite_port}"})
    if origin and origin not in allowed_origins:
        return error_response(request, "invalid_origin", "Local origin required", 403)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("x-local-request") != "1":
            return error_response(request, "csrf_header_required", "X-Local-Request: 1 required", 403)
        if request.method != "DELETE" and not request.headers.get("content-type", "").startswith("application/json"):
            return error_response(request, "json_required", "JSON body required", 415)
    try:
        response = await call_next(request)
    except Exception as exc:
        request_error(request.state.request_id, request.method, request.url.path, exc)
        return error_response(request, "internal_error", "Internal server error", 500)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(StarletteHTTPException)
async def handle_http(request: Request, exc: StarletteHTTPException):
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": STATUS_CODES.get(exc.status_code, "request_error"), "message": "Request failed"}
    )
    return error_response(
        request,
        detail.get("code", "request_error"),
        detail.get("message", "Request failed"),
        exc.status_code,
        detail.get("fields", []),
    )


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception):
    request_error(getattr(request.state, "request_id", ""), request.method, request.url.path, exc)
    return error_response(request, "internal_error", "Internal server error", 500)


@app.exception_handler(RequestValidationError)
async def handle_validation(request: Request, exc: RequestValidationError):
    fields = [{"field": ".".join(str(x) for x in err["loc"]), "message": err["msg"]} for err in exc.errors()]
    return error_response(request, "validation_error", "Invalid request fields", 422, fields)


@app.get("/api/v1/health/live")
def live():
    return {
        "schema_version": "v1",
        "mode": settings.app_mode,
        "data_revision": 0,
        "data": {"status": "ok", "dashboard_coach": True},
    }


@app.get("/api/v1/health/ready")
def ready():
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            revision = get_revision(session)
            db_version = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            if db_version != EXPECTED_HEAD:
                raise RuntimeError("migration pending")
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "schema_version": "v1",
                "mode": settings.app_mode,
                "data_revision": 0,
                "data": {"status": "unavailable", "database": False},
            },
        )
    return {
        "schema_version": "v1",
        "mode": settings.app_mode,
        "data_revision": revision,
        "data": {"status": "ok", "database": True},
    }


def serialize_source_write(request: Request, session: Session = Depends(get_session)) -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        global_write_lock(session)


derived.install()
app.include_router(core_router, prefix="/api/v1", dependencies=[Depends(serialize_source_write)])
app.include_router(anchors_router, prefix="/api/v1")
app.include_router(calendar_router, prefix="/api/v1")
app.include_router(checkins_router, prefix="/api/v1")
app.include_router(exceptions_router, prefix="/api/v1")
app.include_router(planning_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(sync_router, prefix="/api/v1")
app.include_router(travel_router, prefix="/api/v1")
app.include_router(coach_router, prefix="/api/v1")
app.include_router(coach_chat_router, prefix="/api/v1")


@app.get("/{path:path}", include_in_schema=False)
def serve_frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "API route not found"})
    dist = settings.frontend_dist
    if not dist.exists():
        fail("frontend_not_built", "Frontend not built", 404)
    if path == "phone/":
        path = "phone/index.html"
    target = (dist / path).resolve()
    if target.is_file() and target.is_relative_to(dist):
        return FileResponse(target)
    if "." not in Path(path).name and (dist / "index.html").is_file():
        return FileResponse(dist / "index.html")
    fail("not_found", "Not found", 404)
