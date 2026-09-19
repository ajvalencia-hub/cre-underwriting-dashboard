import { describe, expect, it } from 'vitest'
import { clearProvenance, describeProvenance, readProvenance, recordProvenance, sameSourceFor } from './provenance'

describe('field provenance', () => {
  it('records, reads and clears', () => {
    let values: Record<string, unknown> = { purchasePrice: 1 }
    values = recordProvenance(values, sameSourceFor(['purchasePrice', 'vacancyPct'], { source: 'preset', label: 'Garden MF' }))
    expect(Object.keys(readProvenance(values))).toEqual(['purchasePrice', 'vacancyPct'])
    values = clearProvenance(values, 'purchasePrice')
    expect(Object.keys(readProvenance(values))).toEqual(['vacancyPct'])
  })

  it('ignores malformed stored data', () => {
    expect(readProvenance({ _provenance: 'x' })).toEqual({})
    expect(readProvenance({ _provenance: { a: 1, b: { source: 'goalSeek' } } })).toEqual({ b: { source: 'goalSeek' } })
  })

  it('describes the source', () => {
    expect(describeProvenance({ source: 'extraction', sourceRef: { doc: 'OM.pdf', page: 4 } })).toBe('from OM.pdf p.4')
    expect(describeProvenance({ source: 'preset', label: 'Garden MF' })).toBe('preset “Garden MF”')
    expect(describeProvenance({ source: 'goalSeek' })).toBe('goal seek')
  })
})
