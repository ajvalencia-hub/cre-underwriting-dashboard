import { useEffect, useMemo, useState } from 'react'
import {
  createPreset,
  deletePreset,
  fetchPresetFields,
  fetchPresets,
  type AssumptionPreset,
} from '../lib/api'
import { presetDiff, selectedChanges, type PresetDiffRow } from '../lib/presetDiff'
import { flattenFields } from '../lib/schemaFields'
import type { InputSchema } from '../types/schema'

interface PresetsPanelProps {
  schema: InputSchema
  values: Record<string, unknown>
  onApply: (patch: Record<string, unknown>) => void
}

function formatValue(v: unknown, type: string | undefined): string {
  if (v === undefined || v === null || v === '') return '—'
  if (typeof v === 'number' && type === 'percent') return `${(v * 100).toFixed(2)}%`
  if (typeof v === 'number' && type === 'currency') return `$${v.toLocaleString()}`
  return String(v)
}

/** Assumption presets (H8): pick → preview diff → apply the checked rows.
 *  Nothing changes without the explicit Apply click. */
export default function PresetsPanel({ schema, values, onApply }: PresetsPanelProps) {
  const [presets, setPresets] = useState<AssumptionPreset[]>([])
  const [presetFields, setPresetFields] = useState<string[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [diffRows, setDiffRows] = useState<PresetDiffRow[] | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [saveName, setSaveName] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fieldById = useMemo(() => {
    const map = new Map<string, { label: string; type?: string }>()
    for (const field of flattenFields(schema)) {
      map.set(field.id, { label: field.label, type: field.type })
    }
    return map
  }, [schema])

  useEffect(() => {
    fetchPresets().then(setPresets).catch(() => setPresets([]))
    fetchPresetFields().then(setPresetFields).catch(() => setPresetFields([]))
  }, [])

  const selected = presets.find((p) => p.id === selectedId) ?? null

  function handlePreview() {
    if (!selected) return
    const rows = presetDiff(values, selected.values)
    setDiffRows(rows)
    setChecked(new Set(rows.filter((r) => r.changed).map((r) => r.fieldId)))
    setMessage(null)
  }

  function handleApply() {
    if (!diffRows) return
    const patch = selectedChanges(diffRows, checked)
    onApply(patch)
    setDiffRows(null)
    setMessage(`Applied ${Object.keys(patch).length} field(s) from '${selected?.name}'.`)
  }

  async function handleSave() {
    const captured: Record<string, unknown> = {}
    for (const fieldId of presetFields) {
      const v = values[fieldId]
      if (v !== undefined && v !== null && v !== '') captured[fieldId] = v
    }
    setSaving(true)
    setError(null)
    try {
      const created = await createPreset({ name: saveName, values: captured })
      setPresets((prev) => [...prev, created])
      setSaveName('')
      setMessage(`Saved '${created.name}' (${Object.keys(created.values).length} fields).`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!selected) return
    try {
      await deletePreset(selected.id)
      setPresets((prev) => prev.filter((p) => p.id !== selected.id))
      setSelectedId('')
      setDiffRows(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  return (
    <div className="mb-4 rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold tracking-wide text-slate-500">
          ASSUMPTION PRESETS
        </span>
        <select
          value={selectedId}
          onChange={(e) => {
            setSelectedId(e.target.value)
            setDiffRows(null)
            setMessage(null)
          }}
          className="rounded border border-slate-200 px-2 py-1 text-sm"
        >
          <option value="">Select a preset…</option>
          {presets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.name}
              {preset.source === 'seed' ? ' (seed)' : ''}
            </option>
          ))}
        </select>
        <button
          onClick={handlePreview}
          disabled={!selected}
          className="rounded border border-sky-600 px-2 py-1 text-xs text-sky-700 hover:bg-sky-50 disabled:opacity-40"
        >
          Preview & apply
        </button>
        {selected && (
          <button
            onClick={handleDelete}
            className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-400 hover:text-red-600"
          >
            Delete
          </button>
        )}
        <span className="mx-2 h-4 border-l border-slate-200" />
        <input
          value={saveName}
          onChange={(e) => setSaveName(e.target.value)}
          placeholder="Save current assumptions as…"
          className="rounded border border-slate-200 px-2 py-1 text-sm"
        />
        <button
          onClick={handleSave}
          disabled={saving || !saveName.trim()}
          className="rounded border border-emerald-600 px-2 py-1 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
        >
          {saving ? 'Saving…' : 'Save preset'}
        </button>
      </div>
      {selected?.description && !diffRows && (
        <div className="mt-1 text-xs text-slate-400">{selected.description}</div>
      )}
      {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
      {message && <div className="mt-2 text-xs text-emerald-700">{message}</div>}

      {diffRows && (
        <div className="mt-3">
          {diffRows.filter((r) => r.changed).length === 0 ? (
            <div className="text-xs text-slate-400">
              This preset matches the current assumptions — nothing to apply.
            </div>
          ) : (
            <>
              <table className="w-full max-w-xl text-xs">
                <thead>
                  <tr className="text-left text-slate-400">
                    <th className="py-1 pr-2 font-medium" />
                    <th className="py-1 pr-3 font-medium">Field</th>
                    <th className="py-1 pr-3 font-medium">Current</th>
                    <th className="py-1 font-medium">Preset</th>
                  </tr>
                </thead>
                <tbody>
                  {diffRows.map((row) => {
                    const meta = fieldById.get(row.fieldId)
                    return (
                      <tr
                        key={row.fieldId}
                        className={row.changed ? 'text-slate-700' : 'text-slate-300'}
                      >
                        <td className="py-0.5 pr-2">
                          <input
                            type="checkbox"
                            disabled={!row.changed}
                            checked={row.changed && checked.has(row.fieldId)}
                            onChange={(e) => {
                              const next = new Set(checked)
                              if (e.target.checked) next.add(row.fieldId)
                              else next.delete(row.fieldId)
                              setChecked(next)
                            }}
                          />
                        </td>
                        <td className="py-0.5 pr-3">{meta?.label ?? row.fieldId}</td>
                        <td className="py-0.5 pr-3">{formatValue(row.current, meta?.type)}</td>
                        <td className={`py-0.5 ${row.changed ? 'font-medium' : ''}`}>
                          {formatValue(row.proposed, meta?.type)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <div className="mt-2 flex gap-2">
                <button
                  onClick={handleApply}
                  disabled={checked.size === 0}
                  className="rounded bg-emerald-600 px-3 py-1 text-xs text-white hover:bg-emerald-700 disabled:opacity-40"
                >
                  Apply {checked.size} change(s)
                </button>
                <button
                  onClick={() => setDiffRows(null)}
                  className="rounded border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:bg-slate-50"
                >
                  Cancel
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
