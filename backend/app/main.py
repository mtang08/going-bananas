from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import calendar_models, checkin_models, coach_v2_models, fit_models, metric_models, planning_models  # noqa: F401
from app.api.agent import router as agent_router
from app.api.anchors import router as anchors_router
from app.api.calendar import router as calendar_router
from app.api.checkins import router as checkins_router
from app.api.coach import router as coach_router
from app.api.coaching import router as coaching_router
from app.api.core import router as core_router
from app.api.history import router as history_router
from app.api.metrics import router as metrics_router
from app.api.planning import router as planning_router
from app.api.strength import router as strength_router
from app.api.sync import router as sync_router
from app.config import settings
from app.db import SessionLocal, get_revision, get_session
from app.metrics.engine import install_triggers
from app.migrations_head import EXPECTED_HEAD
from app.models import AppState

app = FastAPI(title='Going Bananas Analytics', docs_url=None, redoc_url=None)


def error_response(request: Request, code: str, message: str, status: int, fields=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message,
        'retryable': status >= 500, 'request_id': getattr(request.state, 'request_id', ''),
        'fields': fields or []}})


@app.middleware('http')
async def local_security(request: Request, call_next):
    request.state.request_id = secrets.token_hex(8)
    host = request.headers.get('host', '')
    allowed_hosts = {f'127.0.0.1:{settings.port}', f'localhost:{settings.port}',
                     f'127.0.0.1:{settings.vite_port}', f'localhost:{settings.vite_port}',
                     '127.0.0.1', 'localhost', 'testserver'}
    if host not in allowed_hosts:
        return error_response(request, 'invalid_host', 'Local host required', 403)
    origin = request.headers.get('origin')
    allowed_origins = {f'http://{host}'}
    if host in {f'127.0.0.1:{settings.port}', f'localhost:{settings.port}'}:
        allowed_origins.update({f'http://127.0.0.1:{settings.vite_port}', f'http://localhost:{settings.vite_port}'})
    if origin and origin not in allowed_origins:
        return error_response(request, 'invalid_origin', 'Local origin required', 403)
    if request.method in {'POST','PUT','PATCH','DELETE'}:
        if request.headers.get('x-local-request') != '1':
            return error_response(request, 'csrf_header_required', 'X-Local-Request: 1 required', 403)
        if request.method != 'DELETE' and not request.headers.get('content-type','').startswith('application/json'):
            return error_response(request, 'json_required', 'JSON body required', 415)
    try:
        response = await call_next(request)
    except Exception:
        return error_response(request, 'internal_error', 'Internal server error', 500)
    response.headers['X-Request-ID'] = request.state.request_id
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(HTTPException)
async def handle_http(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {'code':'request_error','message':'Request failed'}
    return error_response(request, detail.get('code','request_error'), detail.get('message','Request failed'), exc.status_code, detail.get('fields', []))


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception):
    return error_response(request, 'internal_error', 'Internal server error', 500)


@app.exception_handler(RequestValidationError)
async def handle_validation(request: Request, exc: RequestValidationError):
    fields = [{'field': '.'.join(str(x) for x in err['loc']), 'message': err['msg']} for err in exc.errors()]
    return error_response(request, 'validation_error', 'Invalid request fields', 422, fields)


@app.get('/api/v1/health/live')
def live():
    return {'schema_version':'v1','mode':settings.app_mode,'data_revision':0,'data':{'status':'ok'}}


@app.get('/api/v1/health/ready')
def ready():
    try:
        with SessionLocal() as session:
            session.execute(text('SELECT 1'))
            revision = get_revision(session)
            db_version = session.execute(text('SELECT version_num FROM alembic_version')).scalar_one_or_none()
            if db_version != EXPECTED_HEAD:
                raise RuntimeError('migration pending')
    except Exception:
        return JSONResponse(status_code=503, content={'schema_version':'v1','mode':settings.app_mode,
            'data_revision':0,'data':{'status':'unavailable','database':False}})
    return {'schema_version':'v1','mode':settings.app_mode,'data_revision':revision,
            'data':{'status':'ok','database':True}}


def serialize_source_write(request: Request, session: Session = Depends(get_session)) -> None:
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        if session.scalar(select(AppState.planning_authority).where(AppState.id == 1)) == 'calendar':
            session.execute(text('SELECT pg_advisory_xact_lock(71382413)'))


install_triggers()
app.include_router(core_router, prefix='/api/v1', dependencies=[Depends(serialize_source_write)])
app.include_router(history_router, prefix='/api/v1')
app.include_router(anchors_router, prefix='/api/v1')
app.include_router(calendar_router, prefix='/api/v1')
app.include_router(checkins_router, prefix='/api/v1')
app.include_router(planning_router, prefix='/api/v1')
app.include_router(metrics_router, prefix='/api/v1')
app.include_router(sync_router, prefix='/api/v1')
app.include_router(coaching_router, prefix='/api/v1')
app.include_router(coach_router, prefix='/api/v1')
app.include_router(agent_router, prefix='/api/v1')
app.include_router(strength_router, prefix='/api/v1', dependencies=[Depends(serialize_source_write)])


@app.get('/{path:path}', include_in_schema=False)
def serve_frontend(path: str):
    if path.startswith('api/'):
        raise HTTPException(status_code=404, detail={'code': 'not_found', 'message': 'API route not found'})
    dist = settings.frontend_dist
    if not dist.exists():
        raise HTTPException(status_code=404, detail='Frontend not built')
    target = (dist / path).resolve()
    if target.is_file() and target.is_relative_to(dist):
        return FileResponse(target)
    if '.' not in Path(path).name and (dist / 'index.html').is_file():
        return FileResponse(dist / 'index.html')
    raise HTTPException(status_code=404, detail='Not found')
