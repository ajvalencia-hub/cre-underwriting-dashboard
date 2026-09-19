import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import FileChooser, { type FileChooserHandle } from './FileChooser'
import TagEditor from './TagEditor'
import type { AutosaveState } from '../lib/dealPersistence'
import { dateStatus, readCriticalDates, sortByDate } from '../lib/criticalDates'
import { dealTypeOf, type DealType } from '../lib/dealStages'
import type { IcState } from '../lib/api'
import { IC_STATE_LABELS, IC_STATE_STYLES } from '../lib/icWorkflow'
import { defaultNewDealType } from '../lib/newDealPrefs'
import type { Deal } from '../types/deal'

const AUTOSAVE_LABEL: Record<AutosaveState, string> = {
  idle: '',
  pending: 'Saving…',
  saving: 'Saving…',
  saved: 'Saved',
  error: 'Not saved — retrying automatically',
  blocked: 'Not saved — changed elsewhere',
}

interface Props {
  deals: Deal[]
  activeDealId: string | null
  /** The active deal's form values: its type badge and date chips. */
  values: Record<string, unknown>
  /** The saved scenario the inputs were loaded from, if any. */
  loadedScenario: { name: string; modified: boolean } | null
  autosaveState: AutosaveState
  /** Investment-committee state; draft shows nothing. */
  icState: IcState | null
  onOpenIc: () => void
  onSwitchDeal: (dealId: string) => void
  /** Resolves true when the name was saved (the rename box then closes). */
  onRename: (name: string) => Promise<boolean>
  /** Resolves false when the deal stays put (its edits weren't saved). */
  onNewDeal: (type: DealType) => Promise<boolean>
  onDelete: () => void
  onExport: () => void
  onImportFile: (file: File) => void
  onOpenDates: () => void
  /** The server's copy of the deal has no dealType (a legacy deal). */
  untyped: boolean
  /** Assign a dealflow to an untyped deal (the "Untyped — set type" chip). */
  onSetType: (type: DealType) => void
  /** More ▾ → Duplicate… (App asks for the name). */
  onDuplicate: () => void
  /** More ▾ → Archive (App confirms, then opens another deal). */
  onArchive: () => void
  /** The tag chip row under the deal picker; the parent persists. */
  onTagsChange: (tags: string[]) => Promise<boolean>
  /** Rendered under the header row (e.g. the edit-conflict banner). */
  children?: ReactNode
}

const MENU_ITEM = 'block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-slate-50'

/** Close an open popover on Escape or a mousedown outside `ref`. */
function useDismiss(open: boolean, ref: RefObject<HTMLElement | null>, close: () => void) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    const onDown = (e: MouseEvent) => {
      if (ref.current && e.target instanceof Node && !ref.current.contains(e.target)) close()
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open, ref, close])
}

/** The active deal's header: picker, rename, type badge, New Deal menu,
 *  delete/export/import, key dates, and save status. Split out of App.tsx
 *  (roadmap #32). */
export default function DealHeaderBar({
  deals,
  activeDealId,
  values,
  loadedScenario,
  autosaveState,
  icState,
  onOpenIc,
  onSwitchDeal,
  onRename,
  onNewDeal,
  onDelete,
  onExport,
  onImportFile,
  onOpenDates,
  onSetType,
  onDuplicate,
  onArchive,
  onTagsChange,
  untyped,
  children,
}: Props) {
  const [renamingName, setRenamingName] = useState<string | null>(null)
  const [newDealMenuOpen, setNewDealMenuOpen] = useState(false)
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)
  const importInputRef = useRef<FileChooserHandle>(null)
  const newDealMenuRef = useRef<HTMLDivElement>(null)
  const moreMenuRef = useRef<HTMLDivElement>(null)
  const activeDeal = deals.find((d) => d.id === activeDealId) ?? null
  // The form shows the schema's default type even for a deal the server
  // stores untyped — the chip below, not a badge, is what's true then.
  const type = untyped ? null : dealTypeOf({ inputs: values })

  const closeNewDealMenu = useCallback(() => setNewDealMenuOpen(false), [])
  const closeMoreMenu = useCallback(() => setMoreMenuOpen(false), [])
  useDismiss(newDealMenuOpen, newDealMenuRef, closeNewDealMenu)
  useDismiss(moreMenuOpen, moreMenuRef, closeMoreMenu)

  async function commitRename(name: string) {
    if (!name.trim()) {
      setRenamingName(null)
      return
    }
    // On failure the box stays open with what was typed, so nothing is lost.
    if (await onRename(name.trim())) setRenamingName(null)
  }

  async function chooseNewDeal(dealType: DealType) {
    if (await onNewDeal(dealType)) setNewDealMenuOpen(false)
  }

  return (
    <div className="mb-4">
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-xs font-semibold tracking-wide text-slate-400">DEAL</label>
      <select
        value={activeDealId ?? ''}
        onChange={(e) => onSwitchDeal(e.target.value)}
        className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
      >
        {deals.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>
      {renamingName === null ? (
        <button
          onClick={() => setRenamingName(activeDeal?.name ?? '')}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Rename
        </button>
      ) : (
        <input
          autoFocus
          value={renamingName}
          onChange={(e) => setRenamingName(e.target.value)}
          onBlur={() => void commitRename(renamingName)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void commitRename(renamingName)
            if (e.key === 'Escape') setRenamingName(null)
          }}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        />
      )}
      {/* Type badge: which dealflow the active deal belongs to. */}
      {type && (
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
            type === 'development' ? 'bg-orange-100 text-orange-700' : 'bg-sky-100 text-sky-700'
          }`}
        >
          {type === 'development' ? 'DEV' : 'ACQ'}
        </span>
      )}
      {/* An untyped (legacy) deal can't compute — say so and offer the fix. */}
      {untyped && activeDeal && (
        <span
          role="group"
          aria-label="Untyped deal — set its type"
          className="flex items-center gap-1 rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800"
        >
          <span className="font-semibold">Untyped — set type:</span>
          <button
            onClick={() => onSetType('acquisition')}
            aria-label="Set type: Acquisition"
            className="rounded px-1 font-medium underline hover:bg-amber-100"
          >
            Acquisition
          </button>
          <span aria-hidden>·</span>
          <button
            onClick={() => onSetType('development')}
            aria-label="Set type: Development"
            className="rounded px-1 font-medium underline hover:bg-amber-100"
          >
            Development
          </button>
        </span>
      )}
      {icState && icState !== 'draft' && (
        <button
          onClick={onOpenIc}
          title="Investment committee — open the IC Approval tab"
          className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${IC_STATE_STYLES[icState]}`}
        >
          {IC_STATE_LABELS[icState]}
        </button>
      )}
      <div className="relative" ref={newDealMenuRef}>
        <button
          onClick={() => {
            // Settings > Workflow can make New Deal create one dealflow
            // directly; 'ask' (the default) keeps the menu. Read at click
            // time so a change in Settings applies immediately.
            const preset = defaultNewDealType()
            if (preset) void chooseNewDeal(preset)
            else setNewDealMenuOpen((v) => !v)
          }}
          aria-haspopup="menu"
          aria-expanded={newDealMenuOpen}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          New Deal ▾
        </button>
        {newDealMenuOpen && (
          <div className="absolute left-0 top-full z-40 mt-1 w-36 rounded border border-slate-200 bg-white py-1 shadow-lg">
            <button
              onClick={() => void chooseNewDeal('acquisition')}
              className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-sky-50"
            >
              Acquisition
            </button>
            <button
              onClick={() => void chooseNewDeal('development')}
              className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-orange-50"
            >
              Development
            </button>
          </div>
        )}
      </div>
      <button
        onClick={onDelete}
        className="rounded border border-slate-300 px-2 py-1 text-xs text-red-500 hover:bg-red-50"
      >
        Delete
      </button>
      <button
        onClick={onExport}
        className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
      >
        Export
      </button>
      <button
        onClick={() => importInputRef.current?.open()}
        className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
      >
        Import
      </button>
      <div className="relative" ref={moreMenuRef}>
        <button
          onClick={() => setMoreMenuOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={moreMenuOpen}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          More ▾
        </button>
        {moreMenuOpen && (
          <div role="menu" className="absolute left-0 top-full z-40 mt-1 w-40 rounded border border-slate-200 bg-white py-1 shadow-lg">
            <button
              role="menuitem"
              onClick={() => {
                setMoreMenuOpen(false)
                onDuplicate()
              }}
              className={MENU_ITEM}
            >
              Duplicate…
            </button>
            <button
              role="menuitem"
              onClick={() => {
                setMoreMenuOpen(false)
                onArchive()
              }}
              className={MENU_ITEM}
            >
              Archive
            </button>
          </div>
        )}
      </div>
      <FileChooser
        ref={importInputRef}
        accept="application/json,.json"
        description="Deal export bundles"
        hidden
        onFiles={(files) => onImportFile(files[0])}
      />
      {/* J11: date chips for the active deal + editor. */}
      {sortByDate(readCriticalDates(values))
        .slice(0, 3)
        .map((row) => {
          const status = dateStatus(row.date, new Date())
          return (
            <span
              key={row.id}
              title={row.notes || row.label}
              className={`rounded px-1.5 py-0.5 text-[11px] ${
                status === 'overdue'
                  ? 'bg-red-100 text-red-700'
                  : status === 'upcoming'
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-slate-100 text-slate-500'
              }`}
            >
              {row.label} {row.date}
            </span>
          )
        })}
      <button
        onClick={onOpenDates}
        className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
      >
        Dates
      </button>
      {loadedScenario && (
        <span
          className="ml-auto rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-600"
          title="The Deal Inputs were loaded from this saved scenario."
        >
          Working from scenario “{loadedScenario.name}”
          {loadedScenario.modified && ' · modified'}
        </span>
      )}
      <span
        className={`${loadedScenario ? '' : 'ml-auto '}text-xs ${
          autosaveState === 'error' || autosaveState === 'blocked' ? 'text-red-500' : 'text-slate-400'
        }`}
      >
        {AUTOSAVE_LABEL[autosaveState]}
      </span>
    </div>
      {activeDeal && (
        <div className="mt-1.5">
          <TagEditor key={activeDeal.id} tags={activeDeal.tags ?? []} onChange={onTagsChange} />
        </div>
      )}
      {children}
    </div>
  )
}
