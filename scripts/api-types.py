"""Generate Go and TypeScript wire types and verify the generated SQL queries."""

import argparse
import filecmp
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'backend-go'
CONTRACT = Path('api/openapi.json')
HANDLERS = Path('api/api.gen.go')
CALENDAR = Path('api/calendar.openapi.json')
CALENDAR_CONFIG = Path('api/calendarwire/oapi-codegen.yaml')
CALENDAR_MODELS = Path('api/calendarwire/models.gen.go')
SQL_OUTPUT = Path('internal/db')


def generate_go(work: Path) -> None:
    subprocess.run(['oapi-codegen', '-config', 'api/oapi-codegen.yaml', CONTRACT], cwd=work, check=True)
    subprocess.run(['oapi-codegen', '-config', CALENDAR_CONFIG, CALENDAR], cwd=work, check=True)
    subprocess.run(['sqlc', 'generate'], cwd=work, check=True)


def check_generated_go() -> None:
    scratch = ROOT / 'private'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='go-generate-', dir=scratch) as directory:
        work = Path(directory)
        (work / CALENDAR_CONFIG.parent).mkdir(parents=True)
        for relative in [CONTRACT, CALENDAR, CALENDAR_CONFIG, Path('api/oapi-codegen.yaml'), Path('sqlc.yaml'), Path('go.mod')]:
            shutil.copyfile(MODULE / relative, work / relative)
        shutil.copytree(MODULE / 'sql', work / 'sql')
        generate_go(work)
        outputs = {HANDLERS, CALENDAR_MODELS}
        for base in (work, MODULE):
            outputs.update(path.relative_to(base) for path in (base / SQL_OUTPUT).glob('*.go'))
        for relative in sorted(outputs):
            checked_in, generated = MODULE / relative, work / relative
            if not (checked_in.is_file() and generated.is_file() and filecmp.cmp(checked_in, generated, shallow=False)):
                raise SystemExit(f'{relative} differs from generated output. Run make generate-api-types.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='verify generated files without changing the checkout')
    mode.add_argument('--schema', action='store_true', help='print the Go-owned OpenAPI contract')
    args = parser.parse_args()
    if args.schema:
        print((MODULE / CONTRACT).read_text(), end='')
        return
    if args.check:
        check_generated_go()
    else:
        generate_go(MODULE)
    sources = [(CONTRACT, 'backend.ts')]
    for fragment in sorted((MODULE / 'api').glob('*.openapi.json')):
        name = fragment.name.removesuffix('.openapi.json')
        first, *rest = name.split('-')
        target = first + ''.join(word.title() for word in rest) + '.ts'
        sources.append((fragment.relative_to(MODULE), target))
    for source, target in sources:
        command = ['node_modules/.bin/openapi-typescript', str(MODULE / source),
                   '-o', f'src/api/generated/{target}']
        if target == 'coachProposals.ts':
            # Saved documents omit defaults the athlete or coach never authored.
            command.extend(['--default-non-nullable', 'false'])
        if args.check:
            command.append('--check')
        subprocess.run(command, cwd=ROOT / 'frontend', check=True)


if __name__ == '__main__':
    main()
