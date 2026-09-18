import { useMemo, useRef, useState } from 'react'
import { useModalFocus } from '../lib/useModalFocus'
import ExtractionReview from './ExtractionReview'
import {
  createDeal,
  createDealFromExtraction,
  deleteDeal,
  fetchDocuments,
  getExtraction,
  runExtraction,
  updateDeal,
  updateDocumentType,
  uploadDocument,
} from '../lib/api'
import type { Deal } from '../types/deal'
import type { DocumentSummary, DocumentType } from '../types/document'
import type { ExtractionResult } from '../types/extraction'
import type { InputSchema } from '../types/schema'
import FileChooser from './FileChooser'

interface OmWizardProps {
  schema: InputSchema
  deals: Deal[]
  onClose: () => void
  /** Called with the finalized deal; the caller switches to it. */
  onCreated: (deal: Deal) => void
  /** Refresh the deal list (draft created/deleted mid-flow). */
  onDealsChanged: () => void
}

interface WizardState {
  step: number
  documentIds: string[]
  extractionResultId?: string
}

const DOC_TYPES: DocumentType[] = [
  'offering_memorandum',
  'rent_roll',
  't12_operating_statement',
  'other',
]

/** J10: OM-to-deal wizard — chains upload → type confirmation → extraction
 *  → the EXISTING review gate → deal creation with provenance. Nothing
 *  auto-applies; every step is a user confirmation. State lives on a draft
 *  deal (inputs._omWizard) so an abandoned flow is resumable or deletable. */
export default function OmWizard({ schema, deals, onClose, onCreated, onDealsChanged }: OmWizardProps) {
  const drafts = useMemo(
    () => deals.filter((d) => Boolean((d.inputs as Record<string, unknown>)?._omWizard)),
    [deals],
  )
  const [draft, setDraft] = useState<Deal | null>(null)
  const [docs, setDocs] = useState<DocumentSummary[]>([])
  const [confirmedDocs, setConfirmedDocs] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<ExtractionResult | null>(null)
  const [confirmedValues, setConfirmedValues] = useState<Record<string, unknown> | null>(null)
  const [dealName, setDealName] = useState('')
  // Dealflow choice at the create step. OMs are overwhelmingly for existing
  // assets, so acquisition is the seed — but development budget fields in
  // the reviewed values flip the suggestion.
  const [dealType, setDealType] = useState<'acquisition' | 'development'>('acquisition')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const wizardState: WizardState = draft
    ? ((draft.inputs as Record<string, unknown>)._omWizard as unknown as WizardState) ?? {
        step: 1,
        documentIds: [],
      }
    : { step: 0, documentIds: [] }
  const step = draft === null ? 0 : confirmedValues !== null ? 4 : result !== null ? 3 : wizardState.step

  async function persistState(next: WizardState) {
    if (!draft) return
    const inputs = { ...(draft.inputs as Record<string, unknown>), _omWizard: next }
    const updated = await updateDeal(draft.id, { inputs })
    setDraft(updated)
  }

  async function startFresh() {
    setBusy(true)
    setError(null)
    try {
      const deal = await createDeal({
        name: 'Draft — from documents',
        inputs: { _omWizard: { step: 1, documentIds: [] } },
      })
      setDraft(deal)
      onDealsChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the draft.')
    } finally {
      setBusy(false)
    }
  }

  async function resumeDraft(d: Deal) {
    setBusy(true)
    setError(null)
    try {
      setDraft(d)
      const state = (d.inputs as Record<string, unknown>)._omWizard as unknown as WizardState
      if (state?.documentIds?.length) {
        const all = await fetchDocuments()
        setDocs(all.filter((doc) => state.documentIds.includes(doc.id)))
        // Type confirmations are deliberately NOT restored — the gate is
        // re-walked on resume (confirming is one click per document).
      }
      if (state?.extractionResultId) {
        setResult(await getExtraction(state.extractionResultId))
      }
    } catch {
      setError('Could not restore the saved extraction — re-run it below.')
    } finally {
      setBusy(false)
    }
  }

  async function discardDraft(d: Deal) {
    await deleteDeal(d.id)
    if (draft?.id === d.id) setDraft(null)
    onDealsChanged()
  }

  async function handleUpload(files: File[]) {
    if (files.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const uploaded: DocumentSummary[] = []
      for (const file of files) {
        uploaded.push(await uploadDocument(file))
      }
      const next = [...docs, ...uploaded.filter((u) => !docs.some((d) => d.id === u.id))]
      setDocs(next)
      await persistState({ ...wizardState, documentIds: next.map((d) => d.id) })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  async function confirmType(doc: DocumentSummary, type: DocumentType) {
    const updated = await updateDocumentType(doc.id, type)
    setDocs(docs.map((d) => (d.id === doc.id ? updated : d)))
    setConfirmedDocs(new Set([...confirmedDocs, doc.id]))
  }

  async function handleExtract() {
    setBusy(true)
    setError(null)
    try {
      const extraction = await runExtraction(docs.map((d) => d.id))
      setResult(extraction)
      await persistState({
        ...wizardState,
        step: 3,
        documentIds: docs.map((d) => d.id),
        extractionResultId: extraction.id,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Extraction failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handleCreate() {
    if (!result || !confirmedValues || !draft) return
    setBusy(true)
    setError(null)
    try {
      const hasFailures = (result.crossValidation ?? []).some((c) => c.status === 'fail')
      const deal = await createDealFromExtraction({
        name: dealName.trim() || 'Deal from documents',
        extractionResultId: result.id,
        // The user's dealflow choice rides with the reviewed values so the
        // deal lands on the right pipeline board.
        confirmedValues: { ...confirmedValues, dealType },
        // The review gate already required per-failure acknowledgment
        // checkboxes before onApply could fire.
        acknowledgeFailures: hasFailures,
        dealId: draft.id,
      })
      onDealsChanged()
      onCreated(deal)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Deal creation failed.')
    } finally {
      setBusy(false)
    }
  }

  const allConfirmed = docs.length > 0 && docs.every((d) => confirmedDocs.has(d.id))

  // Mid-way, a stray backdrop click or Escape shouldn't silently discard the
  // wizard's progress.
  function requestClose() {
    if (step > 0 && !window.confirm('Close the wizard? Uploaded documents stay under Documents, but the progress here is lost.')) return
    onClose()
  }
  const dialogRef = useRef<HTMLDivElement>(null)
  useModalFocus(dialogRef, () => requestCloseRef.current())
  const requestCloseRef = useRef(requestClose)
  requestCloseRef.current = requestClose

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-6" onClick={requestClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="New deal from documents"
        className="w-full max-w-4xl rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">
            New deal from documents{' '}
            <span className="ml-2 text-xs font-normal text-slate-400">
              {['start', 'upload & confirm types', 'extract', 'review', 'create'][step]}
            </span>
          </h2>
          <button onClick={requestClose} aria-label="Close" className="text-slate-400 hover:text-slate-600">✕</button>
        </div>
        {error && <div className="mb-2 text-xs text-red-600">{error}</div>}

        {step === 0 && (
          <div className="text-sm text-slate-600">
            {drafts.length > 0 && (
              <div className="mb-3">
                <div className="mb-1 text-xs font-medium text-slate-500">RESUME A DRAFT</div>
                {drafts.map((d) => (
                  <div key={d.id} className="flex items-center gap-2 py-1 text-xs">
                    <span>{d.name}</span>
                    <button onClick={() => void resumeDraft(d)} className="rounded border border-sky-500 px-2 py-0.5 text-sky-600 hover:bg-sky-50">
                      Resume
                    </button>
                    <button onClick={() => void discardDraft(d)} className="rounded border border-slate-300 px-2 py-0.5 text-slate-500 hover:bg-slate-50">
                      Delete draft
                    </button>
                  </div>
                ))}
              </div>
            )}
            <button
              onClick={() => void startFresh()}
              disabled={busy}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
            >
              Start a new draft
            </button>
            <p className="mt-2 text-xs text-slate-400">
              A draft deal holds the wizard state, so you can leave and resume; deleting the
              draft discards the flow.
            </p>
          </div>
        )}

        {step >= 1 && step < 3 && (
          <div>
            <FileChooser
              multiple
              description="Deal documents"
              label="Choose documents…"
              onFiles={(files) => void handleUpload(files)}
              className="text-xs"
            />
            {docs.length > 0 && (
              <table className="mt-3 w-full text-xs">
                <thead>
                  <tr className="text-left text-slate-400">
                    <th className="pr-3 font-medium">File</th>
                    <th className="pr-3 font-medium">Proposed type</th>
                    <th className="pr-3 font-medium">Confidence</th>
                    <th className="pr-3 font-medium">Confirm</th>
                  </tr>
                </thead>
                <tbody className="text-slate-600">
                  {docs.map((doc) => (
                    <tr key={doc.id}>
                      <td className="pr-3">{doc.filename}</td>
                      <td className="pr-3">
                        <select
                          value={doc.documentType}
                          onChange={(e) => void confirmType(doc, e.target.value as DocumentType)}
                          className="rounded border border-slate-300 px-1 py-0.5"
                        >
                          {DOC_TYPES.map((t) => (
                            <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
                          ))}
                        </select>
                      </td>
                      <td className="pr-3">{Math.round((doc.typeConfidence ?? 0) * 100)}%</td>
                      <td className="pr-3">
                        {confirmedDocs.has(doc.id) ? (
                          <span className="text-emerald-600">confirmed</span>
                        ) : (
                          <button
                            onClick={() => void confirmType(doc, doc.documentType)}
                            className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50"
                          >
                            Looks right
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <button
              onClick={() => void handleExtract()}
              disabled={busy || !allConfirmed}
              title={allConfirmed ? undefined : 'Confirm each document type first.'}
              className="mt-3 rounded bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-700 disabled:opacity-40"
            >
              {busy ? 'Working…' : 'Run extraction'}
            </button>
          </div>
        )}

        {step === 3 && result && (
          <ExtractionReview
            schema={schema}
            result={result}
            onApply={(values) => {
              setConfirmedValues(values)
              // Suggest a dealflow from what was actually extracted: budget
              // fields mean ground-up; otherwise an OM is an existing asset.
              const looksLikeDevelopment =
                values.dealType === 'development' ||
                Number(values.landCost) > 0 ||
                Number(values.hardCosts) > 0
              setDealType(looksLikeDevelopment ? 'development' : 'acquisition')
            }}
          />
        )}

        {step === 4 && confirmedValues && (
          <div className="text-sm text-slate-600">
            <p className="text-xs text-slate-500">
              {Object.keys(confirmedValues).length} reviewed value(s) will populate the new
              deal, each with a provenance row linking it to its source document.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input
                value={dealName}
                onChange={(e) => setDealName(e.target.value)}
                placeholder="Deal name"
                className="w-64 rounded border border-slate-300 px-2 py-1 text-sm"
              />
              <label className="flex items-center gap-1 text-xs text-slate-500">
                Dealflow
                <select
                  value={dealType}
                  onChange={(e) => setDealType(e.target.value as 'acquisition' | 'development')}
                  className="rounded border border-slate-300 px-2 py-1 text-sm"
                >
                  <option value="acquisition">Acquisition</option>
                  <option value="development">Development</option>
                </select>
              </label>
              <button
                onClick={() => void handleCreate()}
                disabled={busy || !dealName.trim()}
                className="rounded bg-emerald-600 px-3 py-1.5 text-white hover:bg-emerald-700 disabled:opacity-40"
              >
                {busy ? 'Creating…' : 'Create deal'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
