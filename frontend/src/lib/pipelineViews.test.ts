import { describe, expect, it } from 'vitest'
import {
  DEFAULT_VIEW_STATE,
  applyPipelineView,
  applyView,
  deleteView,
  filterDeals,
  loadViews,
  normalizeView,
  pipelineToCsv,
  saveView,
  sortDeals,
  stalenessLevel,
  toggleSort,
  type PipelineView,
} from './pipelineViews'
import type { Deal } from '../types/deal'

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial }
  return {
    getItem: (key: string) => (key in data ? data[key] : null),
    setItem: (key: string, value: string) => {
      data[key] = value
    },
  }
}

const NOW = Date.parse('2026-07-05T12:00:00Z')
const deal = (over: Partial<Deal>): Deal => ({
  id: 'x',
  name: 'Deal',
  inputs: {},
  status: 'screening',
  activeTemplateId: null,
  activeMappingProfileId: null,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-07-01T00:00:00Z',
  ...over,
})

describe('saved views', () => {
  const view: PipelineView = {
    ...DEFAULT_VIEW_STATE,
    name: 'Miami active',
    marketFilter: 'miami',
    sortKey: 'updated',
    sortDir: 'desc',
    tagFilter: ['core'],
  }

  it('round-trips and upserts by name', () => {
    const storage = memoryStorage()
    expect(loadViews(storage)).toEqual([])
    saveView(storage, view)
    expect(loadViews(storage)).toEqual([view])
    saveView(storage, { ...view, sortKey: 'name' })
    expect(loadViews(storage)).toHaveLength(1)
    expect(loadViews(storage)[0].sortKey).toBe('name')
    expect(deleteView(storage, 'Miami active')).toEqual([])
  })

  it('tolerates corrupted storage', () => {
    expect(loadViews(memoryStorage({ 'cre.pipelineViews': '{not json' }))).toEqual([])
    expect(loadViews(memoryStorage({ 'cre.pipelineViews': '{"a":1}' }))).toEqual([])
    expect(
      loadViews(memoryStorage({ 'cre.pipelineViews': '[{"name":""},{"name":"ok","marketFilter":"","sortKey":"stage","showTerminal":true}]' })),
    ).toHaveLength(1)
  })

  it('upgrades a pre-wave-2 view with defaults and drops junk filter values', () => {
    const legacy = normalizeView({ name: 'old', marketFilter: 'x', sortKey: 'updated', showTerminal: true })
    expect(legacy).toEqual({
      name: 'old',
      marketFilter: 'x',
      sortKey: 'updated',
      sortDir: 'desc', // the column's default direction
      showTerminal: true,
      stageFilter: [],
      stalenessFilter: [],
      tagFilter: [],
    })
    expect(normalizeView({ name: 'k', sortKey: 'bogus', stalenessFilter: ['stale', 'nope'] })).toMatchObject({
      sortKey: 'stage',
      stalenessFilter: ['stale'],
    })
    expect(normalizeView('nope')).toBeNull()
    expect(normalizeView({ name: 's', stageFilter: ['loi', 'nonsense'] })?.stageFilter).toEqual(['loi'])
  })

  it('keeps metric sort keys and the chosen columns', () => {
    const v = normalizeView({ name: 'irr', sortKey: 'leveredIrr', columns: ['leveredIrr', 3] })
    expect(v).toMatchObject({ sortKey: 'leveredIrr', sortDir: 'desc', columns: ['leveredIrr'] })
    expect(normalizeView({ name: 'no cols' })).not.toHaveProperty('columns')
  })
})

describe('toggleSort', () => {
  it('starts a new column in its default direction and flips the current one', () => {
    expect(toggleSort({ sortKey: 'stage', sortDir: 'asc' }, 'updated')).toEqual({ sortKey: 'updated', sortDir: 'desc' })
    expect(toggleSort({ sortKey: 'updated', sortDir: 'desc' }, 'updated')).toEqual({ sortKey: 'updated', sortDir: 'asc' })
    expect(toggleSort({ sortKey: 'name', sortDir: 'asc' }, 'name')).toEqual({ sortKey: 'name', sortDir: 'desc' })
  })
})

describe('stalenessLevel', () => {
  it('maps the badge tones and treats terminal stages as fresh', () => {
    expect(stalenessLevel('screening', '2026-07-04T00:00:00Z', NOW)).toBe('fresh')
    expect(stalenessLevel('screening', '2026-06-15T00:00:00Z', NOW)).toBe('stale') // 20d
    expect(stalenessLevel('screening', '2026-05-01T00:00:00Z', NOW)).toBe('critical')
    expect(stalenessLevel('closed', '2025-01-01T00:00:00Z', NOW)).toBe('fresh')
  })
})

describe('filterDeals / sortDeals', () => {
  const deals = [
    deal({ id: 'a', name: 'Alpha', status: 'loi', inputs: { market: 'Miami' }, tags: ['core'] }),
    deal({ id: 'b', name: 'Beta', status: 'screening', updatedAt: '2026-07-04T00:00:00Z', tags: ['core', 'value-add'] }),
    deal({ id: 'c', name: 'Gamma', status: 'dead', inputs: { market: 'Miami' } }),
    deal({ id: 'd', name: 'Delta', status: 'underwriting', updatedAt: '2026-05-01T00:00:00Z', inputs: { market: 'Austin' } }),
  ]

  it('hides terminal stages by default and filters by market or name', () => {
    expect(applyView(deals, '', 'stage', false).map((d) => d.id)).toEqual(['b', 'd', 'a'])
    expect(applyView(deals, 'miami', 'stage', true).map((d) => d.id)).toEqual(['a', 'c'])
    expect(applyView(deals, 'beta', 'stage', false).map((d) => d.id)).toEqual(['b'])
  })

  it('filters by stage, staleness and tags (AND)', () => {
    const base = { ...DEFAULT_VIEW_STATE, showTerminal: true }
    expect(filterDeals(deals, { ...base, stageFilter: ['loi', 'dead'] }, NOW).map((d) => d.id)).toEqual(['a', 'c'])
    expect(filterDeals(deals, { ...base, stalenessFilter: ['critical'] }, NOW).map((d) => d.id)).toEqual(['d'])
    expect(filterDeals(deals, { ...base, stalenessFilter: ['fresh'] }, NOW).map((d) => d.id)).toEqual(['a', 'b', 'c'])
    expect(filterDeals(deals, { ...base, tagFilter: ['core'] }, NOW).map((d) => d.id)).toEqual(['a', 'b'])
    expect(filterDeals(deals, { ...base, tagFilter: ['core', 'value-add'] }, NOW).map((d) => d.id)).toEqual(['b'])
  })

  it('sorts by every key in both directions', () => {
    expect(sortDeals(deals, 'name', 'asc', NOW).map((d) => d.name)).toEqual(['Alpha', 'Beta', 'Delta', 'Gamma'])
    expect(sortDeals(deals, 'name', 'desc', NOW).map((d) => d.name)).toEqual(['Gamma', 'Delta', 'Beta', 'Alpha'])
    expect(sortDeals(deals, 'updated', 'desc', NOW)[0].id).toBe('b') // most recent
    expect(sortDeals(deals, 'updated', 'asc', NOW)[0].id).toBe('d')
    // market: blanks first ascending; ties fall back to most recently touched
    expect(sortDeals(deals, 'market', 'asc', NOW).map((d) => d.id)).toEqual(['b', 'd', 'a', 'c'])
    expect(sortDeals(deals, 'market', 'desc', NOW).map((d) => d.id)).toEqual(['a', 'c', 'd', 'b'])
    // staleness: critical (d) first descending; dead (c) is fresh and ties by recency
    expect(sortDeals(deals, 'staleness', 'desc', NOW).map((d) => d.id)).toEqual(['d', 'b', 'a', 'c'])
    expect(sortDeals(deals, 'staleness', 'asc', NOW)[3].id).toBe('d')
    expect(sortDeals(deals, 'stage', 'desc', NOW).map((d) => d.id)).toEqual(['c', 'a', 'd', 'b'])
  })

  it('sorts by a metric column with deals lacking the number at the bottom', () => {
    const irr: Record<string, number | null> = { a: 0.12, b: null, c: 0.2, d: 0.08 }
    const metricOf = (d: Deal) => irr[d.id] ?? null
    expect(sortDeals(deals, 'leveredIrr', 'desc', NOW, metricOf).map((d) => d.id)).toEqual(['c', 'a', 'd', 'b'])
    expect(sortDeals(deals, 'leveredIrr', 'asc', NOW, metricOf).map((d) => d.id)).toEqual(['d', 'a', 'c', 'b'])
    // No accessor: every deal lacks the number — recency order.
    expect(sortDeals(deals, 'equity', 'desc', NOW).map((d) => d.id)).toEqual(['b', 'a', 'c', 'd'])
    expect(toggleSort({ sortKey: 'stage', sortDir: 'asc' }, 'leveredIrr')).toEqual({ sortKey: 'leveredIrr', sortDir: 'desc' })
  })

  it('applyPipelineView composes filter + sort', () => {
    const ids = applyPipelineView(
      deals,
      { ...DEFAULT_VIEW_STATE, showTerminal: true, sortKey: 'name', sortDir: 'desc', tagFilter: ['core'] },
      NOW,
    ).map((d) => d.id)
    expect(ids).toEqual(['b', 'a'])
  })
})

describe('pipelineToCsv', () => {
  it('serializes the given rows with type, escaping, staleness and tags', () => {
    const rows = [
      deal({ name: 'Quote "Deal"', status: 'loi',
             inputs: { market: 'Miami, FL', dealType: 'acquisition' },
             updatedAt: '2026-06-01T00:00:00Z', tags: ['core', 'q "x"'] }), // 34 days old -> red badge
      deal({ id: 'y', name: 'Legacy', status: 'screening',
             updatedAt: '2026-07-04T00:00:00Z' }), // untyped -> empty Type cell
    ]
    const csv = pipelineToCsv(rows, NOW)
    const lines = csv.split('\n')
    expect(lines[0]).toBe('Name,Type,Market,Status,Last touched,Staleness,Tags')
    expect(lines[1]).toBe('"Quote ""Deal""",acquisition,"Miami, FL",loi,2026-06-01T00:00:00Z,stale 34d,"core; q ""x"""')
    expect(lines[2]).toBe('"Legacy",,"",screening,2026-07-04T00:00:00Z,,""')
  })
})
