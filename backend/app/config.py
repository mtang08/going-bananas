from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv('DATABASE_URL', 'postgresql+psycopg://bananas:bananas@localhost:5432/bananas_demo'), repr=False)
    app_mode: str = os.getenv('APP_MODE', 'demo')
    private_dir: Path = Path(os.getenv('PRIVATE_DIR', 'private')).resolve()
    frontend_dist: Path = Path(os.getenv('FRONTEND_DIST', str(Path(__file__).resolve().parents[2] / 'frontend' / 'dist'))).resolve()
    host: str = os.getenv('APP_HOST', '127.0.0.1')
    port: int = int(os.getenv('APP_PORT', '8000'))
    vite_port: int = int(os.getenv('VITE_PORT', '5173'))

    def __post_init__(self) -> None:
        if self.app_mode not in {'demo', 'real', 'test'}:
            raise ValueError('APP_MODE must be demo, real, or test')
        if not self.database_url.startswith(('postgresql+psycopg://', 'postgresql://')):
            raise ValueError('Only PostgreSQL is supported')
        database_name = make_url(self.database_url).database or ''
        if not database_name.endswith('_' + self.app_mode):
            raise ValueError('Database name must end with APP_MODE suffix')
        if self.host not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('Server must bind to loopback')


settings = Settings()
