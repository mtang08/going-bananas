"""Exercise the public OpenAPI export without Go, Node or PostgreSQL."""

import json
import subprocess
import unittest
from pathlib import Path
from runpy import run_path
from urllib.parse import unquote

SCRIPT = Path(__file__).with_name('api-types.py')
EXPORTER = run_path(str(SCRIPT))
CONTRACT = EXPORTER['CONTRACT']
METHODS = EXPORTER['HTTP_METHODS']


def operations(document):
    return {
        (route, key)
        for route, item in document['paths'].items()
        for key in item
        if key in METHODS
    }


def references(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {'$ref', 'operationRef'}:
                yield value
            elif key == 'discriminator':
                yield from value.get('mapping', {}).values()
            else:
                yield from references(value)
    elif isinstance(node, list):
        for item in node:
            yield from references(item)


def resolve(document, pointer):
    for token in unquote(pointer[2:]).split('/'):
        key = token.replace('~1', '/').replace('~0', '~')
        document = document[int(key)] if isinstance(document, list) else document[key]
    return document


def document(paths, **schemas):
    return {'openapi': '3.1.0', 'paths': paths, 'components': {'schemas': schemas}}


class BundleTests(unittest.TestCase):
    def test_export_includes_every_operation_and_resolves_every_reference(self):
        output = subprocess.check_output(['python3', str(SCRIPT), '--schema'])
        bundled = json.loads(output)
        source_documents = [
            json.loads((EXPORTER['MODULE'] / source).read_text())
            for source, _ in EXPORTER['contract_sources']()
        ]
        expected = set().union(*(operations(source) for source in source_documents))
        self.assertEqual(operations(bundled), expected)
        self.assertEqual(len(expected), sum(len(operations(source)) for source in source_documents))
        for reference in references(bundled):
            with self.subTest(reference=reference):
                self.assertTrue(reference.startswith('#/'))
                resolve(bundled, reference)

    def test_scopes_same_names_and_rewrites_discriminator_and_operation_links(self):
        fragment = Path('api/details.openapi.json')
        base = document({'/object': {'get': {}}}, Item={'type': 'string'})
        details = document(
            {'/object': {'post': {'operationRef': './openapi.json#/paths/~1object/get'}}},
            Item={'type': 'integer', 'nullable': True},
            Variant={
                'discriminator': {
                    'propertyName': 'kind',
                    'mapping': {'local': 'Item', 'base': './openapi.json#/components/schemas/Item'},
                },
            },
        )
        details['openapi'] = '3.0.3'
        bundled = EXPORTER['bundle_schema']({CONTRACT: base, fragment: details})
        schemas = bundled['components']['schemas']
        base_name = 'openapi.Item'
        local_name = 'details.openapi.Item'
        self.assertEqual(schemas[base_name], {'type': 'string'})
        self.assertEqual(schemas[local_name], {'type': ['integer', 'null']})
        self.assertEqual(schemas['details.openapi.Variant']['discriminator']['mapping'], {
            'local': f'#/components/schemas/{local_name}',
            'base': f'#/components/schemas/{base_name}',
        })
        self.assertEqual(bundled['paths']['/object']['post']['operationRef'], '#/paths/~1object/get')

    def test_embeds_schema_roots_and_internal_definitions(self):
        schema = Path('shared/document.json')
        selection = Path('shared/selection.json')
        bundled = EXPORTER['bundle_schema']({
            CONTRACT: document({}, Root={'$ref': '../shared/document.json'}),
            schema: {
                'properties': {'selection': {'$ref': './selection.json#/$defs/Choice'}},
            },
            selection: {
                '$defs': {
                    'Choice': {'$ref': '#/$defs/Label'},
                    'Label': {'type': 'string'},
                },
            },
        })
        root = resolve(bundled, bundled['components']['schemas']['openapi.Root']['$ref'])
        choice = resolve(bundled, root['properties']['selection']['$ref'])
        self.assertEqual(resolve(bundled, choice['$ref']), {'type': 'string'})

    def test_rejects_duplicate_methods_and_unresolved_references(self):
        source = Path('api/details.openapi.json')
        base = document({'/object': {'get': {}}})
        with self.assertRaisesRegex(ValueError, 'duplicate GET /object'):
            EXPORTER['bundle_schema']({CONTRACT: base, source: base})
        with self.assertRaisesRegex(ValueError, 'unresolved reference'):
            EXPORTER['bundle_schema']({
                CONTRACT: base,
                source: document({}, Invalid={'$ref': './openapi.json#/components/schemas/Missing'}),
            })


if __name__ == '__main__':
    unittest.main()
