import { describe, expect, it } from 'vitest'
import type { MappingPreviewRow } from '../types/mappingPreview'
import { formatCellValue, needsAttention, statusInfo, summarize, willWrite, withSharedTargets } from './mappingCoverage'

function row(partial: Partial<MappingPreviewRow>): MappingPreviewRow {
  return { fieldId: 'f', isOutput: false, hasValue: true, status: 'ok', resolvedRef: 'S!A1', ...partial }
}

describe('mapping coverage', () => {
  it('flags every way a template result can silently diverge from the deal', () => {
    expect(needsAttention(row({ status: 'ok' }))).toBe(false)
    expect(needsAttention(row({ status: 'unitWarning' }))).toBe(true)
    expect(needsAttention(row({ status: 'formula' }))).toBe(true)
    expect(needsAttention(row({ status: 'unresolved' }))).toBe(true)
    expect(needsAttention(row({ status: 'blank', cellValue: 0.05 }))).toBe(true) // template placeholder used
    expect(needsAttention(row({ status: 'blank', cellValue: null }))).toBe(false)
    expect(needsAttention(row({ status: 'unmapped', hasValue: true }))).toBe(false) // own filter
    expect(needsAttention(row({ status: 'unmapped', hasValue: false }))).toBe(false)
    expect(needsAttention(row({ status: 'output', isOutput: true, isFormula: false }))).toBe(true)
    expect(needsAttention(row({ status: 'output', isOutput: true, isFormula: true }))).toBe(false)
  })

  it('counts written fields the way inject_values does', () => {
    const rows = [
      row({ status: 'ok' }),
      row({ status: 'unitWarning' }),
      row({ status: 'tableSkips' }),
      row({ status: 'formula' }),
      row({ status: 'blank', cellValue: 3 }),
      row({ status: 'unmapped', hasValue: true }),
      row({ status: 'output', isOutput: true, isFormula: true }),
    ]
    expect(rows.filter(willWrite)).toHaveLength(3)
    const s = summarize(rows)
    expect(s).toMatchObject({ written: 3, unitWarnings: 1, notWritten: 1, blankUsingTemplateValue: 1, unmappedWithValue: 1, outputsMapped: 1 })
    expect(s.attention).toBe(4)
    expect(summarize(rows, new Set(['other'])).unmappedWithValue).toBe(0)
    expect(statusInfo(rows[3]).label).toMatch(/formula/)
  })

  it('flags two fields landing in the same cell', () => {
    const rows = withSharedTargets([
      row({ fieldId: 'purchasePrice', resolvedRef: 'A!B2' }),
      row({ fieldId: 'assessedValuePct', resolvedRef: 'A!B2', status: 'unitWarning' }),
      row({ fieldId: 'vacancyPct', resolvedRef: 'A!B5' }),
      row({ fieldId: 'unleveredIrr', resolvedRef: 'A!B8', isOutput: true, status: 'output', isFormula: true }),
      row({ fieldId: 'leveredIrr', resolvedRef: 'A!B8', isOutput: true, status: 'output', isFormula: true }),
      row({ fieldId: 'x', resolvedRef: null, status: 'unmapped' }),
    ])
    expect(rows[0].sharedWith).toEqual(['assessedValuePct'])
    expect(statusInfo(rows[0])).toEqual({ label: 'Same cell as another input', tone: 'error' })
    expect(rows[2].sharedWith).toBeUndefined()
    expect(statusInfo(rows[3]).tone).toBe('warn')
    expect(needsAttention(rows[4])).toBe(true)
  })

  it('shows cell values the way Excel formats them', () => {
    expect(formatCellValue(0.055, '0.00%')).toBe('5.50%')
    expect(formatCellValue(0.05, '0%')).toBe('5%')
    expect(formatCellValue(12500000, '$#,##0')).toBe('$12,500,000')
    expect(formatCellValue(5.5, 'General')).toBe('5.5')
    expect(formatCellValue(12500000, 'General')).toBe('12,500,000')
    expect(formatCellValue(null)).toBe('(empty)')
    expect(formatCellValue('Purchase Price')).toBe('Purchase Price')
  })
})
