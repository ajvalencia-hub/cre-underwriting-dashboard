import { useEffect, useRef, useState } from 'react'
import { globalSearch, type SearchGroup, type SearchItem } from '../lib/api'
import { createLatestGuard } from '../lib/latest'
import { flattenGroups, nextIndex } from '../lib/searchNav'

export interface RecentDeal {
  id: string
  name: string
  dealType?: 'acquisition' | 'development' | null
}

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  /** Deep-link into the app. dealId present -> open that deal first. */
  onNavigate: (item: SearchItem, kind: SearchGroup['kind']) => void
  /** F9: recently viewed deals, newest first — shown while the query is empty. */
  recent?: RecentDeal[]
}

const GROUP_LABELS: Record<SearchGroup['kind'], string> = {
  deals: 'Deals',
  tenants: 'Tenants',
  comps: 'Comps',
  notes: 'Notes',
}

const DEBOUNCE_MS = 180

/** F6: the keyboard map shown by "?" (also from the footer). */
const SHORTCUTS: [string, string][] = [
  ['Ctrl/Cmd + K', 'Open this palette'],
  ['Ctrl/Cmd + 1 … 9', 'Switch workflow tabs (Deals, Quick Screen, Documents, …)'],
  ['Esc', 'Close any modal, popover or this palette'],
  ['↑ ↓ / ↵', 'Move through results / open the highlighted one'],
  ['acq: / dev:', 'Prefix a search to filter one dealflow'],
]

/** J13: Cmd+K global search palette — deals, tenants, comps, notes. */
export default function CommandPalette({ open, onClose, onNavigate, recent = [] }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const [groups, setGroups] = useState<SearchGroup[]>([])
  const [active, setActive] = useState(0)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  // B5: keystrokes race the network — only the newest query's result lands.
  const guard = useRef(createLatestGuard())

  useEffect(() => {
    if (open) {
      setQuery('')
      setGroups([])
      setActive(0)
      setShowShortcuts(false)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  // F6: Escape closes the palette even when focus has left the input.
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const q = query.trim()
    if (q.length < 2 || q === '?') {
      guard.current.invalidate()
      setGroups([])
      return
    }
    const handle = setTimeout(() => {
      const token = guard.current.next()
      globalSearch(q)
        .then((res) => {
          if (!guard.current.isCurrent(token)) return
          setGroups(res.groups)
          setActive(0)
        })
        .catch(() => {
          if (guard.current.isCurrent(token)) setGroups([])
        })
    }, DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [query, open])

  if (!open) return null

  // F9: with no query, the "Recent" group is the navigable list.
  const recentAsGroups: SearchGroup[] =
    query.trim() === '' && recent.length > 0
      ? [
          {
            kind: 'deals',
            items: recent.map((d) => ({
              id: d.id,
              title: d.name,
              subtitle: 'Recently viewed',
              dealId: d.id,
              dealType: d.dealType ?? null,
            })),
          },
        ]
      : []
  const shownGroups = query.trim() === '' ? recentAsGroups : groups
  const shortcutsVisible = showShortcuts || query.trim() === '?'
  const flat = flattenGroups(shownGroups)
  // Group lookup for the active item so navigate() knows the kind.
  const kindOf = (item: SearchItem): SearchGroup['kind'] =>
    shownGroups.find((g) => g.items.includes(item))?.kind ?? 'deals'

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
        role="dialog"
        aria-modal="true"
        aria-label="Search and commands"
        className="w-full max-w-xl rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Search deals, tenants, comps, notes… (? for shortcuts)"
          aria-label="Search"
          className="w-full rounded-t-lg border-b border-slate-200 px-4 py-3 text-sm outline-none"
        />
        <div className="max-h-96 overflow-y-auto">
          {shortcutsVisible && (
            <div className="px-4 py-2">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                Keyboard shortcuts
              </div>
              <table className="mt-1 w-full text-xs">
                <tbody>
                  {SHORTCUTS.map(([keys, what]) => (
                    <tr key={keys}>
                      <td className="w-40 py-0.5 pr-3 font-mono text-slate-600">{keys}</td>
                      <td className="py-0.5 text-slate-500">{what}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {query.trim().length >= 2 && query.trim() !== '?' && flat.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-slate-400">No matches.</div>
          )}
          {shownGroups.map((group) => (
            <div key={group.kind}>
              <div className="px-4 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                {query.trim() === '' ? 'Recent' : GROUP_LABELS[group.kind]}
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
                    <span className="flex items-center gap-1.5 text-sm text-slate-700">
                      {item.title}
                      {item.dealType && (
                        <span
                          className={`rounded px-1 py-0.5 text-[9px] font-semibold ${
                            item.dealType === 'development'
                              ? 'bg-orange-100 text-orange-700'
                              : 'bg-sky-100 text-sky-700'
                          }`}
                        >
                          {item.dealType === 'development' ? 'DEV' : 'ACQ'}
                        </span>
                      )}
                    </span>
                    {item.subtitle && (
                      <span className="text-[11px] text-slate-400">{item.subtitle}</span>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2 border-t border-slate-100 px-4 py-1.5 text-[10px] text-slate-400">
          <span className="flex-1">
            ↑↓ navigate · ↵ open · esc close · prefix <code>acq:</code> / <code>dev:</code> to
            filter one dealflow
          </span>
          <button
            onClick={() => setShowShortcuts((v) => !v)}
            aria-pressed={shortcutsVisible}
            aria-label="Keyboard shortcuts"
            title="Keyboard shortcuts"
            className="rounded border border-slate-200 px-1.5 py-0.5 font-mono text-slate-500 hover:bg-slate-50"
          >
            ?
          </button>
        </div>
      </div>
    </div>
  )
}
