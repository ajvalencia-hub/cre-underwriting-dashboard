import { useState } from 'react'
import { MAX_TAGS, addTag } from '../lib/tags'

interface TagEditorProps {
  tags: string[]
  /** Called with the full next list; the parent persists it. */
  onChange: (next: string[]) => void
  disabled?: boolean
}

/** Wave 2: the header chip row — Enter adds, × removes, capped at 20. All
 *  normalisation / validation lives in lib/tags. */
export default function TagEditor({ tags, onChange, disabled = false }: TagEditorProps) {
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)

  function commit() {
    const result = addTag(tags, draft)
    if (!result.ok) {
      setError(result.error)
      return
    }
    setError(null)
    setDraft('')
    onChange(result.tags)
  }

  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Deal tags">
      <span className="text-[10px] font-semibold tracking-wide text-slate-400">TAGS</span>
      {tags.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600"
        >
          {tag}
          <button
            type="button"
            onClick={() => onChange(tags.filter((t) => t !== tag))}
            disabled={disabled}
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
          if (e.key === 'Enter') {
            e.preventDefault()
            commit()
          }
        }}
        disabled={disabled || tags.length >= MAX_TAGS}
        placeholder={tags.length >= MAX_TAGS ? `Max ${MAX_TAGS} tags` : 'Add tag… ↵'}
        aria-label="Add a tag (press Enter)"
        aria-invalid={error !== null}
        className="w-28 rounded border border-slate-200 px-1.5 py-0.5 text-[11px]"
      />
      {error && (
        <span role="alert" className="text-[11px] text-red-600">
          {error}
        </span>
      )}
    </div>
  )
}
