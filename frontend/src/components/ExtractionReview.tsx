import { useState } from 'react'
import ScalarInput from './fields/ScalarInput'
import { confirmExtraction } from '../lib/api'
import { flattenFields, type FlatField } from '../lib/schemaFields'
import type { ExtractionResult } from '../types/extraction'
import type { InputSchema } from '../types/schema'

interface ExtractionReviewProps {
  schema: InputSchema
  result: ExtractionResult
  onApply: (confirmedValues: Record<string, unknown>) => void
}

const LOW_CONFIDENCE_THRESHOLD = 0.6

function confidenceBadgeClass(confidence: number): string {
  if (confidence >= LOW_CONFIDENCE_THRESHOLD) return 'bg-emerald-100 text-emerald-700'
  if (confidence > 0) return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-500'
}

function isTableValue(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value)
}

export default function ExtractionReview({ schema, result, onApply }: ExtractionReviewProps) {
  const fields = flattenFields(schema)
  const fieldById = new Map<string, FlatField>(fields.map((f) => [f.id, f]))

  const [accepted, setAccepted] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {}
    for (const [fieldId, entry] of Object.entries(result.fields)) {
      initial[fieldId] = entry.confidence >= LOW_CONFIDENCE_THRESHOLD
    }
    return initial
  })
  const [editedValues, setEditedValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {}
    for (const [fieldId, entry] of Object.entries(result.fields)) {
      initial[fieldId] = entry.value
    }
    return initial
  })
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [applied, setApplied] = useState(false)

  const fieldEntries = Object.entries(result.fields)

  function acceptAllHighConfidence() {
    setAccepted((prev) => {
      const next = { ...prev }
      for (const [fieldId, entry] of fieldEntries) {
        if (entry.confidence >= LOW_CONFIDENCE_THRESHOLD) next[fieldId] = true
      }
      return next
    })
  }

  async function handleApply() {
    setApplying(true)
    setError(null)
    try {
      const confirmedValues: Record<string, unknown> = {}
      for (const [fieldId, isAccepted] of Object.entries(accepted)) {
        if (isAccepted) confirmedValues[fieldId] = editedValues[fieldId]
      }
      await confirmExtraction(result.id, confirmedValues)
      onApply(confirmedValues)
      setApplied(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not apply extracted values')
    } finally {
      setApplying(false)
    }
  }

  const acceptedCount = Object.values(accepted).filter(Boolean).length

  return (
    <div className="mt-6 space-y-4 rounded-md border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-slate-500">
          EXTRACTION REVIEW ({fieldEntries.length} field{fieldEntries.length === 1 ? '' : 's'} found)
        </h2>
        <button
          onClick={acceptAllHighConfidence}
          className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
        >
          Accept all high-confidence (≥{Math.round(LOW_CONFIDENCE_THRESHOLD * 100)}%)
        </button>
      </div>

      {result.warnings.length > 0 && (
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          {result.warnings.map((w, i) => (
            <div key={i}>{w}</div>
          ))}
        </div>
      )}

      {result.crossValidation.length > 0 && (
        <div className="space-y-1">
          {result.crossValidation.map((check, i) => (
            <div
              key={i}
              className={`rounded-md border px-3 py-2 text-xs ${
                check.severity === 'warning'
                  ? 'border-amber-200 bg-amber-50 text-amber-700'
                  : 'border-sky-200 bg-sky-50 text-sky-700'
              }`}
            >
              ⚠ {check.message}
            </div>
          ))}
        </div>
      )}

      {fieldEntries.length === 0 ? (
        <p className="text-sm text-slate-400">
          No fields extracted. See warnings above — likely the LLM extraction path (needed for
          narrative documents) isn't configured.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              <th className="py-1.5 pr-2 font-medium">Field</th>
              <th className="py-1.5 pr-2 font-medium">Source</th>
              <th className="py-1.5 pr-2 font-medium">Confidence</th>
              <th className="py-1.5 pr-2 font-medium">Value</th>
              <th className="py-1.5 font-medium">Accept</th>
            </tr>
          </thead>
          <tbody>
            {fieldEntries.map(([fieldId, entry]) => {
              const field = fieldById.get(fieldId)
              const value = editedValues[fieldId]
              return (
                <tr key={fieldId} className="border-b border-slate-50 align-top">
                  <td className="py-2 pr-2">
                    <div className="font-medium">{field?.label ?? fieldId}</div>
                    <div className="font-mono text-[11px] text-slate-400">{fieldId}</div>
                    {entry.notes && <div className="mt-0.5 text-[11px] text-slate-400">{entry.notes}</div>}
                  </td>
                  <td className="py-2 pr-2 text-xs text-slate-500">
                    {entry.sourceRef.doc}
                    {entry.sourceRef.sheet && ` · ${entry.sourceRef.sheet}`}
                    {entry.sourceRef.page != null && ` · p.${entry.sourceRef.page}`}
                    {entry.sourceRef.row != null && ` · row ${entry.sourceRef.row}`}
                    <div className="mt-0.5 text-[10px] uppercase text-slate-400">{entry.source}</div>
                  </td>
                  <td className="py-2 pr-2">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] ${confidenceBadgeClass(entry.confidence)}`}>
                      {Math.round(entry.confidence * 100)}%
                    </span>
                  </td>
                  <td className="py-2 pr-2">
                    {isTableValue(value) ? (
                      <div className="max-w-xs overflow-x-auto rounded border border-slate-200">
                        <table className="w-full text-xs">
                          <thead className="bg-slate-50">
                            <tr>
                              {value[0] &&
                                Object.keys(value[0]).map((col) => (
                                  <th key={col} className="whitespace-nowrap px-1.5 py-1 text-left font-medium">
                                    {col}
                                  </th>
                                ))}
                            </tr>
                          </thead>
                          <tbody>
                            {value.map((row, i) => (
                              <tr key={i} className="border-t border-slate-100">
                                {Object.values(row).map((cell, j) => (
                                  <td key={j} className="whitespace-nowrap px-1.5 py-1">
                                    {cell === null || cell === undefined ? '' : String(cell)}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : field ? (
                      <div className="max-w-xs">
                        <ScalarInput
                          type={field.type}
                          value={value}
                          options={field.options}
                          onChange={(v) => setEditedValues((prev) => ({ ...prev, [fieldId]: v }))}
                        />
                      </div>
                    ) : (
                      <span className="text-slate-600">{String(value)}</span>
                    )}
                  </td>
                  <td className="py-2">
                    <input
                      type="checkbox"
                      checked={accepted[fieldId] ?? false}
                      onChange={(e) => setAccepted((prev) => ({ ...prev, [fieldId]: e.target.checked }))}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {result.unmatched.length > 0 && (
        <div>
          <div className="text-xs font-medium text-slate-400">
            UNMATCHED (found, but doesn't map to an existing field — informational only)
          </div>
          <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
            {result.unmatched.map((u, i) => (
              <li key={i}>
                {u.suggestedLabel}: <span className="text-slate-700">{String(u.value)}</span>{' '}
                <span className="text-slate-400">({Math.round(u.confidence * 100)}%)</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <div className="text-sm text-red-600">{error}</div>}

      {fieldEntries.length > 0 && (
        <button
          onClick={handleApply}
          disabled={applying || acceptedCount === 0}
          className="rounded bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
        >
          {applying ? 'Applying…' : applied ? 'Applied ✓ — apply again' : `Apply ${acceptedCount} confirmed value(s) to Deal Inputs`}
        </button>
      )}
    </div>
  )
}
