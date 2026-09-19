import { describe, expect, it } from 'vitest'
import type { MappingsById } from '../types/mapping'
import { mappingsEqual } from './mappingFormat'

const base: MappingsById = {
  purchasePrice: { target: 'cell', ref: 'Inputs!C5', sheet: 'Inputs', source: 'auto' },
  exitCapRate: { target: 'namedRange', ref: 'ExitCap', source: 'manual' },
}

describe('mappingsEqual', () => {
  it('ignores auto/manual provenance and key order', () => {
    const reordered: MappingsById = {
      exitCapRate: { ...base.exitCapRate },
      purchasePrice: { ...base.purchasePrice, source: 'manual' },
    }
    expect(mappingsEqual(base, reordered)).toBe(true)
  })

  it('detects a moved, added or removed mapping', () => {
    expect(mappingsEqual(base, { ...base, purchasePrice: { ...base.purchasePrice, ref: 'Inputs!C6' } })).toBe(false)
    expect(mappingsEqual(base, { ...base, vacancy: { target: 'cell', ref: 'Inputs!C9', source: 'manual' } })).toBe(false)
    const { exitCapRate: _removed, ...fewer } = base
    expect(mappingsEqual(base, fewer)).toBe(false)
  })
})
