"""Local rotating application logs."""
import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = 'going_bananas'


def configure(private_dir: Path) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        directory = private_dir / 'logs'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / 'app.log', maxBytes=2_000_000, backupCount=5, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def get(name: str) -> logging.Logger:
    return logging.getLogger(f'{LOGGER_NAME}.{name}')


def request_error(request_id: str, method: str, path: str, exc: Exception) -> None:
    # Driver and validation exception messages can contain bound values or whole request bodies.
    frames = traceback.extract_tb(exc.__traceback__)
    locations = '\n'.join(f'  {frame.filename}:{frame.lineno} in {frame.name}' for frame in frames)
    get('api').error('unhandled request_id=%s method=%s path=%s %s\n%s',
                     request_id, method, path, type(exc).__name__, locations)
