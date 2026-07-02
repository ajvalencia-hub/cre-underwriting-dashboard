import { useEffect, useRef, useState } from 'react'
import {
  deleteMappingProfile,
  deleteTemplate,
  fetchAutoMatch,
  fetchInputSchema,
  fetchMappingProfiles,
  fetchSheetGrid,
  fetchTemplates,
  saveMappingProfile,
  updateMappingProfile,
  uploadTemplate,
} from '../lib/api'
import { describeMapping } from '../lib/mappingFormat'
import { flattenFields, type FlatField } from '../lib/schemaFields'
import type { MappingEntry, MappingProfile, MappingsById } from '../types/mapping'
import type { SheetGrid, TemplateSummary } from '../types/template'

interface TemplateUploadProps {
  onTemplateReady?: (template: TemplateSummary | null, mappingProfileId: string | null) => void
}

const OUTPUTS_SECTION_ID = 'computed_outputs'

export default function TemplateUpload({ onTemplateReady }: TemplateUploadProps) {
  const [template, setTemplate] = useState<TemplateSummary | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [recentTemplates, setRecentTemplates] = useState<TemplateSummary[]>([])

  const [selectedSheet, setSelectedSheet] = useState<string>('')
  const [grid, setGrid] = useState<SheetGrid | null>(null)
  const [gridLoading, setGridLoading] = useState(false)

  const [fields, setFields] = useState<FlatField[]>([])
  const [mappings, setMappings] = useState<MappingsById>({})
  const [formulaWarnings, setFormulaWarnings] = useState<Set<string>>(new Set())
  const [pickingFieldId, setPickingFieldId] = useState<string | null>(null)

  const [profiles, setProfiles] = useState<MappingProfile[]>([])
  const [profileId, setProfileId] = useState<string | null>(null)
  const [profileName, setProfileName] = useState('My Mapping Profile')
  const [profileLoadedNote, setProfileLoadedNote] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fetchInputSchema()
      .then((schema) => {
        const outputFields: FlatField[] = schema.outputs.map((o) => ({
          id: o.id,
          label: o.label,
          type: o.type === 'percent' ? 'percent' : o.type === 'currency' ? 'currency' : 'number',
          sectionId: OUTPUTS_SECTION_ID,
          sectionLabel: 'Computed Outputs (mapped after recalculation)',
        }))
        setFields([...flattenFields(schema), ...outputFields])
      })
      .catch(() => setFields([]))
    refreshRecentTemplates()
  }, [])

  useEffect(() => {
    onTemplateReady?.(template, profileId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template, profileId])

  function refreshRecentTemplates() {
    fetchTemplates()
      .then(setRecentTemplates)
      .catch(() => setRecentTemplates([]))
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const summary = await uploadTemplate(file)
      await loadTemplate(summary)
      refreshRecentTemplates()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function loadTemplate(summary: TemplateSummary) {
    setTemplate(summary)
    setGrid(null)
    setMappings({})
    setFormulaWarnings(new Set())
    setProfileId(null)
    setProfileLoadedNote(null)
    setSelectedSheet(summary.sheets[0]?.name ?? '')
    await seedMappings(summary)
  }

  async function seedMappings(summary: TemplateSummary) {
    try {
      const existing = await fetchMappingProfiles(summary.id)
      setProfiles(existing)
      if (existing.length > 0) {
        const latest = existing[0]
        applyProfile(latest)
        setProfileLoadedNote(`Loaded saved mapping profile "${latest.profileName}".`)
        return
      }
    } catch {
      setProfiles([])
    }
    try {
      const autoMatch = await fetchAutoMatch(summary.id)
      setMappings(autoMatch.mappings)
      if (Object.keys(autoMatch.mappings).length > 0) {
        setProfileLoadedNote(
          `Auto-matched ${Object.keys(autoMatch.mappings).length} field(s) from named ranges and cell labels — review below.`,
        )
      }
    } catch {
      // no named ranges / auto-match failed silently, user maps manually
    }
  }

  function applyProfile(profile: MappingProfile) {
    setMappings(profile.mappings)
    setProfileId(profile.id)
    setProfileName(profile.profileName)
    setFormulaWarnings(new Set())
  }

  async function handleDeleteTemplate(id: string) {
    try {
      await deleteTemplate(id)
      if (template?.id === id) {
        setTemplate(null)
        setMappings({})
        setProfiles([])
        setProfileId(null)
      }
      refreshRecentTemplates()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete template')
    }
  }

  async function handleDeleteProfile(id: string) {
    try {
      await deleteMappingProfile(id)
      setProfiles((prev) => prev.filter((p) => p.id !== id))
      if (profileId === id) {
        setProfileId(null)
        setMappings({})
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete mapping profile')
    }
  }

  async function handlePreviewGrid(sheetName = selectedSheet) {
    if (!template || !sheetName) return
    setGridLoading(true)
    setError(null)
    try {
      const g = await fetchSheetGrid(template.id, sheetName)
      setGrid(g)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load sheet preview')
    } finally {
      setGridLoading(false)
    }
  }

  function handleStartPicking(fieldId: string) {
    setPickingFieldId(fieldId)
    if (!grid) handlePreviewGrid()
  }

  function handleCellPick(cellRef: string, isFormula: boolean) {
    if (!pickingFieldId || !grid) return
    const field = fields.find((f) => f.id === pickingFieldId)
    if (!field) return

    const entry: MappingEntry =
      field.type === 'table' || field.type === 'keyvalue'
        ? {
            target: 'table',
            anchor: cellRef,
            sheet: grid.sheet,
            columnOrder: field.columns?.map((c) => c.id) ?? null,
            source: 'manual',
          }
        : {
            target: 'cell',
            ref: `${grid.sheet}!${cellRef}`,
            sheet: grid.sheet,
            source: 'manual',
          }

    setMappings((prev) => ({ ...prev, [pickingFieldId]: entry }))
    setFormulaWarnings((prev) => {
      const next = new Set(prev)
      if (isFormula) next.add(pickingFieldId)
      else next.delete(pickingFieldId)
      return next
    })
    setPickingFieldId(null)
  }

  function handleClearMapping(fieldId: string) {
    setMappings((prev) => {
      const next = { ...prev }
      delete next[fieldId]
      return next
    })
    setFormulaWarnings((prev) => {
      const next = new Set(prev)
      next.delete(fieldId)
      return next
    })
  }

  async function handleSaveProfile() {
    if (!template) return
    setSaving(true)
    setError(null)
    try {
      const result = profileId
        ? await updateMappingProfile(profileId, { templateId: template.id, profileName, mappings })
        : await saveMappingProfile({ templateId: template.id, profileName, mappings })
      setProfileId(result.id)
      setProfiles((prev) => [result, ...prev.filter((p) => p.id !== result.id)])
      setProfileLoadedNote(
        result.unmappedRequiredFields.length > 0
          ? `Saved. ${result.unmappedRequiredFields.length} required field(s) still unmapped.`
          : 'Saved. All required fields are mapped.',
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save mapping profile')
    } finally {
      setSaving(false)
    }
  }

  const sections = Array.from(new Map(fields.map((f) => [f.sectionId, f.sectionLabel])).entries())
  const mappedCount = Object.keys(mappings).length

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold">Template &amp; Mapping Setup</h1>
      <p className="mt-1 text-slate-500">
        Upload your Excel underwriting model (.xlsx / .xlsm). We'll read its sheets, cells, and
        named ranges so you can map dashboard inputs to it — a one-time setup per template.
      </p>

      {recentTemplates.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold tracking-wide text-slate-500">
            RECENT TEMPLATES ({recentTemplates.length})
          </h2>
          <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200 bg-white">
            {recentTemplates.map((t) => (
              <li key={t.id} className="flex items-center justify-between px-3 py-2 text-sm">
                <div>
                  <span className="font-medium">{t.filename}</span>
                  <span className="ml-2 text-xs text-slate-400">
                    {t.sheets.length} sheet(s) &middot; {new Date(t.createdAt).toLocaleString()}
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => loadTemplate(t)}
                    className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                  >
                    Use
                  </button>
                  <button
                    onClick={() => handleDeleteTemplate(t.id)}
                    className="rounded border border-slate-300 px-2 py-0.5 text-xs text-red-500 hover:bg-red-50"
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-6 rounded-md border border-dashed border-slate-300 bg-white p-6 text-center">
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xlsm"
          onChange={handleFileChange}
          disabled={uploading}
          className="text-sm"
        />
        {uploading && <div className="mt-3 text-sm text-slate-500">Uploading &amp; parsing…</div>}
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {template && (
        <div className="mt-8 space-y-8">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium">{template.filename}</div>
              <div className="text-xs text-slate-400">
                hash {template.fileHash.slice(0, 12)}… &middot; uploaded{' '}
                {new Date(template.createdAt).toLocaleString()}
              </div>
            </div>
            {template.reused && (
              <span className="rounded-full bg-sky-100 px-3 py-1 text-xs font-medium text-sky-700">
                Known template — reused existing record
              </span>
            )}
          </div>

          <section>
            <h2 className="text-sm font-semibold tracking-wide text-slate-500">
              SHEETS ({template.sheets.length})
            </h2>
            <table className="mt-2 w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="py-1.5 font-medium">Sheet</th>
                  <th className="py-1.5 font-medium">Rows</th>
                  <th className="py-1.5 font-medium">Cols</th>
                </tr>
              </thead>
              <tbody>
                {template.sheets.map((s) => (
                  <tr key={s.name} className="border-b border-slate-100">
                    <td className="py-1.5">{s.name}</td>
                    <td className="py-1.5 text-slate-500">{s.maxRow}</td>
                    <td className="py-1.5 text-slate-500">{s.maxCol}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2 className="text-sm font-semibold tracking-wide text-slate-500">
              NAMED RANGES ({template.namedRanges.length})
            </h2>
            {template.namedRanges.length === 0 ? (
              <p className="mt-2 text-sm text-slate-400">
                None found. You'll map every field manually using the cell picker below.
              </p>
            ) : (
              <table className="mt-2 w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="py-1.5 font-medium">Name</th>
                    <th className="py-1.5 font-medium">Sheet</th>
                    <th className="py-1.5 font-medium">Ref</th>
                  </tr>
                </thead>
                <tbody>
                  {template.namedRanges.map((nr, i) => (
                    <tr key={`${nr.name}-${i}`} className="border-b border-slate-100">
                      <td className="py-1.5 font-mono text-xs">{nr.name}</td>
                      <td className="py-1.5 text-slate-500">{nr.sheet}</td>
                      <td className="py-1.5 font-mono text-xs text-slate-500">{nr.ref}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h2 className="text-sm font-semibold tracking-wide text-slate-500">SHEET PREVIEW</h2>
            <div className="mt-2 flex items-center gap-2">
              <select
                value={selectedSheet}
                onChange={(e) => {
                  setSelectedSheet(e.target.value)
                  setGrid(null)
                }}
                className="rounded border border-slate-300 px-2 py-1 text-sm"
              >
                {template.sheets.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
              <button
                onClick={() => handlePreviewGrid()}
                disabled={gridLoading}
                className="rounded bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-700 disabled:opacity-50"
              >
                {gridLoading ? 'Loading…' : 'Preview Grid'}
              </button>
            </div>

            {pickingFieldId && (
              <div className="mt-3 rounded-md border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm text-indigo-700">
                Click a cell below to map{' '}
                <strong>{fields.find((f) => f.id === pickingFieldId)?.label}</strong>.{' '}
                <button className="underline" onClick={() => setPickingFieldId(null)}>
                  Cancel
                </button>
              </div>
            )}

            {grid && (
              <div className="mt-3 max-h-96 overflow-auto rounded border border-slate-200">
                <table className="border-collapse text-xs">
                  <thead className="sticky top-0 bg-slate-100">
                    <tr>
                      <th className="border border-slate-200 px-2 py-1"></th>
                      {grid.columns.map((c) => (
                        <th key={c} className="border border-slate-200 px-2 py-1 font-medium">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {grid.rows.map((row, rIdx) => (
                      <tr key={rIdx}>
                        <td className="border border-slate-200 bg-slate-50 px-2 py-1 font-medium text-slate-400">
                          {rIdx + 1}
                        </td>
                        {row.map((cell) => (
                          <td
                            key={cell.ref}
                            title={cell.ref}
                            onClick={() => pickingFieldId && handleCellPick(cell.ref, cell.isFormula)}
                            className={`border border-slate-200 px-2 py-1 whitespace-nowrap ${
                              cell.isFormula ? 'bg-amber-50 text-amber-700' : ''
                            } ${pickingFieldId ? 'cursor-pointer hover:bg-indigo-100' : ''}`}
                          >
                            {cell.value === null ? '' : String(cell.value)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="border-t border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-400">
                  Showing {grid.rows.length} of {grid.totalRows} rows &middot; formula cells
                  highlighted &middot; click a cell while mapping a field
                </div>
              </div>
            )}
          </section>

          <section>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold tracking-wide text-slate-500">
                FIELD MAPPING ({mappedCount} mapped)
              </h2>
            </div>

            {profileLoadedNote && (
              <div className="mt-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                {profileLoadedNote}
              </div>
            )}

            <div className="mt-3 space-y-2">
              {sections.map(([sectionId, sectionLabel]) => (
                <details key={sectionId} className="rounded border border-slate-200 bg-white">
                  <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-slate-700">
                    {sectionLabel}
                  </summary>
                  <table className="w-full border-t border-slate-100 text-sm">
                    <tbody>
                      {fields
                        .filter((f) => f.sectionId === sectionId)
                        .map((field) => {
                          const entry = mappings[field.id]
                          return (
                            <tr key={field.id} className="border-b border-slate-50">
                              <td className="w-1/3 py-1.5 pl-3">
                                {field.label}
                                {field.required && <span className="ml-1 text-red-400">*</span>}
                                <div className="font-mono text-[11px] text-slate-400">{field.id}</div>
                              </td>
                              <td className="py-1.5 text-slate-600">
                                {describeMapping(entry)}
                                {entry?.source === 'auto' && (
                                  <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                                    auto
                                  </span>
                                )}
                                {formulaWarnings.has(field.id) && (
                                  <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">
                                    ⚠ mapped cell has a formula
                                  </span>
                                )}
                              </td>
                              <td className="w-40 py-1.5 pr-3 text-right">
                                <button
                                  onClick={() => handleStartPicking(field.id)}
                                  className="mr-2 rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                                >
                                  Pick cell
                                </button>
                                {entry && (
                                  <button
                                    onClick={() => handleClearMapping(field.id)}
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
                  </table>
                </details>
              ))}
            </div>

            <div className="mt-4 flex items-center gap-2">
              <input
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="Profile name"
              />
              <button
                onClick={handleSaveProfile}
                disabled={saving || !profileName.trim()}
                className="rounded bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {saving ? 'Saving…' : profileId ? 'Update Mapping Profile' : 'Save Mapping Profile'}
              </button>
            </div>
          </section>

          {profiles.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold tracking-wide text-slate-500">
                MAPPING PROFILES FOR THIS TEMPLATE ({profiles.length})
              </h2>
              <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200 bg-white">
                {profiles.map((p) => (
                  <li key={p.id} className="flex items-center justify-between px-3 py-2 text-sm">
                    <div>
                      <span className={`font-medium ${p.id === profileId ? 'text-emerald-700' : ''}`}>
                        {p.profileName}
                      </span>
                      {p.id === profileId && (
                        <span className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] text-emerald-700">
                          active
                        </span>
                      )}
                      <span className="ml-2 text-xs text-slate-400">
                        {Object.keys(p.mappings).length} field(s) mapped &middot;{' '}
                        {new Date(p.updatedAt).toLocaleString()}
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => applyProfile(p)}
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                      >
                        Load
                      </button>
                      <button
                        onClick={() => handleDeleteProfile(p.id)}
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs text-red-500 hover:bg-red-50"
                      >
                        Delete
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
