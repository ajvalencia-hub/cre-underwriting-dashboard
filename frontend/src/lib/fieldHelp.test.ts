import { describe, expect, it } from 'vitest'
import schema from '../../../backend/app/data/input_schema.json'
import { FIELD_HELP } from './fieldHelp'

interface SchemaField {
  id: string
  type: string
  templateOnly?: boolean
}

const fields = (schema as { sections: { fields: SchemaField[] }[] }).sections.flatMap((s) => s.fields)
const ids = new Set(fields.map((f) => f.id))

describe('field definitions', () => {
  it('only describe fields that exist', () => {
    expect(Object.keys(FIELD_HELP).filter((id) => !ids.has(id))).toEqual([])
  })

  it('cover every numeric input the engine uses', () => {
    const numeric = new Set(['currency', 'percent', 'number', 'years', 'multiple'])
    const missing = fields
      .filter((f) => numeric.has(f.type) && !f.templateOnly && !(f.id in FIELD_HELP))
      .map((f) => f.id)
    expect(missing).toEqual([])
  })
})
