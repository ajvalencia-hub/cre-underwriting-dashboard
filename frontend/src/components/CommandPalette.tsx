import { useEffect, useMemo, useRef, useState } from 'react'
import { globalSearch, type SearchGroup, type SearchItem } from '../lib/api'
import { searchCommands, type CommandGroup, type PaletteCommand } from '../lib/commandSearch'
import { nextIndex } from '../lib/searchNav'

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  /** Actions, tabs and this deal's fields (roadmap #30). */
  commands: PaletteCommand[]
  /** Deep-link into the app. dealId present -> open that deal first. */
  onNavigate: (item: SearchItem, kind: SearchGroup['kind']) => void
}

const SERVER_GROUP_LABELS: Record<SearchGroup['kind'], string> = {
  deals: 'Deals',
  tenants: 'Tenants',
  comps: 'Comps',
  notes: 'Notes',
}

const COMMAND_GROUP_LABELS: Record<CommandGroup, string> = {
  actions: 'Actions',
  tabs: 'Go to',
  fields: 'Deal Inputs fields',
}

/** Local groups lead: they answer without a round trip. */
const COMMAND_GROUP_ORDER: CommandGroup[] = ['actions', 'fields', 'tabs']
const COMMAND_LIMITS: Partial<Record<CommandGroup, number>> = { actions: 6, fields: 8, tabs: 6 }

const DEBOUNCE_MS = 180

interface Row {
  key: string
  title: string
  subtitle?: string
  shortcut?: string
  dealType?: SearchItem['dealType']
  activate: () => void
}

/** J13 + roadmap #30: Cmd+K palette — run an action, jump to a tab or a
 *  Deal Inputs field, or search deals, tenants, comps and notes. */
export default function CommandPalette({ open, onClose, commands, onNavigate }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const [groups, setGroups] = useState<SearchGroup[]>([])
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setQuery('')
      setGroups([])
      setActive(0)
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
        .then((res) => setGroups(res.groups))
        .catch(() => setGroups([]))
    }, DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [query, open])

  const sections = useMemo(() => {
    const matched = searchCommands(commands, query, COMMAND_LIMITS)
    const local = COMMAND_GROUP_ORDER.map((group) => ({
      key: group,
      label: COMMAND_GROUP_LABELS[group],
      rows: matched
        .filter((c) => c.group === group)
        .map<Row>((c) => ({ key: c.id, title: c.title, subtitle: c.subtitle, shortcut: c.shortcut, activate: c.run })),
    }))
    const server = groups.map((group) => ({
      key: `search-${group.kind}`,
      label: SERVER_GROUP_LABELS[group.kind],
      rows: group.items.map<Row>((item) => ({
        key: `${group.kind}-${item.id}`,
        title: item.title,
        subtitle: item.subtitle ?? undefined,
        dealType: item.dealType,
        activate: () => onNavigate(item, group.kind),
      })),
    }))
    return [...local, ...server].filter((s) => s.rows.length > 0)
  }, [commands, query, groups, onNavigate])

  const flat = sections.flatMap((s) => s.rows)
  // A new result set keeps the highlight in range (server results arrive late).
  const activeIndex = Math.min(active, flat.length - 1)

  if (!open) return null

  function choose(row: Row) {
    onClose()
    row.activate()
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive(nextIndex(activeIndex, 1, flat.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive(nextIndex(activeIndex, -1, flat.length))
    } else if (e.key === 'Enter' && flat[activeIndex]) {
      e.preventDefault()
      choose(flat[activeIndex])
    }
  }

  let flatIndex = -1
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 pt-24" onClick={onClose}>
      <div
        role="dialog"
        aria-label="Command palette"
        className="w-full max-w-xl rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          // Focused as it mounts, so keys typed right after ⌘K aren't lost.
          autoFocus
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setActive(0)
          }}
          onKeyDown={handleKey}
          placeholder="Run an action, jump to a field or tab, or search deals…"
          aria-label="Command or search"
          className="w-full rounded-t-lg border-b border-slate-200 px-4 py-3 text-sm outline-none"
        />
        <div className="max-h-96 overflow-y-auto">
          {query.trim().length >= 2 && flat.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-slate-500">No matches.</div>
          )}
          {sections.map((section) => (
            <div key={section.key}>
              <div className="px-4 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                {section.label}
              </div>
              {section.rows.map((row) => {
                flatIndex += 1
                const index = flatIndex
                return (
                  <button
                    key={row.key}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => choose(row)}
                    className={`flex w-full items-center justify-between gap-3 px-4 py-1.5 text-left ${
                      index === activeIndex ? 'bg-sky-50' : ''
                    }`}
                  >
                    <span className="flex min-w-0 flex-col items-start">
                      <span className="flex items-center gap-1.5 text-sm text-slate-700">
                        {row.title}
                        {row.dealType && (
                          <span
                            className={`rounded px-1 py-0.5 text-[9px] font-semibold ${
                              row.dealType === 'development'
                                ? 'bg-orange-100 text-orange-700'
                                : 'bg-sky-100 text-sky-700'
                            }`}
                          >
                            {row.dealType === 'development' ? 'DEV' : 'ACQ'}
                          </span>
                        )}
                      </span>
                      {row.subtitle && <span className="text-[11px] text-slate-500">{row.subtitle}</span>}
                    </span>
                    {row.shortcut && (
                      <kbd className="shrink-0 rounded border border-slate-200 px-1.5 text-[10px] text-slate-500">
                        {row.shortcut}
                      </kbd>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
        <div className="border-t border-slate-100 px-4 py-1.5 text-[10px] text-slate-500">
          ↑↓ navigate · ↵ run or open · esc close · prefix <code>acq:</code> / <code>dev:</code> to filter
          one dealflow
        </div>
      </div>
    </div>
  )
}
