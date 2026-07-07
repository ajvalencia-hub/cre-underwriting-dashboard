import { useState } from 'react'
import ScalarInput from './fields/ScalarInput'
import { confirmExtraction } from '../lib/api'
import { mapExtractionToQuickScreen, type QuickScreenInputs } from '../lib/quickScreenMath'
import { flattenFields, type FlatField } from '../lib/schemaFields'
import {
  isNonEmptyUnitMix,
  mergeCommercialLeases,
  mergeUnitMix,
  toSchemaRows,
  type ProposedLeaseRow,
  type ProposedUnitMixRow,
} from '../lib/unitMixMerge'
import type { ExtractionResult } from '../types/extraction'
import type { InputSchema } from '../types/schema'

interface ExtractionReviewProps {
  schema: InputSchema
  result: ExtractionResult
  /** The deal's current unitMix rows — a non-empty table triggers the
   *  replace/merge choice instead of a silent overwrite. */
  currentUnitMix?: unknown
  /** Same for the deal's current lease-level commercial rent roll (H1). */
  currentCommercialLeases?: unknown
  onApply: (confirmedValues: Record<string, unknown>) => void
  /** Optional — seeds the Quick Screen back-of-napkin inputs from the
   *  currently-accepted fields instead of (or alongside) applying to full
   *  Deal Inputs. Omitted entirely when the caller doesn't support it. */
  onSeedQuickScreen?: (values: Partial<QuickScreenInputs>) => void
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

export default function ExtractionReview({
  schema,
  result,
  currentUnitMix,
  currentCommercialLeases,
  onApply,
  onSeedQuickScreen,
}: ExtractionReviewProps) {
  const fields = flattenFields(schema)
  const fieldById = new Map<string, FlatField>(fields.map((f) => [f.id, f]))

  const proposal = result.unitMixProposal ?? null
  const [mixRows, setMixRows] = useState<ProposedUnitMixRow[]>(() => proposal?.rows ?? [])
  const [includeUnitMix, setIncludeUnitMix] = useState(Boolean(proposal))
  const existingMixIsNonEmpty = isNonEmptyUnitMix(currentUnitMix)
  const [mergeMode, setMergeMode] = useState<'replace' | 'merge'>('merge')

  const leaseProposal = result.commercialLeaseProposal ?? null
  const [leaseRows, setLeaseRows] = useState<ProposedLeaseRow[]>(() => leaseProposal?.rows ?? [])
  const [includeLeases, setIncludeLeases] = useState(Boolean(leaseProposal))
  const existingLeasesNonEmpty = isNonEmptyUnitMix(currentCommercialLeases)
  const [leaseMergeMode, setLeaseMergeMode] = useState<'replace' | 'merge'>('merge')

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
  const [seeded, setSeeded] = useState(false)
  const [failuresAcknowledged, setFailuresAcknowledged] = useState(false)

  // With a dedicated unit-mix section, the generic unitMix field row would be
  // a confusing second apply path — the section supersedes it.
  const fieldEntries = Object.entries(result.fields).filter(
    ([fieldId]) => !(proposal && fieldId === 'unitMix'),
  )
  const checksByStatus = {
    pass: result.crossValidation.filter((c) => c.status === 'pass'),
    warn: result.crossValidation.filter((c) => c.status === 'warn'),
    fail: result.crossValidation.filter((c) => c.status === 'fail'),
  }
  const applyBlockedByFailures = checksByStatus.fail.length > 0 && !failuresAcknowledged

  function acceptAllHighConfidence() {
    setAccepted((prev) => {
      const next = { ...prev }
      for (const [fieldId, entry] of fieldEntries) {
        if (entry.confidence >= LOW_CONFIDENCE_THRESHOLD) next[fieldId] = true
      }
      return next
    })
  }

  /** Shared apply path — takes the accepted map explicitly rather than reading
   *  `accepted` state, so the one-click "accept high-confidence & apply" button
   *  can act on its own just-computed set in the same tick instead of racing a
   *  batched setState. */
  async function applyValues(acceptedMap: Record<string, boolean>) {
    setApplying(true)
    setError(null)
    try {
      const confirmedValues: Record<string, unknown> = {}
      for (const [fieldId, isAccepted] of Object.entries(acceptedMap)) {
        if (isAccepted && !(proposal && fieldId === 'unitMix')) {
          confirmedValues[fieldId] = editedValues[fieldId]
        }
      }
      if (proposal && includeUnitMix && mixRows.length > 0) {
        confirmedValues.unitMix = existingMixIsNonEmpty
          ? mergeUnitMix(currentUnitMix as Record<string, unknown>[], mixRows, mergeMode)
          : toSchemaRows(mixRows)
      }
      if (leaseProposal && includeLeases && leaseRows.length > 0) {
        confirmedValues.commercialLeases = existingLeasesNonEmpty
          ? mergeCommercialLeases(
              currentCommercialLeases as Record<string, unknown>[], leaseRows, leaseMergeMode,
            )
          : leaseRows
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

  function handleApply() {
    return applyValues(accepted)
  }

  /** Seeds the Quick Screen back-of-napkin inputs from the currently
   *  accepted+edited fields and the (possibly edited) unit-mix proposal —
   *  reuses the same accepted set the user already reviewed rather than a
   *  separate selection, so "checked" means the same thing everywhere on
   *  this screen. */
  function handleSeedQuickScreen() {
    const acceptedValues: Record<string, unknown> = {}
    for (const [fieldId, isAccepted] of Object.entries(accepted)) {
      if (isAccepted) acceptedValues[fieldId] = editedValues[fieldId]
    }
    const rows = includeUnitMix ? mixRows : []
    onSeedQuickScreen?.(mapExtractionToQuickScreen(acceptedValues, rows))
    setSeeded(true)
  }

  /** The one-click path: mark every >=60%-confidence field accepted (on top of
   *  whatever's already checked, including manually-accepted low-confidence
   *  fields) and apply immediately. Low-confidence fields are never swept in
   *  automatically — they still require an explicit checkbox. */
  function acceptHighConfidenceAndApply() {
    const next = { ...accepted }
    for (const [fieldId, entry] of fieldEntries) {
      if (entry.confidence >= LOW_CONFIDENCE_THRESHOLD) next[fieldId] = true
    }
    setAccepted(next)
    return applyValues(next)
  }

  const acceptedCount = Object.values(accepted).filter(Boolean).length
  const highConfidenceCount = fieldEntries.filter(
    ([, entry]) => entry.confidence >= LOW_CONFIDENCE_THRESHOLD,
  ).length

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
        <div className="space-y-2">
          <div className="text-xs font-semibold tracking-wide text-slate-500">
            CROSS-VALIDATION ({checksByStatus.pass.length} pass · {checksByStatus.warn.length}{' '}
            warn · {checksByStatus.fail.length} fail)
          </div>
          {checksByStatus.fail.map((check) => (
            <div
              key={check.rule}
              className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
            >
              ✕ <span className="font-semibold">{check.rule}</span> — {check.detail}
            </div>
          ))}
          {checksByStatus.warn.map((check) => (
            <div
              key={check.rule}
              className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700"
            >
              ⚠ <span className="font-semibold">{check.rule}</span> — {check.detail}
            </div>
          ))}
          {checksByStatus.pass.length > 0 && (
            <details className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
              <summary className="cursor-pointer select-none">
                ✓ {checksByStatus.pass.length} check(s) passed
              </summary>
              <ul className="mt-1 space-y-0.5">
                {checksByStatus.pass.map((check) => (
                  <li key={check.rule}>
                    <span className="font-semibold">{check.rule}</span> — {check.detail}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {checksByStatus.fail.length > 0 && (
            <label className="flex items-start gap-2 rounded-md border border-red-200 px-3 py-2 text-xs text-red-700">
              <input
                type="checkbox"
                checked={failuresAcknowledged}
                onChange={(e) => setFailuresAcknowledged(e.target.checked)}
                className="mt-0.5"
              />
              I've reviewed the failed check(s) above and want to apply these values anyway.
            </label>
          )}
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

      {proposal && (
        <div className="rounded-md border border-sky-200 bg-sky-50/50 p-3">
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-xs font-semibold tracking-wide text-slate-600">
              <input
                type="checkbox"
                checked={includeUnitMix}
                onChange={(e) => setIncludeUnitMix(e.target.checked)}
              />
              PROPOSED UNIT MIX ({mixRows.length} type{mixRows.length === 1 ? '' : 's'}, grouped by{' '}
              {proposal.groupedBy === 'bedBath'
                ? 'parsed bed/bath'
                : proposal.groupedBy === 'sf'
                  ? 'square footage'
                  : 'unit-type label'}
              )
            </label>
            {existingMixIsNonEmpty && includeUnitMix && (
              <div className="flex items-center gap-2 text-xs text-slate-600">
                <span className="text-amber-600">
                  The deal already has a unit mix —
                </span>
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    checked={mergeMode === 'merge'}
                    onChange={() => setMergeMode('merge')}
                  />
                  merge (replace matching types only)
                </label>
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    checked={mergeMode === 'replace'}
                    onChange={() => setMergeMode('replace')}
                  />
                  replace all
                </label>
              </div>
            )}
          </div>
          <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="px-2 py-1 font-medium">Unit type</th>
                  <th className="px-2 py-1 font-medium"># Units</th>
                  <th className="px-2 py-1 font-medium">Avg SF</th>
                  <th className="px-2 py-1 font-medium">In-place rent</th>
                  <th className="px-2 py-1 font-medium">Market rent</th>
                  <th className="px-2 py-1 font-medium text-slate-400">Occupancy</th>
                  <th className="px-2 py-1 font-medium text-slate-400">Source rows</th>
                </tr>
              </thead>
              <tbody>
                {mixRows.map((row, i) => {
                  const setCell = (key: keyof ProposedUnitMixRow, value: unknown) =>
                    setMixRows((prev) =>
                      prev.map((r, j) => (j === i ? { ...r, [key]: value } : r)),
                    )
                  const numberCell = (key: 'unitCount' | 'avgSf' | 'inPlaceRent' | 'marketRent') => (
                    <input
                      type="number"
                      value={row[key] ?? ''}
                      onChange={(e) =>
                        setCell(key, e.target.value === '' ? null : Number(e.target.value))
                      }
                      className="w-20 rounded border border-slate-200 px-1 py-0.5"
                    />
                  )
                  return (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="px-2 py-1">
                        <input
                          value={row.unitType}
                          onChange={(e) => setCell('unitType', e.target.value)}
                          className="w-28 rounded border border-slate-200 px-1 py-0.5"
                        />
                      </td>
                      <td className="px-2 py-1">{numberCell('unitCount')}</td>
                      <td className="px-2 py-1">{numberCell('avgSf')}</td>
                      <td className="px-2 py-1">{numberCell('inPlaceRent')}</td>
                      <td className="px-2 py-1">{numberCell('marketRent')}</td>
                      <td className="px-2 py-1 text-slate-400">
                        {row.occupancyPct != null
                          ? `${Math.round(row.occupancyPct * 100)}% (${row.occupiedCount}/${row.unitCount})`
                          : '—'}
                      </td>
                      <td className="px-2 py-1 text-slate-400">{row.sourceRowCount ?? '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            Occupancy and source-row counts are extraction provenance — only the schema columns are
            written to Deal Inputs.
          </p>
        </div>
      )}

      {leaseProposal && (
        <div className="rounded-md border border-indigo-200 bg-indigo-50/50 p-3">
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-xs font-semibold tracking-wide text-slate-600">
              <input
                type="checkbox"
                checked={includeLeases}
                onChange={(e) => setIncludeLeases(e.target.checked)}
              />
              PROPOSED COMMERCIAL LEASES ({leaseRows.length}) — escalations/free rent
              default to none; edit before applying
            </label>
            {existingLeasesNonEmpty && includeLeases && (
              <div className="flex items-center gap-2 text-xs text-slate-600">
                <span className="text-amber-600">Existing leases —</span>
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    checked={leaseMergeMode === 'merge'}
                    onChange={() => setLeaseMergeMode('merge')}
                  />
                  merge by suite
                </label>
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    checked={leaseMergeMode === 'replace'}
                    onChange={() => setLeaseMergeMode('replace')}
                  />
                  replace all
                </label>
              </div>
            )}
          </div>
          <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  {['Tenant', 'Suite', 'SF', 'Start', 'End', 'Rent PSF/yr', 'Recovery'].map((h) => (
                    <th key={h} className="px-2 py-1 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {leaseRows.map((row, i) => {
                  const setCell = (key: keyof ProposedLeaseRow, value: unknown) =>
                    setLeaseRows((prev) =>
                      prev.map((r, j) => (j === i ? { ...r, [key]: value } : r)),
                    )
                  const text = (key: 'tenant' | 'suiteId' | 'startDate' | 'endDate', width = 'w-24') => (
                    <input
                      value={(row[key] as string) ?? ''}
                      onChange={(e) => setCell(key, e.target.value || null)}
                      className={`${width} rounded border border-slate-200 px-1 py-0.5`}
                    />
                  )
                  return (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="px-2 py-1">{text('tenant', 'w-32')}</td>
                      <td className="px-2 py-1">{text('suiteId', 'w-14')}</td>
                      <td className="px-2 py-1">
                        <input
                          type="number"
                          value={row.sf ?? ''}
                          onChange={(e) => setCell('sf', e.target.value === '' ? null : Number(e.target.value))}
                          className="w-20 rounded border border-slate-200 px-1 py-0.5"
                        />
                      </td>
                      <td className="px-2 py-1">{text('startDate')}</td>
                      <td className="px-2 py-1">{text('endDate')}</td>
                      <td className="px-2 py-1">
                        <input
                          type="number"
                          value={row.baseRentPsfAnnual ?? ''}
                          onChange={(e) =>
                            setCell('baseRentPsfAnnual', e.target.value === '' ? null : Number(e.target.value))
                          }
                          className="w-20 rounded border border-slate-200 px-1 py-0.5"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <select
                          value={row.recoveryType}
                          onChange={(e) => setCell('recoveryType', e.target.value)}
                          className="rounded border border-slate-200 px-1 py-0.5"
                        >
                          {['gross', 'NNN', 'base_year_stop', 'fixed_psf'].map((o) => (
                            <option key={o} value={o}>{o}</option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
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

      {(fieldEntries.length > 0 || proposal || leaseProposal) && (
        <div className="flex flex-wrap items-center gap-2">
          {highConfidenceCount > 0 && (
            <button
              onClick={acceptHighConfidenceAndApply}
              disabled={applying || applyBlockedByFailures}
              title={
                applyBlockedByFailures
                  ? 'Acknowledge the failed cross-validation check(s) above first.'
                  : `Accepts the ${highConfidenceCount} field(s) at or above ${Math.round(LOW_CONFIDENCE_THRESHOLD * 100)}% confidence (plus anything already checked) and applies immediately. Low-confidence fields are never included automatically.`
              }
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
            >
              {applying
                ? 'Applying…'
                : `Accept high-confidence (≥${Math.round(LOW_CONFIDENCE_THRESHOLD * 100)}%) & apply`}
            </button>
          )}
          <button
            onClick={handleApply}
            disabled={
              applying ||
              (acceptedCount === 0 &&
                !(proposal && includeUnitMix && mixRows.length > 0) &&
                !(leaseProposal && includeLeases && leaseRows.length > 0)) ||
              applyBlockedByFailures
            }
            title={
              applyBlockedByFailures
                ? 'Acknowledge the failed cross-validation check(s) above first.'
                : undefined
            }
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            {applying ? 'Applying…' : applied ? 'Applied ✓ — apply again' : `Apply ${acceptedCount} confirmed value(s) as checked`}
          </button>
          {onSeedQuickScreen && (
            <button
              onClick={handleSeedQuickScreen}
              disabled={acceptedCount === 0}
              title="Fills in the Quick Screen back-of-napkin tab from the checked fields above — a fast sanity read, separate from Deal Inputs."
              className="rounded border border-sky-300 px-3 py-1.5 text-sm text-sky-700 hover:bg-sky-50 disabled:opacity-40"
            >
              {seeded ? 'Quick Screen seeded ✓ — seed again' : 'Seed Quick Screen from checked fields'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
