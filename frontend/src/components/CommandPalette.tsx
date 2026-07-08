import { useEffect, useRef, useState } from 'react'
import { globalSearch, type SearchGroup, type SearchItem } from '../lib/api'
import { flattenGroups, nextIndex } from '../lib/searchNav'

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  /** Deep-link into the app. dealId present -> open that deal first. */
  onNavigate: (item: SearchItem, kind: SearchGroup['kind']) => void
}

const GROUP_LABELS: Record<SearchGroup['kind'], string> = {
  deals: 'Deals',
  tenants: 'Tenants',
  comps: 'Comps',
  notes: 'Notes',
}

const DEBOUNCE_MS = 180

/** J13: Cmd+K global search palette — deals, tenants, comps, notes. */
export default function CommandPalette({ open, onClose, onNavigate }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const [groups, setGroups] = useState<SearchGroup[]>([])
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setQuery('')
      setGroups([])
      setActive(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const q = query.trim()
    if (q.length < 2) {
      setGroups([])
      return
    }
    const handle = setTimeout(() => {
      globalSearch(q)
        .then((res) => {
          setGroups(res.groups)
          setActive(0)
        })
        .catch(() => setGroups([]))
    }, DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [query, open])

  if (!open) return null

  const flat = flattenGroups(groups)
  // Group lookup for the active item so navigate() knows the kind.
  const kindOf = (item: SearchItem): SearchGroup['kind'] =>
    groups.find((g) => g.items.includes(item))?.kind ?? 'deals'

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => nextIndex(i, 1, flat.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => nextIndex(i, -1, flat.length))
    } else if (e.key === 'Enter' && flat[active]) {
      onNavigate(flat[active], kindOf(flat[active]))
      onClose()
    }
  }

  let flatIndex = -1
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 pt-24" onClick={onClose}>
      <div
        className="w-full max-w-xl rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Search deals, tenants, comps, notes…"
          className="w-full rounded-t-lg border-b border-slate-200 px-4 py-3 text-sm outline-none"
        />
        <div className="max-h-96 overflow-y-auto">
          {query.trim().length >= 2 && flat.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-slate-400">No matches.</div>
          )}
          {groups.map((group) => (
            <div key={group.kind}>
              <div className="px-4 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                {GROUP_LABELS[group.kind]}
              </div>
              {group.items.map((item) => {
                flatIndex += 1
                const isActive = flatIndex === active
                return (
                  <button
                    key={item.id}
                    onMouseEnter={() => setActive(flat.indexOf(item))}
                    onClick={() => {
                      onNavigate(item, group.kind)
                      onClose()
                    }}
                    className={`flex w-full flex-col items-start px-4 py-1.5 text-left ${
                      isActive ? 'bg-sky-50' : ''
                    }`}
                  >
                    <span className="text-sm text-slate-700">{item.title}</span>
                    {item.subtitle && (
                      <span className="text-[11px] text-slate-400">{item.subtitle}</span>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
        <div className="border-t border-slate-100 px-4 py-1.5 text-[10px] text-slate-400">
          ↑↓ navigate · ↵ open · esc close
        </div>
      </div>
    </div>
  )
}
