import { useEffect, useMemo, useRef, useState } from 'react'
import {
  deleteMappingProfile,
  deleteTemplate,
  fetchAutoMatch,
  fetchInputSchema,
  fetchMappingProfiles,
  fetchTemplates,
  previewMapping,
  saveMappingProfile,
  updateMappingProfile,
  uploadTemplate,
} from '../lib/api'
import FileChooser from '../components/FileChooser'
import MappingCoverage from '../components/MappingCoverage'
import SheetPicker from '../components/SheetPicker'
import { withSharedTargets } from '../lib/mappingCoverage'
import { mappingsEqual } from '../lib/mappingFormat'
import { useHeaderOffset } from '../lib/useHeaderOffset'
import { flattenFields, visibleFields, type FlatField } from '../lib/schemaFields'
import type { MappingEntry, MappingProfile, MappingsById } from '../types/mapping'
import type { MappingPreviewRow } from '../types/mappingPreview'
import type { InputSchema } from '../types/schema'
import type { TemplateSummary } from '../types/template'

interface TemplateUploadProps {
  /** The active deal's inputs — shown next to each mapping and used to
   *  preview exactly what Generate would write. */
  values: Record<string, unknown>
  onTemplateReady?: (template: TemplateSummary | null, mappingProfileId: string | null) => void
  /** True while the mapping on screen differs from the saved profile that
   *  Generate / template sensitivity actually use. */
  onUnsavedChange?: (unsaved: boolean) => void
}

const OUTPUTS_SECTION_ID = 'computed_outputs'
const PREVIEW_DEBOUNCE_MS = 400

export default function TemplateUpload({ values, onTemplateReady, onUnsavedChange }: TemplateUploadProps) {
  const [template, setTemplate] = useState<TemplateSummary | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [recentTemplates, setRecentTemplates] = useState<TemplateSummary[]>([])

  const [schema, setSchema] = useState<InputSchema | null>(null)
  const [fields, setFields] = useState<FlatField[]>([])
  const [mappings, setMappings] = useState<MappingsById>({})
  // What the active saved profile contains — the mapping Generate will use.
  const [savedMappings, setSavedMappings] = useState<MappingsById | null>(null)
  const [pickingFieldId, setPickingFieldId] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [focusRef, setFocusRef] = useState<string | null>(null)

  const [preview, setPreview] = useState<MappingPreviewRow[] | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const previewRequest = useRef(0)

  const [profiles, setProfiles] = useState<MappingProfile[]>([])
  const [profileId, setProfileId] = useState<string | null>(null)
  const [profileName, setProfileName] = useState('My Mapping Profile')
  const [profileLoadedNote, setProfileLoadedNote] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetchInputSchema()
      .then((schema) => {
        setSchema(schema)
        const outputFields: FlatField[] = schema.outputs.map((o) => ({
          id: o.id,
          label: o.label,
          type: o.type === 'percent' ? 'percent' : o.type === 'currency' ? 'currency' : 'number',
          sectionId: OUTPUTS_SECTION_ID,
          sectionLabel: 'Computed Outputs (read back after recalculation)',
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

  const unsaved = profileId !== null && savedMappings !== null && !mappingsEqual(mappings, savedMappings)
  useEffect(() => {
    onUnsavedChange?.(unsaved)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unsaved])

  // Re-check the mapping against the template whenever it or the deal changes.
  useEffect(() => {
    if (!template) {
      setPreview(null)
      return
    }
    const id = ++previewRequest.current
    setPreviewLoading(true)
    const handle = setTimeout(() => {
      previewMapping(template.id, mappings, values)
        .then((rows) => {
          if (id !== previewRequest.current) return
          setPreview(withSharedTargets(rows))
          setPreviewError(null)
        })
        .catch((err) => {
          if (id !== previewRequest.current) return
          setPreviewError(err instanceof Error ? err.message : 'Preview failed')
        })
        .finally(() => {
          if (id === previewRequest.current) setPreviewLoading(false)
        })
    }, PREVIEW_DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [template, mappings, values])

  const relevantIds = useMemo(
    () => new Set(schema ? visibleFields(schema, values).map((f) => f.id) : fields.map((f) => f.id)),
    [schema, values, fields],
  )
  const labelById = useMemo(() => new Map(fields.map((f) => [f.id, f.label])), [fields])
  const mappedCells = useMemo(() => {
    const cells = new Map<string, string>()
    for (const row of preview ?? []) {
      if (row.resolvedRef && row.fieldId in mappings) cells.set(row.resolvedRef, labelById.get(row.fieldId) ?? row.fieldId)
    }
    return cells
  }, [preview, mappings, labelById])

  function refreshRecentTemplates() {
    fetchTemplates()
      .then(setRecentTemplates)
      .catch(() => setRecentTemplates([]))
  }

  async function handleFile(file: File) {
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
    }
  }

  async function loadTemplate(summary: TemplateSummary) {
    setTemplate(summary)
    setMappings({})
    setSavedMappings(null)
    setPreview(null)
    setProfileId(null)
    setProfileLoadedNote(null)
    setPickingFieldId(null)
    setFocusRef(null)
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
          `Auto-matched ${Object.keys(autoMatch.mappings).length} field(s) from named ranges and cell labels — review each one below before saving.`,
        )
      }
    } catch {
      // no named ranges / auto-match failed, user maps manually
    }
  }

  function applyProfile(profile: MappingProfile) {
    setMappings(profile.mappings)
    setSavedMappings(profile.mappings)
    setProfileId(profile.id)
    setProfileName(profile.profileName)
  }

  async function handleDeleteTemplate(id: string) {
    try {
      await deleteTemplate(id)
      if (template?.id === id) {
        setTemplate(null)
        setMappings({})
        setSavedMappings(null)
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
        setSavedMappings(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete mapping profile')
    }
  }

  function handleStartPicking(fieldId: string) {
    setPickingFieldId(fieldId)
    setPickerOpen(true)
    const current = preview?.find((r) => r.fieldId === fieldId)?.resolvedRef
    if (current) setFocusRef(current)
  }

  function handleCellPick(sheet: string, cellRef: string) {
    if (!pickingFieldId) return
    const field = fields.find((f) => f.id === pickingFieldId)
    if (!field) return

    const entry: MappingEntry =
      field.type === 'table' || field.type === 'keyvalue'
        ? {
            target: 'table',
            anchor: cellRef,
            sheet,
            columnOrder: field.columns?.map((c) => c.id) ?? null,
            source: 'manual',
          }
        : {
            target: 'cell',
            ref: `${sheet}!${cellRef}`,
            sheet,
            source: 'manual',
          }

    setMappings((prev) => ({ ...prev, [pickingFieldId]: entry }))
    setPickingFieldId(null)
  }

  function handleClearMapping(fieldId: string) {
    setMappings((prev) => {
      const next = { ...prev }
      delete next[fieldId]
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
      setSavedMappings(result.mappings)
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

  const headerOffset = useHeaderOffset()
  const pickingLabel = pickingFieldId ? (labelById.get(pickingFieldId) ?? pickingFieldId) : null

  return (
    <div className={template ? 'max-w-6xl' : 'max-w-4xl'}>
      <h1 className="text-2xl font-semibold">Template &amp; Mapping Setup</h1>
      <p className="mt-1 text-slate-500">
        Open your Excel underwriting model (.xlsx / .xlsm). Map each dashboard input to the cell it belongs in —
        a one-time setup per template. Below you can check, for this deal, exactly what will be written where.
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
        <FileChooser
          accept=".xlsx,.xlsm"
          description="Excel workbooks"
          label="Open Excel template…"
          onFiles={(files) => void handleFile(files[0])}
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
        <div className="mt-8 space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium">{template.filename}</div>
              <div className="text-xs text-slate-400">
                hash {template.fileHash.slice(0, 12)}… &middot; uploaded{' '}
                {new Date(template.createdAt).toLocaleString()}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {template.reused && (
                <span className="rounded-full bg-sky-100 px-3 py-1 text-xs font-medium text-sky-700">
                  Known template — reused existing record
                </span>
              )}
              {!pickerOpen && (
                <button
                  onClick={() => setPickerOpen(true)}
                  className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
                >
                  Show sheet
                </button>
              )}
            </div>
          </div>

          <details className="rounded border border-slate-200 bg-white px-3 py-2 text-sm">
            <summary className="cursor-pointer select-none text-slate-600">
              Workbook details — {template.sheets.length} sheet(s), {template.namedRanges.length} named range(s)
            </summary>
            <div className="mt-2 grid gap-6 md:grid-cols-2">
              <table className="w-full text-sm">
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
              {template.namedRanges.length === 0 ? (
                <p className="text-sm text-slate-400">
                  No named ranges. Fields are auto-matched from cell labels, or mapped with Pick cell.
                </p>
              ) : (
                <table className="w-full text-sm">
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
            </div>
          </details>

          {pickerOpen && (
            // Sticky so the sheet stays in view while scrolling the field list.
            <div className="sticky z-20 -mx-2 bg-slate-50 px-2 pt-1 pb-2" style={{ top: headerOffset }}>
              <SheetPicker
                templateId={template.id}
                sheets={template.sheets}
                pickingLabel={pickingLabel}
                mappedCells={mappedCells}
                focusRef={focusRef}
                onPick={handleCellPick}
                onCancel={() => setPickingFieldId(null)}
                onClose={() => {
                  setPickerOpen(false)
                  setPickingFieldId(null)
                }}
              />
            </div>
          )}

          <section>
            <h2 className="text-sm font-semibold tracking-wide text-slate-500">MAPPING — WHAT GENERATE WILL DO FOR THIS DEAL</h2>
            {profileLoadedNote && (
              <div className="mt-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                {profileLoadedNote}
              </div>
            )}
            <div className="mt-3">
              <MappingCoverage
                fields={fields}
                relevantIds={relevantIds}
                mappings={mappings}
                preview={preview}
                previewError={previewError}
                previewLoading={previewLoading}
                values={values}
                pickingFieldId={pickingFieldId}
                onPick={handleStartPicking}
                onClear={handleClearMapping}
                onShowCell={(ref) => {
                  setPickerOpen(true)
                  setFocusRef(null)
                  // Re-trigger even when the same cell is requested twice.
                  setTimeout(() => setFocusRef(ref), 0)
                }}
              />
            </div>

            {unsaved && (
              <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                <strong>Unsaved mapping changes.</strong> Generate and template sensitivity still use
                the saved profile “{profileName}” until you click Update Mapping Profile.
              </div>
            )}

            <div className="mt-4 flex items-center gap-2">
              <label className="sr-only" htmlFor="profile-name">
                Profile name
              </label>
              <input
                id="profile-name"
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
