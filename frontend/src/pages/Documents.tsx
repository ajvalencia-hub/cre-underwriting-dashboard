import { useEffect, useRef, useState } from 'react'
import ExtractionReview from '../components/ExtractionReview'
import { deleteDocument, fetchDocuments, runExtraction, updateDocumentType, uploadDocument } from '../lib/api'
import type { QuickScreenInputs } from '../lib/quickScreenMath'
import { DOCUMENT_TYPE_LABELS, type DocumentSummary, type DocumentType } from '../types/document'
import type { ExtractionResult } from '../types/extraction'
import type { InputSchema } from '../types/schema'

interface DocumentsProps {
  schema: InputSchema
  dealId: string | null
  /** The active deal's current unitMix rows — drives the replace/merge choice. */
  currentUnitMix?: unknown
  currentCommercialLeases?: unknown
  onApplyExtraction: (confirmedValues: Record<string, unknown>) => void
  onSeedQuickScreen?: (values: Partial<QuickScreenInputs>) => void
}

const DOCUMENT_TYPES: DocumentType[] = [
  'offering_memorandum',
  'rent_roll',
  't12_operating_statement',
  'other',
]

const LOW_CONFIDENCE_THRESHOLD = 0.6

function confidenceBadge(confidence: number): string {
  if (confidence >= LOW_CONFIDENCE_THRESHOLD) return 'bg-emerald-100 text-emerald-700'
  if (confidence > 0) return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-500'
}

export default function Documents({
  schema,
  dealId,
  currentUnitMix,
  currentCommercialLeases,
  onApplyExtraction,
  onSeedQuickScreen,
}: DocumentsProps) {
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [uploading, setUploading] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [extractionResult, setExtractionResult] = useState<ExtractionResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setSelected(new Set())
    setExtractionResult(null)
    if (dealId) refresh()
    else setDocuments([])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId])

  function refresh() {
    if (!dealId) return
    fetchDocuments(dealId)
      .then(setDocuments)
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load documents'))
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files || files.length === 0 || !dealId) return
    setUploading(true)
    setError(null)
    try {
      for (const file of Array.from(files)) {
        const doc = await uploadDocument(file, dealId)
        setDocuments((prev) => [doc, ...prev.filter((d) => d.id !== doc.id)])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function handleTypeOverride(id: string, documentType: DocumentType) {
    try {
      const updated = await updateDocumentType(id, documentType)
      setDocuments((prev) => prev.map((d) => (d.id === id ? updated : d)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update document type')
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteDocument(id)
      setDocuments((prev) => prev.filter((d) => d.id !== id))
      setSelected((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete document')
    }
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleRunExtraction() {
    setExtracting(true)
    setError(null)
    setExtractionResult(null)
    try {
      const result = await runExtraction(Array.from(selected))
      setExtractionResult(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Extraction failed')
    } finally {
      setExtracting(false)
    }
  }

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold">Documents</h1>
      <p className="mt-1 text-slate-500">
        Upload Offering Memoranda, rent rolls, or T-12 operating statements for THIS deal — documents are
        scoped per deal, so other deals never see them. The app classifies each document automatically —
        confirm or override the type, select documents, then run extraction to pre-fill deal inputs for
        review. Nothing is applied without your confirmation.
      </p>

      {!dealId && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
          Select or create a deal first — documents are tied to a specific deal.
        </div>
      )}

      <div className="mt-6 rounded-md border border-dashed border-slate-300 bg-white p-6 text-center">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.xlsx,.xls,.csv"
          multiple
          onChange={handleFileChange}
          disabled={uploading || !dealId}
          className="text-sm"
        />
        {uploading && <div className="mt-3 text-sm text-slate-500">Uploading &amp; classifying…</div>}
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <section className="mt-8">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-wide text-slate-500">
            UPLOADED DOCUMENTS ({documents.length})
          </h2>
          <button
            onClick={handleRunExtraction}
            disabled={selected.size === 0 || extracting}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:opacity-40"
          >
            {extracting ? 'Extracting…' : `Run Extraction (${selected.size} selected)`}
          </button>
        </div>
        {documents.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">No documents uploaded yet.</p>
        ) : (
          <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200 bg-white">
            {documents.map((doc) => (
              <li key={doc.id} className="flex items-start justify-between gap-4 px-3 py-3 text-sm">
                <div className="flex min-w-0 flex-1 items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={selected.has(doc.id)}
                    onChange={() => toggleSelected(doc.id)}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">{doc.filename}</span>
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${confidenceBadge(doc.typeConfidence)}`}>
                        {doc.typeSource} · {(doc.typeConfidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-slate-400">{doc.typeRationale}</div>
                    <div className="mt-1 text-xs text-slate-400">
                      Uploaded {new Date(doc.createdAt).toLocaleString()}
                    </div>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <select
                    value={doc.documentType}
                    onChange={(e) => handleTypeOverride(doc.id, e.target.value as DocumentType)}
                    className="rounded border border-slate-300 px-2 py-1 text-xs"
                  >
                    {DOCUMENT_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {DOCUMENT_TYPE_LABELS[t]}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => handleDelete(doc.id)}
                    className="rounded border border-slate-300 px-2 py-0.5 text-xs text-red-500 hover:bg-red-50"
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {extractionResult && (
        <ExtractionReview
          schema={schema}
          result={extractionResult}
          currentUnitMix={currentUnitMix}
          currentCommercialLeases={currentCommercialLeases}
          onApply={onApplyExtraction}
          onSeedQuickScreen={onSeedQuickScreen}
        />
      )}
    </div>
  )
}
