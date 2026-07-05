import { describe, expect, it } from 'vitest'
import {
  applyView,
  deleteView,
  loadViews,
  pipelineToCsv,
  saveView,
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
    name: 'Miami active',
    marketFilter: 'miami',
    sortKey: 'updated',
    showTerminal: false,
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
})

describe('applyView', () => {
  const deals = [
    deal({ id: 'a', name: 'Alpha', status: 'loi', inputs: { market: 'Miami' } }),
    deal({ id: 'b', name: 'Beta', status: 'screening', updatedAt: '2026-07-04T00:00:00Z' }),
    deal({ id: 'c', name: 'Gamma', status: 'dead', inputs: { market: 'Miami' } }),
  ]

  it('hides terminal stages by default and filters by market or name', () => {
    expect(applyView(deals, '', 'stage', false).map((d) => d.id)).toEqual(['b', 'a'])
    expect(applyView(deals, 'miami', 'stage', true).map((d) => d.id)).toEqual(['a', 'c'])
    expect(applyView(deals, 'beta', 'stage', false).map((d) => d.id)).toEqual(['b'])
  })

  it('sorts by the chosen key', () => {
    expect(applyView(deals, '', 'name', true).map((d) => d.name)).toEqual([
      'Alpha', 'Beta', 'Gamma',
    ])
    expect(applyView(deals, '', 'updated', false)[0].id).toBe('b') // most recent
  })
})

describe('pipelineToCsv', () => {
  it('serializes the given rows with escaping and staleness', () => {
    const rows = [
      deal({ name: 'Quote "Deal"', status: 'loi', inputs: { market: 'Miami, FL' },
             updatedAt: '2026-06-01T00:00:00Z' }), // 34 days old -> red badge
    ]
    const csv = pipelineToCsv(rows, NOW)
    const lines = csv.split('\n')
    expect(lines[0]).toBe('Name,Market,Status,Last touched,Staleness')
    expect(lines[1]).toBe('"Quote ""Deal""","Miami, FL",loi,2026-06-01T00:00:00Z,stale 34d')
  })
})
