"""Export the OpenAPI bundle and generate Go, TypeScript and SQL code."""

import argparse
import filecmp
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'backend-go'
CONTRACT = Path('api/openapi.json')
HANDLERS = Path('api/api.gen.go')
CALENDAR = Path('api/calendar.openapi.json')
CALENDAR_CONFIG = Path('api/calendarwire/oapi-codegen.yaml')
CALENDAR_MODELS = Path('api/calendarwire/models.gen.go')
SQL_OUTPUT = Path('internal/db')
HTTP_METHODS = frozenset({'get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'})


def contract_sources() -> list[tuple[Path, str]]:
    sources = [(CONTRACT, 'backend.ts')]
    for fragment in sorted((MODULE / CONTRACT.parent).glob('*.openapi.json')):
        name = fragment.name.removesuffix('.openapi.json')
        first, *rest = name.split('-')
        target = first + ''.join(word.title() for word in rest) + '.ts'
        sources.append((fragment.relative_to(MODULE), target))
    return sources


def component_name(source: Path, name: str) -> str:
    return f'{source.stem}.{name}'


def rewrite_pointer(reference: str, source: Path, documents: dict) -> str:
    uri = urlsplit(reference)
    target = source.parent / unquote(uri.path) if uri.path else source
    if uri.scheme or uri.netloc or uri.query or target not in documents:
        raise ValueError(f'{source}: cannot bundle reference {reference!r}')
    fragment = unquote(uri.fragment)
    if not fragment.startswith('/'):
        raise ValueError(f'{source}: expected a JSON pointer in {reference!r}')
    tokens = fragment.split('/')[1:]
    node = documents[target]
    try:
        for token in tokens:
            key = token.replace('~1', '/').replace('~0', '~')
            node = node[int(key)] if isinstance(node, list) else node[key]
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise ValueError(f'{source}: unresolved reference {reference!r}') from error
    if len(tokens) >= 3 and tokens[0] == 'components':
        tokens[2] = component_name(target, tokens[2])
    elif tokens[0] != 'paths':
        raise ValueError(f'{source}: cannot bundle reference {reference!r}')
    return '#/' + quote('/'.join(tokens), safe='/~')


def rewrite_references(node, source: Path, documents: dict):
    if isinstance(node, list):
        return [rewrite_references(item, source, documents) for item in node]
    if not isinstance(node, dict):
        return node
    properties = {}
    for key, value in node.items():
        if key in {'$ref', 'operationRef'} and isinstance(value, str):
            properties[key] = rewrite_pointer(value, source, documents)
        elif key == 'discriminator' and isinstance(value, dict) and 'mapping' in value:
            schemas = documents[source].get('components', {}).get('schemas', {})
            properties[key] = {
                **value,
                'mapping': {
                    label: rewrite_pointer(
                        f'#/components/schemas/{target}' if target in schemas else target,
                        source, documents,
                    )
                    for label, target in value['mapping'].items()
                },
            }
        else:
            properties[key] = rewrite_references(value, source, documents)
    if documents[source]['openapi'].startswith('3.0.'):
        if isinstance(properties.get('nullable'), bool) and isinstance(properties.get('type'), str):
            if properties.pop('nullable'):
                properties['type'] = [properties['type'], 'null']
        for bound in ('Minimum', 'Maximum'):
            exclusive = 'exclusive' + bound
            if isinstance(properties.get(exclusive), bool):
                if properties.pop(exclusive) and bound.lower() in properties:
                    properties[exclusive] = properties.pop(bound.lower())
    return properties


def bundle_schema(documents: dict[Path, dict]) -> dict:
    base = documents[CONTRACT]
    paths = {}
    components = {}
    operations = {}
    for source, document in documents.items():
        for route, path_item in document['paths'].items():
            combined = paths.setdefault(route, {})
            for key, value in rewrite_references(path_item, source, documents).items():
                if key in HTTP_METHODS:
                    operation = (route, key)
                    if operation in operations:
                        raise ValueError(f'{source}: duplicate {key.upper()} {route} in {operations[operation]}')
                    operations[operation] = source
                elif key in combined and combined[key] != value:
                    raise ValueError(f'{source}: conflicting {key} on {route}')
                combined[key] = value
        for group, definitions in document.get('components', {}).items():
            combined = components.setdefault(group, {})
            for name, definition in definitions.items():
                scoped = component_name(source, name)
                if scoped in combined:
                    raise ValueError(f'{source}: duplicate component {group}/{scoped}')
                combined[scoped] = rewrite_references(definition, source, documents)
    return {**base, 'paths': paths, 'components': components}


def load_schema() -> dict:
    return bundle_schema({source: json.loads((MODULE / source).read_text()) for source, _ in contract_sources()})


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
    mode.add_argument('--schema', action='store_true', help='print the bundled Go-owned OpenAPI contract')
    args = parser.parse_args()
    if args.schema or args.check:
        try:
            schema = load_schema()
        except ValueError as error:
            parser.exit(1, f'{error}\n')
        if args.schema:
            print(json.dumps(schema, indent=2))
            return
    if args.check:
        check_generated_go()
    else:
        generate_go(MODULE)
    for source, target in contract_sources():
        command = ['node_modules/.bin/openapi-typescript', str(MODULE / source),
                   '-o', f'src/api/generated/{target}']
        if args.check:
            command.append('--check')
        subprocess.run(command, cwd=ROOT / 'frontend', check=True)


if __name__ == '__main__':
    main()
