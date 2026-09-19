import { describe, expect, it } from 'vitest'
import schemaJson from '../../../backend/app/data/input_schema.json'
import { visibleFields } from './schemaFields'
import type { InputSchema } from '../types/schema'

// Run 6: `buildingRsf` is schema-driven — DealInputForm renders it through
// the commercial rent-roll section, so a lease deal must see it and a
// multifamily deal must not.
const schema = schemaJson as unknown as InputSchema

const ids = (values: Record<string, unknown>) => visibleFields(schema, values).map((f) => f.id)

describe('buildingRsf field visibility', () => {
  it('shows on lease deals (office / retail / industrial / commercial mixed-use)', () => {
    for (const propertyType of ['office', 'retail', 'industrial']) {
      expect(ids({ dealType: 'acquisition', propertyType })).toContain('buildingRsf')
    }
    expect(
      ids({ dealType: 'acquisition', propertyType: 'mixed_use', mixedUseComponents: ['residential', 'retail'] }),
    ).toContain('buildingRsf')
  })

  it('is a non-negative number input', () => {
    const field = visibleFields(schema, { propertyType: 'office' }).find((f) => f.id === 'buildingRsf')
    expect(field?.type).toBe('number')
  })

  it('stays hidden on multifamily', () => {
    expect(ids({ dealType: 'acquisition', propertyType: 'multifamily' })).not.toContain('buildingRsf')
  })
})
