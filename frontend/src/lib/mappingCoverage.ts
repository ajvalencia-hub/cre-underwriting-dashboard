// Presentation logic for the mapping coverage view and the Generate
// pre-flight/report. The statuses come from POST /api/mappings/preview,
// which mirrors exactly what generation writes or skips.

import type { MappingPreviewRow, PreviewStatus } from '../types/mappingPreview'
import { withDollar } from './money'

export type Tone = 'ok' | 'warn' | 'error' | 'muted' | 'info'

export interface StatusInfo {
  label: string
  tone: Tone
}

/** Mark fields whose value lands in (or is read from) the same cell as
 *  another field of the same kind. Two inputs in one cell means only the
 *  last one written survives; two outputs in one cell means at least one
 *  of them is reading the wrong number. */
export function withSharedTargets(rows: MappingPreviewRow[]): MappingPreviewRow[] {
  const byCell = new Map<string, string[]>()
  for (const row of rows) {
    if (!row.resolvedRef || row.status === 'unmapped') continue
    const key = `${row.isOutput ? 'out' : 'in'}|${row.resolvedRef}`
    byCell.set(key, [...(byCell.get(key) ?? []), row.fieldId])
  }
  return rows.map((row) => {
    if (!row.resolvedRef || row.status === 'unmapped') return row
    const ids = byCell.get(`${row.isOutput ? 'out' : 'in'}|${row.resolvedRef}`) ?? []
    return ids.length > 1 ? { ...row, sharedWith: ids.filter((id) => id !== row.fieldId) } : row
  })
}

export function statusInfo(row: MappingPreviewRow): StatusInfo {
  if (row.sharedWith && row.sharedWith.length > 0) {
    return row.isOutput
      ? { label: 'Same cell as another output', tone: 'warn' }
      : { label: 'Same cell as another input', tone: 'error' }
  }
  if (row.retired) {
    return willWrite(row)
      ? { label: 'Retired field — still written', tone: 'warn' }
      : row.status === 'unresolved'
        ? { label: 'Retired field — target missing', tone: 'error' }
        : { label: 'Retired field — nothing written', tone: 'muted' }
  }
  switch (row.status) {
    case 'ok':
      return { label: 'Will write', tone: 'ok' }
    case 'unitWarning':
      return { label: 'Check units', tone: 'warn' }
    case 'blank':
      return row.cellValue === null || row.cellValue === undefined || row.cellValue === ''
        ? { label: 'Blank on this deal', tone: 'muted' }
        : { label: 'Blank — template value used', tone: 'warn' }
    case 'formula':
      return { label: 'Not written — formula cell', tone: 'error' }
    case 'multiCell':
      return { label: 'Not written — range', tone: 'error' }
    case 'unresolved':
      return { label: 'Not written — target missing', tone: 'error' }
    case 'tableSkips':
      return { label: 'Some cells skipped', tone: 'warn' }
    case 'unmapped':
      return row.hasValue ? { label: 'Not mapped — template value used', tone: 'warn' } : { label: 'Not mapped', tone: 'muted' }
    case 'output':
      return row.isFormula === false ? { label: 'Output is a fixed value', tone: 'warn' } : { label: 'Read back after recalc', tone: 'info' }
  }
}

export const TONE_CLASS: Record<Tone, string> = {
  ok: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  warn: 'bg-amber-50 text-amber-700 border-amber-200',
  error: 'bg-red-50 text-red-700 border-red-200',
  muted: 'bg-slate-50 text-slate-500 border-slate-200',
  info: 'bg-sky-50 text-sky-700 border-sky-200',
}

/** A mapped field whose template result could differ from the deal on
 *  screen. Unmapped fields are reported separately (see isUnmappedWithValue):
 *  a template legitimately owns many assumptions itself. */
export function needsAttention(row: MappingPreviewRow): boolean {
  if (row.status === 'unmapped') return false
  const tone = statusInfo(row).tone
  return tone === 'warn' || tone === 'error'
}

export function isUnmappedWithValue(row: MappingPreviewRow): boolean {
  return row.status === 'unmapped' && row.hasValue && !row.isOutput
}

const WRITTEN: ReadonlySet<PreviewStatus> = new Set(['ok', 'unitWarning', 'tableSkips'])

export function willWrite(row: MappingPreviewRow): boolean {
  return !row.isOutput && WRITTEN.has(row.status)
}

export interface CoverageSummary {
  written: number
  unitWarnings: number
  blankUsingTemplateValue: number
  unmappedWithValue: number
  notWritten: number // formula / range / missing target
  outputsMapped: number
  attention: number
}

/** `relevant`: field ids that apply to this deal (visible for its type);
 *  unmapped fields outside it aren't counted. */
export function summarize(rows: MappingPreviewRow[], relevant?: ReadonlySet<string>): CoverageSummary {
  const s: CoverageSummary = {
    written: 0,
    unitWarnings: 0,
    blankUsingTemplateValue: 0,
    unmappedWithValue: 0,
    notWritten: 0,
    outputsMapped: 0,
    attention: 0,
  }
  for (const row of rows) {
    if (willWrite(row)) s.written++
    if (row.status === 'unitWarning') s.unitWarnings++
    if (row.status === 'blank' && statusInfo(row).tone === 'warn') s.blankUsingTemplateValue++
    if (isUnmappedWithValue(row) && (!relevant || relevant.has(row.fieldId))) s.unmappedWithValue++
    if (row.status === 'formula' || row.status === 'multiCell' || row.status === 'unresolved') s.notWritten++
    if (row.isOutput && row.status === 'output') s.outputsMapped++
    if (needsAttention(row)) s.attention++
  }
  return s
}

function decimalsIn(format: string): number {
  const m = format.match(/0\.(0+)/)
  return m ? m[1].length : 0
}

/** Render a raw cell value roughly the way Excel shows it, from its number
 *  format — so "0.055" in a 0.00% cell reads as "5.50%". */
export function formatCellValue(value: unknown, numberFormat?: string): string {
  if (value === null || value === undefined || value === '') return '(empty)'
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE'
  if (typeof value !== 'number') return String(value)
  const fmt = numberFormat ?? 'General'
  if (fmt.includes('%')) return `${(value * 100).toFixed(decimalsIn(fmt))}%`
  const decimals = fmt === 'General' ? (Number.isInteger(value) ? 0 : Math.min(6, `${value}`.split('.')[1]?.length ?? 0)) : decimalsIn(fmt)
  const grouped = fmt === 'General' ? Math.abs(value) >= 10000 : fmt.includes(',')
  const text = value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping: grouped,
  })
  return fmt.includes('$') ? withDollar(text) : text
}

export interface GenerateCheckResult {
  rows: MappingPreviewRow[]
  issues: MappingPreviewRow[]
  unmappedWithValue: MappingPreviewRow[]
}

/** What Generate is about to do with this deal — mapped problems plus
 *  relevant fields that have a value but no cell. */
export function checkForGenerate(rows: MappingPreviewRow[], relevantIds: ReadonlySet<string>): GenerateCheckResult {
  return {
    rows,
    issues: rows.filter(needsAttention),
    unmappedWithValue: rows.filter((r) => isUnmappedWithValue(r) && relevantIds.has(r.fieldId)),
  }
}
