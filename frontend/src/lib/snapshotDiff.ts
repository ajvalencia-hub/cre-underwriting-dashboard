// Snapshot diffing (I12). Pure/framework-free: compare two input blobs
// against the schema — scalars grouped by section with per-type formatting,
// table fields (unit mix, lease rows, opex lines) diffed BY ROW KEY with
// added/removed/changed classification, so reordering rows is not a change.

import { flattenFields } from './schemaFields'
import type { InputSchema } from '../types/schema'

export type ChangeKind = 'added' | 'removed' | 'changed'

export interface ScalarChange {
  fieldId: string
  label: string
  section: string
  type: string
  before: unknown
  after: unknown
  kind: ChangeKind
}

export interface CellChange {
  column: string
  before: unknown
  after: unknown
}

export interface RowChange {
  key: string
  kind: ChangeKind
  cells: CellChange[]
}

export interface TableChange {
  fieldId: string
  label: string
  section: string
  rows: RowChange[]
}

export interface SnapshotDiff {
  scalars: ScalarChange[]
  tables: TableChange[]
}

/** Row identity per table field; null = positional (index). */
const TABLE_ROW_KEYS: Record<string, string | null> = {
  unitMix: 'unitType',
  commercialLeases: 'suiteId',
  opexLineItems: 'category',
  waterfallTiers: null,
}

export function formatDiffValue(value: unknown, type: string): string {
  if (value === undefined || value === null || value === '') return '—'
  if (typeof value === 'number') {
    if (type === 'percent') return `${(value * 100).toFixed(2)}%`
    if (type === 'currency') return `$${value.toLocaleString()}`
    return String(value)
  }
  if (typeof value === 'boolean') return value ? 'on' : 'off'
  return String(value)
}

function equal(a: unknown, b: unknown): boolean {
  if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) < 1e-12
  if (a == null && b == null) return true
  return JSON.stringify(a) === JSON.stringify(b)
}

function rowKeyOf(row: unknown, keyField: string | null, index: number): string {
  if (keyField && typeof row === 'object' && row !== null) {
    const value = (row as Record<string, unknown>)[keyField]
    if (value !== undefined && value !== null && value !== '') return String(value)
  }
  return `#${index + 1}`
}

function diffTable(
  before: unknown,
  after: unknown,
  keyField: string | null,
): RowChange[] {
  const beforeRows = Array.isArray(before) ? before : []
  const afterRows = Array.isArray(after) ? after : []
  const byKey = (rows: unknown[]) => {
    const map = new Map<string, Record<string, unknown>>()
    rows.forEach((row, index) => {
      let key = rowKeyOf(row, keyField, index)
      while (map.has(key)) key += "'" // duplicate keys: disambiguate, don't drop
      map.set(key, (row ?? {}) as Record<string, unknown>)
    })
    return map
  }
  const beforeMap = byKey(beforeRows)
  const afterMap = byKey(afterRows)
  const changes: RowChange[] = []

  for (const [key, beforeRow] of beforeMap) {
    const afterRow = afterMap.get(key)
    if (afterRow === undefined) {
      changes.push({ key, kind: 'removed', cells: [] })
      continue
    }
    const columns = new Set([...Object.keys(beforeRow), ...Object.keys(afterRow)])
    const cells: CellChange[] = []
    for (const column of columns) {
      if (!equal(beforeRow[column], afterRow[column])) {
        cells.push({ column, before: beforeRow[column], after: afterRow[column] })
      }
    }
    if (cells.length > 0) changes.push({ key, kind: 'changed', cells })
  }
  for (const key of afterMap.keys()) {
    if (!beforeMap.has(key)) changes.push({ key, kind: 'added', cells: [] })
  }
  return changes
}

function classify(before: unknown, after: unknown): ChangeKind {
  const beforeEmpty = before === undefined || before === null || before === ''
  const afterEmpty = after === undefined || after === null || after === ''
  if (beforeEmpty && !afterEmpty) return 'added'
  if (!beforeEmpty && afterEmpty) return 'removed'
  return 'changed'
}

export function diffSnapshots(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
  schema: InputSchema,
): SnapshotDiff {
  const fields = flattenFields(schema)
  const meta = new Map(fields.map((f) => [f.id, f]))
  const scalars: ScalarChange[] = []
  const tables: TableChange[] = []

  const keys = new Set([...Object.keys(before), ...Object.keys(after)])
  for (const key of keys) {
    const b = before[key]
    const a = after[key]
    if (equal(b, a)) continue
    const field = meta.get(key)

    if (field?.type === 'table' || key in TABLE_ROW_KEYS) {
      const rows = diffTable(b, a, TABLE_ROW_KEYS[key] ?? null)
      if (rows.length > 0) {
        tables.push({
          fieldId: key,
          label: field?.label ?? key,
          section: field?.sectionLabel ?? 'Other',
          rows,
        })
      }
      continue
    }

    if (key === 'quickScreen' && typeof b === 'object' && typeof a === 'object') {
      const bq = (b ?? {}) as Record<string, unknown>
      const aq = (a ?? {}) as Record<string, unknown>
      for (const sub of new Set([...Object.keys(bq), ...Object.keys(aq)])) {
        if (equal(bq[sub], aq[sub])) continue
        scalars.push({
          fieldId: `quickScreen.${sub}`,
          label: sub,
          section: 'Quick Screen',
          type: 'number',
          before: bq[sub],
          after: aq[sub],
          kind: classify(bq[sub], aq[sub]),
        })
      }
      continue
    }

    scalars.push({
      fieldId: key,
      label: field?.label ?? key,
      section: field?.sectionLabel ?? 'Other',
      type: field?.type ?? 'text',
      before: b,
      after: a,
      kind: classify(b, a),
    })
  }

  const sectionOrder = [...new Set(fields.map((f) => f.sectionLabel))]
  const rank = (section: string) => {
    const index = sectionOrder.indexOf(section)
    return index === -1 ? sectionOrder.length : index
  }
  scalars.sort((x, y) => rank(x.section) - rank(y.section) || x.label.localeCompare(y.label))
  tables.sort((x, y) => rank(x.section) - rank(y.section))
  return { scalars, tables }
}
