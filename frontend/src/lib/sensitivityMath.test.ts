import { describe, expect, it } from 'vitest'
import { boundsReady, linspace } from './sensitivityMath'

// FINDINGS.md M8: Number('') === 0, so a driver with empty min/max could run
// a sweep from 0 (e.g. a 0% exit cap grid point). The run button stays
// disabled until every selected driver's bounds are actually usable.
describe('boundsReady', () => {
  it('accepts finite numeric bounds with integer steps >= 2', () => {
    expect(boundsReady({ min: '4', max: '6', steps: '5' })).toBe(true)
    expect(boundsReady({ min: '-2', max: '2', steps: '2' })).toBe(true)
    expect(boundsReady({ min: '0.04', max: '0.06', steps: '3' })).toBe(true)
  })

  it('rejects empty min or max (which would coerce to 0)', () => {
    expect(boundsReady({ min: '', max: '6', steps: '5' })).toBe(false)
    expect(boundsReady({ min: '4', max: '', steps: '5' })).toBe(false)
    expect(boundsReady({ min: '', max: '', steps: '5' })).toBe(false)
    expect(boundsReady({ min: '   ', max: '6', steps: '5' })).toBe(false)
  })

  it('rejects non-numeric bounds', () => {
    expect(boundsReady({ min: 'abc', max: '6', steps: '5' })).toBe(false)
    expect(boundsReady({ min: '4', max: 'Infinity', steps: '5' })).toBe(false)
  })

  it('rejects unusable step counts', () => {
    expect(boundsReady({ min: '4', max: '6', steps: '' })).toBe(false)
    expect(boundsReady({ min: '4', max: '6', steps: '1' })).toBe(false)
    expect(boundsReady({ min: '4', max: '6', steps: '2.5' })).toBe(false)
  })
})

describe('linspace', () => {
  it('produces an inclusive evenly spaced sweep', () => {
    expect(linspace(0, 10, 3)).toEqual([0, 5, 10])
  })

  it('collapses to [min] when steps <= 1', () => {
    expect(linspace(4, 6, 1)).toEqual([4])
  })
})
