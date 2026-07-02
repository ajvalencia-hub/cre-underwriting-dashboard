import { useState } from 'react'
import { generateWorkbook } from '../lib/api'
import type { TemplateSummary } from '../types/template'

interface GeneratePanelProps {
  template: TemplateSummary | null
  mappingProfileId: string | null
  values: Record<string, unknown>
  onGenerated?: (outputs: Record<string, unknown>) => void
}

export default function GeneratePanel({
  template,
  mappingProfileId,
  values,
  onGenerated,
}: GeneratePanelProps) {
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<{ warnings: string[]; writtenCount: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [recalc, setRecalc] = useState(true)

  const ready = Boolean(template && mappingProfileId)

  async function handleGenerate() {
    if (!template || !mappingProfileId) return
    setGenerating(true)
    setError(null)
    setResult(null)
    try {
      const { blob, filename, warnings, writtenCount, outputs } = await generateWorkbook({
        templateId: template.id,
        mappingProfileId,
        values,
        recalc,
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setResult({ warnings, writtenCount })
      if (Object.keys(outputs).length > 0) onGenerated?.(outputs)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generate failed')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="sticky bottom-0 -mx-8 border-t border-slate-200 bg-white px-8 py-3">
      <div className="flex max-w-3xl items-center justify-between gap-4">
        <div className="text-xs text-slate-500">
          {!template && (
            <>Upload a template and save a mapping profile under "1. Template &amp; Mapping".</>
          )}
          {template && !mappingProfileId && (
            <>
              Template <strong>{template.filename}</strong> uploaded — save a mapping profile
              first.
            </>
          )}
          {template && mappingProfileId && (
            <>
              Template <strong>{template.filename}</strong> &middot; mapping profile ready.
            </>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <label className="flex items-center gap-1 text-xs text-slate-500">
            <input
              type="checkbox"
              checked={recalc}
              onChange={(e) => setRecalc(e.target.checked)}
            />
            Recalculate on server
          </label>
          <button
            onClick={handleGenerate}
            disabled={!ready || generating}
            className="rounded bg-emerald-600 px-4 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
          >
            {generating ? 'Generating…' : 'Generate & Download'}
          </button>
        </div>
      </div>
      {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
      {result && (
        <div className="mt-2 text-xs text-slate-500">
          Wrote {result.writtenCount} field(s).
          {result.warnings.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-amber-600">
              {result.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
