import { useState } from 'react'
import { MAX_TAGS, addTags, removeTag } from '../lib/tags'

interface TagEditorProps {
  tags: string[]
  /** Called with the full next list; the parent persists it. Resolves
   *  false when the save failed (the typed text is then kept). */
  onChange: (next: string[]) => Promise<boolean> | void
  disabled?: boolean
}

/** The deal header's tag chip row: Enter (or a comma) adds — several can be
 *  typed at once ("core, miami") — × removes, capped at 20. The rules live
 *  in lib/tags (they mirror the backend's). Tags aren't deal inputs, so
 *  they stay editable while the deal is IC-locked. */
export default function TagEditor({ tags, onChange, disabled = false }: TagEditorProps) {
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function apply(next: string[], clearDraft: boolean) {
    setBusy(true)
    try {
      const ok = await onChange(next)
      if (ok !== false && clearDraft) setDraft('')
    } finally {
      setBusy(false)
    }
  }

  function commit() {
    if (!draft.trim()) return
    const result = addTags(tags, draft)
    if (!result.ok) {
      setError(result.error)
      return
    }
    setError(null)
    void apply(result.tags, true)
  }

  const full = tags.length >= MAX_TAGS
  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Deal tags">
      <span className="text-[10px] font-semibold tracking-wide text-slate-400">TAGS</span>
      {tags.map((tag) => (
        <span key={tag} className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
          {tag}
          <button
            type="button"
            onClick={() => void apply(removeTag(tags, tag), false)}
            disabled={disabled || busy}
            aria-label={`Remove tag ${tag}`}
            className="ml-0.5 text-slate-400 hover:text-red-600 disabled:opacity-40"
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value)
          if (error) setError(null)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault()
            commit()
          } else if (e.key === 'Escape') {
            setDraft('')
            setError(null)
          }
        }}
        disabled={disabled || busy || full}
        placeholder={full ? `Max ${MAX_TAGS} tags` : 'Add tag… ↵'}
        aria-label="Add a tag (press Enter)"
        aria-invalid={error !== null}
        aria-describedby={error ? 'tag-editor-error' : undefined}
        className="w-28 rounded border border-slate-200 px-1.5 py-0.5 text-[11px]"
      />
      {error && (
        <span id="tag-editor-error" role="alert" className="text-[11px] text-red-600">
          {error}
        </span>
      )}
    </div>
  )
}
