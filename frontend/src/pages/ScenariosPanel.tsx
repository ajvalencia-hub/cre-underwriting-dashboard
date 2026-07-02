import { useEffect, useState } from 'react'
import { deleteScenario, fetchScenarios, saveScenario, updateScenario } from '../lib/api'
import { formatValue } from '../lib/formatValue'
import { flattenFields } from '../lib/schemaFields'
import type { InputSchema } from '../types/schema'
import type { Scenario } from '../types/scenario'
import type { TemplateSummary } from '../types/template'

interface ScenariosPanelProps {
  schema: InputSchema
  template: TemplateSummary | null
  mappingProfileId: string | null
  values: Record<string, unknown>
  onLoadScenario: (inputs: Record<string, unknown>) => void
}

const MAX_COMPARE = 3

export default function ScenariosPanel({
  schema,
  template,
  mappingProfileId,
  values,
  onLoadScenario,
}: ScenariosPanelProps) {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scenarioName, setScenarioName] = useState('Base Case')
  const [saving, setSaving] = useState(false)
  const [compareIds, setCompareIds] = useState<string[]>([])

  const fields = flattenFields(schema)
  const fieldById = new Map(fields.map((f) => [f.id, f]))

  useEffect(() => {
    if (!template) {
      setScenarios([])
      return
    }
    setLoading(true)
    fetchScenarios(template.id)
      .then(setScenarios)
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load scenarios'))
      .finally(() => setLoading(false))
  }, [template])

  async function handleSave() {
    if (!template || !mappingProfileId) return
    setSaving(true)
    setError(null)
    try {
      const existing = scenarios.find((s) => s.scenarioName === scenarioName)
      const saved = existing
        ? await updateScenario(existing.id, {
            scenarioName,
            templateId: template.id,
            mappingProfileId,
            inputs: values,
          })
        : await saveScenario({
            scenarioName,
            templateId: template.id,
            mappingProfileId,
            inputs: values,
          })
      setScenarios((prev) => [saved, ...prev.filter((s) => s.id !== saved.id)])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save scenario')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteScenario(id)
      setScenarios((prev) => prev.filter((s) => s.id !== id))
      setCompareIds((prev) => prev.filter((cid) => cid !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete scenario')
    }
  }

  function toggleCompare(id: string) {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((cid) => cid !== id)
      if (prev.length >= MAX_COMPARE) return prev
      return [...prev, id]
    })
  }

  const compared = scenarios.filter((s) => compareIds.includes(s.id))
  const compareFieldIds = Array.from(
    new Set(
      compared.flatMap((s) =>
        Object.keys(s.inputs).filter((k) => {
          const v = s.inputs[k]
          return v !== undefined && v !== null && v !== ''
        }),
      ),
    ),
  )

  if (!template) {
    return (
      <div className="max-w-3xl text-sm text-slate-500">
        Upload a template under "1. Template &amp; Mapping" to save and compare scenarios.
      </div>
    )
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Scenarios</h1>
        <p className="mt-1 text-slate-500">
          Save the current deal inputs as a named scenario, reload one later, or compare a few
          side by side.
        </p>
      </div>

      <div className="flex items-center gap-2">
        <input
          value={scenarioName}
          onChange={(e) => setScenarioName(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
          placeholder="Scenario name"
        />
        <button
          onClick={handleSave}
          disabled={saving || !mappingProfileId || !scenarioName.trim()}
          className="rounded bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
        >
          {saving ? 'Saving…' : 'Save current inputs as scenario'}
        </button>
        {!mappingProfileId && (
          <span className="text-xs text-slate-400">
            Save a mapping profile first to enable scenarios.
          </span>
        )}
      </div>

      {error && <div className="text-sm text-red-600">{error}</div>}

      <section>
        <h2 className="text-sm font-semibold tracking-wide text-slate-500">
          SAVED SCENARIOS ({scenarios.length})
        </h2>
        {loading && <div className="mt-2 text-sm text-slate-400">Loading…</div>}
        {!loading && scenarios.length === 0 && (
          <div className="mt-2 text-sm text-slate-400">No scenarios saved yet.</div>
        )}
        <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200 bg-white">
          {scenarios.map((s) => (
            <li key={s.id} className="flex items-center justify-between px-3 py-2 text-sm">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={compareIds.includes(s.id)}
                  onChange={() => toggleCompare(s.id)}
                  disabled={!compareIds.includes(s.id) && compareIds.length >= MAX_COMPARE}
                />
                <span className="font-medium">{s.scenarioName}</span>
                <span className="text-xs text-slate-400">
                  {new Date(s.updatedAt).toLocaleString()}
                </span>
              </label>
              <div className="flex gap-2">
                <button
                  onClick={() => onLoadScenario(s.inputs)}
                  className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                >
                  Load
                </button>
                <button
                  onClick={() => handleDelete(s.id)}
                  className="rounded border border-slate-300 px-2 py-0.5 text-xs text-red-500 hover:bg-red-50"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {compared.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold tracking-wide text-slate-500">
            COMPARISON ({compared.length} of {MAX_COMPARE})
          </h2>
          <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left">
                  <th className="px-3 py-2 font-medium text-slate-500">Field</th>
                  {compared.map((s) => (
                    <th key={s.id} className="px-3 py-2 font-medium text-slate-700">
                      {s.scenarioName}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {compareFieldIds.map((fieldId) => {
                  const field = fieldById.get(fieldId)
                  return (
                    <tr key={fieldId} className="border-b border-slate-50">
                      <td className="px-3 py-1.5 text-slate-500">{field?.label ?? fieldId}</td>
                      {compared.map((s) => (
                        <td key={s.id} className="px-3 py-1.5">
                          {formatValue(field, s.inputs[fieldId])}
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
