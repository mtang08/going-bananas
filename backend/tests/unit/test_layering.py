import ast
import re
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
    banned = ('sqlalchemy', 'fastapi', 'app.db', 'app.models', 'app.services', 'app.api', 'app.read')
    offenders = [f'{p.name}: {m}' for p in sorted((APP / 'domain').rglob('*.py')) for m in _imports(p)
                 if m.startswith(banned) or m.endswith('_models')]
    assert offenders == []


def test_timezone_default_has_one_home():
    offenders = [str(p.relative_to(APP)) for p in sorted(APP.rglob('*.py'))
                 if "America/New_York" in p.read_text() and str(p.relative_to(APP)) not in TZ_LITERAL_ALLOWED]
    assert offenders == []


def test_consumers_use_registered_metric_versions():
    patterns = (
        re.compile(r"""latest_results\([^)]*['"]v\d+['"]"""),
        re.compile(r"""method_version\s*==\s*['"]v\d+['"]"""),
    )
    offenders = [
        f'{path.relative_to(APP)}:{line_no}: {line.strip()}'
        for path in sorted(APP.rglob('*.py'))
        if path != APP / 'metrics' / 'engine.py'
        for line_no, line in enumerate(path.read_text().splitlines(), start=1)
        if any(pattern.search(line) for pattern in patterns)
        or (APP / 'metrics' not in path.parents and re.search(r'\blatest_results\s*\(', line))
    ]
    assert offenders == []


def test_global_lock_key_has_one_home():
    offenders = [str(p.relative_to(APP)) for p in sorted(APP.rglob('*.py'))
                 if '71382413' in p.read_text() and p.relative_to(APP) != Path('db.py')]
    assert offenders == []


SERVICES_ALLOWED_BELOW = {'app.services.timezone'}
METRICS_SERVICES_BASELINE = {
    'metrics/planned_actual.py: app.services.matching',  # candidates_for_session; see decisions.md
}
PRIVATE_IMPORT_BASELINE = {
}
RUN_SPORT_LITERAL_ALLOWED = {'domain/sports.py', 'metrics/volume.py', 'adapters/garmin/normalize.py',
                             'adapters/garmin/fit.py', 'demo_seed.py'}
LOCAL_DATE_ALLOWED = {'domain/local_time.py', 'adapters/garmin/normalize.py'}


def _rel(path: Path) -> str:
    return str(path.relative_to(APP))


def _service_imports(layer: str) -> set[str]:
    return {f'{_rel(p)}: {m}' for p in sorted((APP / layer).rglob('*.py')) for m in _imports(p)
            if (m == 'app.services' or m.startswith('app.services.')) and m not in SERVICES_ALLOWED_BELOW}


def _private_uses(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    aliases: set[str] = set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('app'):
            for alias in node.names:
                if alias.name.startswith('_') and not alias.name.startswith('__'):
                    found.add(f'{node.module}.{alias.name}')
                aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            aliases.update(a.asname or a.name for a in node.names if a.name.startswith('app'))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases
                and node.attr.startswith('_') and not node.attr.startswith('__')):
            found.add(f'{node.value.id}.{node.attr}')
    return found


def _files_matching(pattern: str, allowed: set[str]) -> list[str]:
    regex = re.compile(pattern)
    return [_rel(p) for p in sorted(APP.rglob('*.py')) if _rel(p) not in allowed and regex.search(p.read_text())]


def test_metrics_do_not_import_services_beyond_baseline():
    found = _service_imports('metrics')
    assert found - METRICS_SERVICES_BASELINE == set()
    assert METRICS_SERVICES_BASELINE - found == set(), 'remove fixed entries from METRICS_SERVICES_BASELINE'


def test_read_layer_stays_below_services_metrics_and_api():
    offenders = [f'{_rel(p)}: {m}' for p in sorted((APP / 'read').rglob('*.py')) for m in _imports(p)
                 if m.startswith(('app.api', 'app.metrics', 'app.cli', 'app.main'))
                 or (m.startswith('app.services') and m not in SERVICES_ALLOWED_BELOW)]
    assert offenders == []


def test_no_cross_module_private_imports_beyond_baseline():
    found = {f'{_rel(p)}: {name}' for p in sorted(APP.rglob('*.py')) for name in _private_uses(p)}
    assert found - PRIVATE_IMPORT_BASELINE == set()
    assert PRIVATE_IMPORT_BASELINE - found == set(), 'remove fixed entries from PRIVATE_IMPORT_BASELINE'


def test_run_sports_have_one_definition():
    assert _files_matching(r"""['"]trail_running['"]""", RUN_SPORT_LITERAL_ALLOWED) == []


def test_local_date_conversion_has_one_home():
    assert _files_matching(r'\.astimezone\([^\n]*\)\.date\(\)', LOCAL_DATE_ALLOWED) == []


def test_calendar_head_and_latest_revision_reads_have_one_home():
    assert _files_matching(r'calendar_head_version if|select\(AppState\.calendar_head_version', {'read/calendar.py'}) == []
    assert _files_matching(r'desc\(CalendarSessionRevision\.calendar_version_number\)'
                           r'|CalendarSessionRevision\.calendar_version_number\.desc\(\)', {'read/calendar.py'}) == []
