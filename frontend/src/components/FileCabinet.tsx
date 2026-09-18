import { useEffect, useState, type ReactNode } from 'react'
import {
  attachmentDownloadUrl,
  createNote,
  deleteNote,
  fetchAttachmentPreview,
  fetchAttachments,
  fetchNotes,
  updateNote,
  uploadAttachment,
  type DealAttachment,
  type DealNote,
} from '../lib/api'
import FileChooser from './FileChooser'
import ServerFileLink from './ServerFileLink'

const TYPE_ICONS: Record<string, string> = {
  pdf: '📄', xlsx: '📊', xls: '📊', csv: '📊',
  png: '🖼', jpg: '🖼', jpeg: '🖼', gif: '🖼', webp: '🖼',
  docx: '📝', doc: '📝', pptx: '📽',
}

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp'])

function fmtSize(bytes: number | null): string {
  if (bytes === null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** Markdown-lite: **bold**, *italic*, and line breaks — rendered without a
 *  markdown dependency (see DECISIONS.md). */
function renderNoteBody(body: string) {
  return body.split('\n').map((line, i) => {
    const parts: ReactNode[] = []
    let rest = line
    let key = 0
    while (rest.length > 0) {
      const bold = rest.match(/\*\*(.+?)\*\*/)
      const italic = rest.match(/(?<!\*)\*([^*]+)\*(?!\*)/)
      const first =
        bold && (!italic || bold.index! <= italic.index!) ? bold : italic
      if (!first) {
        parts.push(rest)
        break
      }
      if (first.index! > 0) parts.push(rest.slice(0, first.index))
      parts.push(
        first === bold ? (
          <strong key={key++}>{first[1]}</strong>
        ) : (
          <em key={key++}>{first[1]}</em>
        ),
      )
      rest = rest.slice(first.index! + first[0].length)
    }
    return (
      <p key={i} className="min-h-[1em]">
        {parts}
      </p>
    )
  })
}

interface FileCabinetProps {
  dealId: string | null
}

/** J12: per-deal attachments + notes timeline, alongside the history drawer. */
export default function FileCabinet({ dealId }: FileCabinetProps) {
  const [attachments, setAttachments] = useState<DealAttachment[]>([])
  const [notes, setNotes] = useState<DealNote[]>([])
  const [noteDraft, setNoteDraft] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState('')
  const [preview, setPreview] = useState<{ id: string; content: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setPreview(null)
    setError(null)
    if (!dealId) {
      setAttachments([])
      setNotes([])
      return
    }
    fetchAttachments(dealId).then(setAttachments).catch(() => setAttachments([]))
    fetchNotes(dealId).then(setNotes).catch(() => setNotes([]))
  }, [dealId])

  if (!dealId) return null

  async function handleUpload(files: File[]) {
    if (files.length === 0 || !dealId) return
    setBusy(true)
    setError(null)
    try {
      for (const file of files) {
        const uploaded = await uploadAttachment(dealId, file)
        setAttachments((prev) => [uploaded, ...prev])
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handlePreview(att: DealAttachment) {
    if (preview?.id === att.id) {
      setPreview(null)
      return
    }
    if (IMAGE_EXTS.has(att.fileExt)) {
      setPreview({ id: att.id, content: '__image__' })
      return
    }
    const result = await fetchAttachmentPreview(dealId!, att.id)
    setPreview({
      id: att.id,
      content: result.kind === 'text' ? result.text || '(empty first page)' : result.note || '',
    })
  }

  async function addNote() {
    if (!noteDraft.trim() || !dealId) return
    const note = await createNote(dealId, noteDraft)
    setNotes((prev) => [note, ...prev])
    setNoteDraft('')
  }

  async function saveEdit(noteId: string) {
    if (!dealId) return
    const updated = await updateNote(dealId, noteId, editDraft)
    setNotes((prev) => prev.map((n) => (n.id === noteId ? updated : n)))
    setEditingId(null)
  }

  return (
    <details className="mb-4 rounded border border-slate-200 bg-white">
      <summary className="cursor-pointer select-none px-3 py-2 text-sm font-semibold text-slate-700">
        Files &amp; Notes
        <span className="ml-2 text-xs font-normal text-slate-400">
          {attachments.length} file(s) · {notes.length} note(s)
        </span>
      </summary>
      <div className="grid gap-4 px-3 pb-3 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-medium text-slate-500">ATTACHMENTS</div>
          <FileChooser
            multiple
            description="Attachments"
            label="Attach files…"
            onFiles={(files) => void handleUpload(files)}
            className="text-xs"
            disabled={busy}
          />
          {error && <div className="mt-1 text-xs text-red-600">{error}</div>}
          <ul className="mt-2 space-y-1 text-xs">
            {attachments.map((att) => (
              <li key={att.id}>
                <div className="flex items-center gap-2">
                  <span>{TYPE_ICONS[att.fileExt] ?? '📎'}</span>
                  <span className="truncate text-slate-700">{att.filename}</span>
                  <span className="text-slate-400">{fmtSize(att.sizeBytes)}</span>
                  {att.source === 'extraction' && (
                    <span className="rounded bg-violet-100 px-1 text-[10px] text-violet-700" title="This deal's provenance names this document as an extraction source.">
                      extraction source
                    </span>
                  )}
                  {(IMAGE_EXTS.has(att.fileExt) || att.fileExt === 'pdf') && (
                    <button onClick={() => void handlePreview(att)} className="text-sky-600 hover:underline">
                      preview
                    </button>
                  )}
                  <ServerFileLink
                    href={attachmentDownloadUrl(dealId, att.id)}
                    filename={att.filename}
                    className="text-sky-600 hover:underline"
                    download={att.filename}
                  >
                    download
                  </ServerFileLink>
                </div>
                {preview?.id === att.id && (
                  <div className="mt-1 rounded border border-slate-200 bg-slate-50 p-2">
                    {preview.content === '__image__' ? (
                      <img
                        src={attachmentDownloadUrl(dealId, att.id, true)}
                        alt={att.filename}
                        className="max-h-48 max-w-full"
                      />
                    ) : (
                      <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap text-[11px] text-slate-600">
                        {preview.content}
                      </pre>
                    )}
                  </div>
                )}
              </li>
            ))}
            {attachments.length === 0 && <li className="text-slate-400">No files yet.</li>}
          </ul>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium text-slate-500">NOTES</div>
          <div className="flex gap-2">
            <textarea
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              placeholder="Add a note… (**bold**, *italic*)"
              rows={2}
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
            />
            <button
              onClick={() => void addNote()}
              disabled={!noteDraft.trim()}
              className="self-start rounded bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700 disabled:opacity-40"
            >
              Add
            </button>
          </div>
          <ul className="mt-2 space-y-2 text-xs">
            {notes.map((note) => (
              <li key={note.id} className="rounded border border-slate-100 bg-slate-50 p-2">
                <div className="mb-1 flex items-center gap-2 text-[10px] text-slate-400">
                  {new Date(note.createdAt).toLocaleString()}
                  {note.updatedAt !== note.createdAt && ' (edited)'}
                  <button
                    onClick={() => {
                      setEditingId(note.id)
                      setEditDraft(note.body)
                    }}
                    className="ml-auto text-sky-600 hover:underline"
                  >
                    edit
                  </button>
                  <button
                    onClick={() =>
                      void deleteNote(dealId, note.id).then(() =>
                        setNotes((prev) => prev.filter((n) => n.id !== note.id)),
                      )
                    }
                    className="text-red-500 hover:underline"
                  >
                    delete
                  </button>
                </div>
                {editingId === note.id ? (
                  <div>
                    <textarea
                      value={editDraft}
                      onChange={(e) => setEditDraft(e.target.value)}
                      rows={2}
                      className="w-full rounded border border-slate-300 px-2 py-1"
                    />
                    <button onClick={() => void saveEdit(note.id)} className="mt-1 rounded bg-emerald-600 px-2 py-0.5 text-white">
                      Save
                    </button>
                    <button onClick={() => setEditingId(null)} className="ml-1 text-slate-500">
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="text-slate-700">{renderNoteBody(note.body)}</div>
                )}
              </li>
            ))}
            {notes.length === 0 && <li className="text-slate-400">No notes yet.</li>}
          </ul>
        </div>
      </div>
    </details>
  )
}
