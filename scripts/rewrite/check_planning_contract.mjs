import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const Ajv = require('ajv')
const document = JSON.parse(readFileSync(new URL('../../backend-go/api/planning.openapi.json', import.meta.url)))
const ajv = new Ajv({ allErrors: true, jsonPointers: true })
const operations = new Set()
for (const sample of JSON.parse(readFileSync(0, 'utf8'))) {
  const op = document.paths['/api/v1' + sample.path][sample.method.toLowerCase()]
  operations.add(op.operationId)
  const response = op.responses[sample.status]
  assert(response, `${op.operationId} returned undocumented HTTP ${sample.status}`)
  const validate = schema => ajv.compile({ ...schema, components: document.components })
  const body = validate(response.content['application/json'].schema)
  assert(body(sample.response), `${op.operationId}: ${ajv.errorsText(body.errors)}`)
  if (sample.status < 300 && op.requestBody) {
    const request = validate(op.requestBody.content['application/json'].schema)
    assert(request(sample.body), `${op.operationId} input: ${ajv.errorsText(request.errors)}`)
  }
}
assert.equal(operations.size, Object.values(document.paths).flatMap(Object.values).length)
