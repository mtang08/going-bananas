import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / 'app'
TZ_LITERAL_ALLOWED = {'services/timezone.py', 'models.py', 'adapters/garmin/normalize.py', 'demo_seed.py'}


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


def test_lower_layers_never_import_api():
    offenders = [f'{p.relative_to(APP)}: {m}' for layer in ('services', 'metrics', 'domain', 'adapters')
                 for p in sorted((APP / layer).rglob('*.py')) for m in _imports(p)
                 if m == 'app.api' or m.startswith('app.api.')]
    assert offenders == []


def test_domain_imports_no_framework_or_db():
    banned = ('sqlalchemy', 'fastapi', 'app.db', 'app.models', 'app.services', 'app.api')
    offenders = [f'{p.name}: {m}' for p in sorted((APP / 'domain').rglob('*.py')) for m in _imports(p)
                 if m.startswith(banned) or m.endswith('_models')]
    assert offenders == []


def test_timezone_default_has_one_home():
    offenders = [str(p.relative_to(APP)) for p in sorted(APP.rglob('*.py'))
                 if "America/New_York" in p.read_text() and str(p.relative_to(APP)) not in TZ_LITERAL_ALLOWED]
    assert offenders == []
