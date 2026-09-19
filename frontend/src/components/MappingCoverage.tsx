import { useMemo, useState } from 'react'
import { formatValue } from '../lib/formatValue'
import {
  TONE_CLASS,
  formatCellValue,
  isUnmappedWithValue,
  needsAttention,
  statusInfo,
  summarize,
} from '../lib/mappingCoverage'
import type { FlatField } from '../lib/schemaFields'
import type { MappingsById } from '../types/mapping'
import type { MappingPreviewRow } from '../types/mappingPreview'

type Filter = 'attention' | 'unmapped' | 'mapped' | 'all'

interface MappingCoverageProps {
  fields: FlatField[]
  /** Ids of fields that apply to this deal's type (visibility rules). */
  relevantIds: ReadonlySet<string>
  mappings: MappingsById
  preview: MappingPreviewRow[] | null
  previewError: string | null
  previewLoading: boolean
  values: Record<string, unknown>
  pickingFieldId: string | null
  onPick: (fieldId: string) => void
  onClear: (fieldId: string) => void
  onShowCell: (ref: string) => void
}

/**
 * Every field: its value on this deal, the cell it lands in, what that cell
 * holds in the template today, and whether Generate will write it — so the
 * mapping can be checked without opening the spreadsheet.
 */
export default function MappingCoverage({
  fields,
  relevantIds,
  mappings,
  preview,
  previewError,
  previewLoading,
  values,
  pickingFieldId,
  onPick,
  onClear,
  onShowCell,
}: MappingCoverageProps) {
  const rowsById = useMemo(() => new Map((preview ?? []).map((r) => [r.fieldId, r])), [preview])
  const labels = useMemo(() => new Map(fields.map((f) => [f.id, f.label])), [fields])
  const labelOf = (id: string) => labels.get(id) ?? id
  const summary = useMemo(() => summarize(preview ?? [], relevantIds), [preview, relevantIds])
  const retired = useMemo(() => (preview ?? []).filter((r) => r.retired), [preview])
  const [filter, setFilter] = useState<Filter | null>(null)
  // Default to the issues when there are any, otherwise to what's mapped.
  const activeFilter: Filter = filter ?? (summary.attention > 0 ? 'attention' : 'mapped')

  const sections = useMemo(() => {
    const bySection = new Map<string, { label: string; fields: FlatField[] }>()
    for (const f of fields) {
      const entry = bySection.get(f.sectionId) ?? { label: f.sectionLabel, fields: [] }
      entry.fields.push(f)
      bySection.set(f.sectionId, entry)
    }
    return [...bySection.entries()]
  }, [fields])

  function visible(field: FlatField): boolean {
    const row = rowsById.get(field.id)
    if (activeFilter === 'all') return true
    if (activeFilter === 'mapped') return field.id in mappings
    if (activeFilter === 'unmapped') return row ? isUnmappedWithValue(row) && relevantIds.has(field.id) : false
    return row ? needsAttention(row) : false
  }

  const chips: { id: Filter; label: string }[] = [
    { id: 'attention', label: `Needs attention (${summary.attention})` },
    { id: 'unmapped', label: `Not mapped, has a value (${summary.unmappedWithValue})` },
    { id: 'mapped', label: `Mapped (${Object.keys(mappings).length})` },
    { id: 'all', label: `All fields (${fields.length})` },
  ]

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="text-emerald-700">
          <strong>{summary.written}</strong> input(s) will be written
        </span>
        {summary.unmappedWithValue > 0 && (
          <span className="text-amber-700">
            <strong>{summary.unmappedWithValue}</strong> have values but aren't mapped
          </span>
        )}
        {summary.blankUsingTemplateValue > 0 && (
          <span className="text-amber-700">
            <strong>{summary.blankUsingTemplateValue}</strong> blank — template value used
          </span>
        )}
        {summary.unitWarnings > 0 && (
          <span className="text-amber-700">
            <strong>{summary.unitWarnings}</strong> unit check(s)
          </span>
        )}
        {summary.notWritten > 0 && (
          <span className="text-red-700">
            <strong>{summary.notWritten}</strong> mapped but not written
          </span>
        )}
        <span className="text-slate-500">{summary.outputsMapped} output(s) read back</span>
        {previewLoading && <span className="text-xs text-slate-400">Checking…</span>}
      </div>
      {previewError && (
        <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          Couldn't check the mapping against the template: {previewError}
        </div>
      )}

      <div className="mt-3 flex gap-1 text-xs" role="tablist" aria-label="Filter fields">
        {chips.map((chip) => (
          <button
            key={chip.id}
            role="tab"
            aria-selected={activeFilter === chip.id}
            onClick={() => setFilter(chip.id)}
            className={`rounded border px-2 py-1 ${
              activeFilter === chip.id
                ? 'border-slate-900 bg-slate-900 text-white'
                : 'border-slate-300 text-slate-600 hover:bg-slate-50'
            }`}
          >
            {chip.label}
          </button>
        ))}
      </div>

      {activeFilter === 'unmapped' && (
        <p className="mt-2 text-xs text-slate-500">
          These have values on this deal but no cell in the template, so the template calculates with its own
          numbers for them. That's fine for assumptions your model owns — map any that the template has an input
          cell for.
        </p>
      )}

      <table className="mt-2 w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
            <th className="py-1.5 pr-2 font-medium">Field</th>
            <th className="py-1.5 pr-2 text-right font-medium">This deal</th>
            <th className="py-1.5 pr-2 font-medium">Template cell</th>
            <th className="py-1.5 pr-2 text-right font-medium">Cell holds now</th>
            <th className="py-1.5 pr-2 font-medium">Status</th>
            <th className="py-1.5 font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        {sections.map(([sectionId, section]) => {
          const shown = section.fields.filter(visible)
          if (shown.length === 0) return null
          const mappedHere = section.fields.filter((f) => f.id in mappings).length
          return (
            <tbody key={sectionId}>
              <tr>
                <td colSpan={6} className="pt-3 pb-1 text-xs font-semibold tracking-wide text-slate-500">
                  {section.label.toUpperCase()}{' '}
                  <span className="font-normal text-slate-400">
                    · {mappedHere}/{section.fields.length} mapped
                  </span>
                </td>
              </tr>
              {shown.map((field) => {
                const row = rowsById.get(field.id)
                const info = row ? statusInfo(row) : null
                const entry = mappings[field.id]
                const isOutput = row?.isOutput ?? false
                return (
                  <tr
                    key={field.id}
                    className={`border-b border-slate-100 align-top ${pickingFieldId === field.id ? 'bg-indigo-100' : ''}`}
                  >
                    <td className="py-1.5 pr-2">
                      {field.label}
                      {field.required && <span className="ml-1 text-red-400">*</span>}
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums text-slate-700">
                      {isOutput ? <span className="text-slate-400">output</span> : formatValue(field, values[field.id])}
                    </td>
                    <td className="py-1.5 pr-2 font-mono text-xs">
                      {row?.resolvedRef ? (
                        <button
                          onClick={() => onShowCell(row.resolvedRef!)}
                          className="text-sky-700 hover:underline"
                          title="Show this cell in the sheet preview"
                        >
                          {row.resolvedRef}
                        </button>
                      ) : entry ? (
                        <span className="text-slate-400">{entry.ref ?? entry.anchor}</span>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                      {entry?.target === 'namedRange' && (
                        <div className="text-[10px] text-slate-400">via name {entry.ref}</div>
                      )}
                      {entry?.source === 'auto' && <div className="text-[10px] text-slate-400">auto-matched</div>}
                    </td>
                    <td className="py-1.5 pr-2 text-right text-xs tabular-nums text-slate-600">
                      {row?.cellFormula ? (
                        <span className="font-mono text-amber-700" title={row.cellFormula}>
                          ƒ {row.cellFormula.slice(0, 18)}
                        </span>
                      ) : row && 'cellValue' in row ? (
                        formatCellValue(row.cellValue, row.numberFormat)
                      ) : row?.tableRows ? (
                        `${row.tableRows}×${row.tableColumns}`
                      ) : (
                        ''
                      )}
                    </td>
                    <td className="py-1.5 pr-2">
                      {info && (
                        <span className={`inline-block rounded border px-1.5 py-0.5 text-[11px] ${TONE_CLASS[info.tone]}`}>
                          {info.label}
                        </span>
                      )}
                      {row?.sharedWith && row.sharedWith.length > 0 && (
                        <div className="mt-0.5 text-xs text-slate-500">
                          Also mapped here: {row.sharedWith.map((id) => labelOf(id)).join(', ')}.{' '}
                          {row.isOutput
                            ? 'At least one of these outputs is reading the wrong cell.'
                            : 'Only the last value written survives — map each input to its own cell.'}
                        </div>
                      )}
                      {row?.message && <div className="mt-0.5 text-xs text-slate-500">{row.message}</div>}
                    </td>
                    <td className="py-1.5 text-right whitespace-nowrap">
                      <button
                        onClick={() => onPick(field.id)}
                        className="mr-1 rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                      >
                        {entry ? 'Change' : 'Pick cell'}
                      </button>
                      {entry && (
                        <button
                          onClick={() => onClear(field.id)}
                          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-500 hover:bg-slate-50"
                        >
                          Clear
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          )
        })}
      </table>
      {retired.length > 0 && (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <div className="font-medium">Mappings for fields this app no longer has</div>
          <ul className="mt-1 space-y-1">
            {retired.map((row) => (
              <li key={row.fieldId} className="flex flex-wrap items-center gap-2">
                <code className="text-xs">{row.fieldId}</code>
                <span className="text-xs">→ {row.resolvedRef ?? mappings[row.fieldId]?.ref ?? '—'}</span>
                <span className={`rounded border px-1.5 text-[11px] ${TONE_CLASS[statusInfo(row).tone]}`}>
                  {statusInfo(row).label}
                </span>
                <button type="button" className="text-xs text-amber-900 underline" onClick={() => onClear(row.fieldId)}>
                  Remove mapping
                </button>
                {row.message && <div className="w-full text-xs">{row.message}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {preview &&
        sections.every(([, s]) => s.fields.filter(visible).length === 0) &&
        !(activeFilter === 'attention' && retired.some(needsAttention)) && (
        <div className="mt-3 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {activeFilter === 'attention'
            ? 'Nothing needs attention — every mapped input will be written as shown.'
            : activeFilter === 'unmapped'
              ? 'Every field with a value on this deal is mapped.'
              : 'No mapped fields yet. Switch to "All fields" and use Pick cell.'}
        </div>
      )}
    </div>
  )
}
