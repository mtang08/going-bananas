import logging
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import logs
from app.main import local_security


def test_unhandled_request_rotates_without_logging_private_values(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, 'LOGGER_NAME', 'test_going_bananas')
    logger = logs.configure(tmp_path)
    try:
        assert logs.configure(tmp_path) is logger
        assert sum(isinstance(h, RotatingFileHandler) for h in logger.handlers) == 1
        app = FastAPI()
        app.middleware('http')(local_security)

        @app.get('/test')
        async def fail():
            raise RuntimeError('secret-value')

        response = TestClient(app).get('/test?token=secret-query')
        assert response.status_code == 500
        error = response.json()['error']
        assert error['code'] == 'internal_error' and 'secret-value' not in response.text
        log = (tmp_path / 'logs' / 'app.log').read_text()
        assert f"unhandled request_id={error['request_id']} method=GET path=/test RuntimeError" in log
        assert ' in fail' in log
        assert 'secret-value' not in log and 'secret-query' not in log
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(logging.NOTSET)
