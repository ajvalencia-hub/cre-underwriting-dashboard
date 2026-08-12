import { describe, expect, it } from 'vitest'
import {
  ALL_STAGES,
  bulkStageOptions,
  dealTypeOf,
  SHARED_STAGES,
  STAGE_LABELS,
  STAGE_STYLES,
  stageOptionsForDeal,
  STAGES_BY_TYPE,
  stalenessThresholds,
  TERMINAL_STAGES,
} from './dealStages'
import { stalenessBadge } from './staleness'

describe('registry sync', () => {
  it('pins BOTH stage sets to the agreed registry — the backend test pins', () => {
    // backend/tests/test_deal_stages.py::test_registry_shape asserts the
    // SAME literals against input_schema.json's dealStages, so a drift on
    // either side of the wire fails one of the two suites.
    expect(STAGES_BY_TYPE).toEqual({
      acquisition: ['screening', 'underwriting', 'loi', 'under_contract', 'closed', 'dead'],
      development: [
        'screening', 'feasibility', 'site_control', 'entitlements',
        'pre_construction', 'construction', 'lease_up', 'stabilized', 'dead',
      ],
    })
  })

  it('every stage has a label and a style', () => {
    for (const stage of ALL_STAGES) {
      expect(STAGE_LABELS[stage], stage).toBeTruthy()
      expect(STAGE_STYLES[stage], stage).toBeTruthy()
    }
  })

  it('shared stages are exactly the intersection', () => {
    expect(SHARED_STAGES).toEqual(['screening', 'dead'])
  })

  it('terminal stages cover both flows', () => {
    expect(TERMINAL_STAGES).toEqual(['closed', 'stabilized', 'dead'])
  })
})

describe('dealTypeOf / stage options', () => {
  it('reads the type from inputs, null for junk', () => {
    expect(dealTypeOf({ inputs: { dealType: 'acquisition' } })).toBe('acquisition')
    expect(dealTypeOf({ inputs: { dealType: 'development' } })).toBe('development')
    expect(dealTypeOf({ inputs: {} })).toBeNull()
    expect(dealTypeOf({ inputs: { dealType: 'flip' } })).toBeNull()
  })

  it('appends a legacy status to the wrong-type stage list, never rewrites it', () => {
    // A development deal still carrying the acquisition-era 'loi'.
    const options = stageOptionsForDeal({
      inputs: { dealType: 'development' },
      status: 'loi',
    })
    expect(options).toEqual([...STAGES_BY_TYPE.development, 'loi'])
    // In-set statuses do not duplicate.
    expect(
      stageOptionsForDeal({ inputs: { dealType: 'development' }, status: 'construction' }),
    ).toEqual(STAGES_BY_TYPE.development)
  })

  it('bulk options: one type -> its stages; mixed or untyped -> shared only', () => {
    const acq = { inputs: { dealType: 'acquisition' } }
    const dev = { inputs: { dealType: 'development' } }
    const untyped = { inputs: {} }
    expect(bulkStageOptions([acq, acq])).toEqual(STAGES_BY_TYPE.acquisition)
    expect(bulkStageOptions([dev])).toEqual(STAGES_BY_TYPE.development)
    expect(bulkStageOptions([acq, dev])).toEqual(SHARED_STAGES)
    expect(bulkStageOptions([untyped])).toEqual(SHARED_STAGES)
    expect(bulkStageOptions([])).toEqual(SHARED_STAGES)
  })
})

describe('per-stage staleness', () => {
  const NOW = Date.parse('2026-07-04T12:00:00Z')
  const daysAgo = (d: number) => new Date(NOW - d * 86_400_000).toISOString()

  it('long-lived development stages get relaxed thresholds', () => {
    expect(stalenessThresholds('construction')).toEqual({ stale: 45, veryStale: 90 })
    expect(stalenessThresholds('entitlements')).toEqual({ stale: 45, veryStale: 90 })
    expect(stalenessThresholds('screening')).toEqual({ stale: 14, veryStale: 30 })
  })

  it('a 40-day-quiet construction deal does not badge; 100 days goes red', () => {
    expect(stalenessBadge('construction', daysAgo(40), NOW)).toBeNull()
    expect(stalenessBadge('construction', daysAgo(100), NOW)).toEqual({
      label: 'stale 100d',
      tone: 'red',
    })
    // Default stages keep the original 14/30 behavior.
    expect(stalenessBadge('feasibility', daysAgo(15), NOW)).toEqual({
      label: 'stale 15d',
      tone: 'amber',
    })
  })

  it('stabilized is terminal — never badges', () => {
    expect(stalenessBadge('stabilized', daysAgo(400), NOW)).toBeNull()
  })
})
