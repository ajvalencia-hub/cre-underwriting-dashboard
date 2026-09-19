import { useEffect, useRef, useState } from 'react'
import FileChooser, { type FileChooserHandle } from './FileChooser'
import type { AutosaveState } from '../lib/dealPersistence'
import { dateStatus, readCriticalDates, sortByDate } from '../lib/criticalDates'
import { dealTypeOf, type DealType } from '../lib/dealStages'
import type { IcState } from '../lib/api'
import { IC_STATE_LABELS, IC_STATE_STYLES } from '../lib/icWorkflow'
import type { Deal } from '../types/deal'

const AUTOSAVE_LABEL: Record<AutosaveState, string> = {
  idle: '',
  pending: 'Saving…',
  saving: 'Saving…',
  saved: 'Saved',
  error: 'Not saved — retrying automatically',
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
}: Props) {
  const [renamingName, setRenamingName] = useState<string | null>(null)
  const [newDealMenuOpen, setNewDealMenuOpen] = useState(false)
  const importInputRef = useRef<FileChooserHandle>(null)
  const activeDeal = deals.find((d) => d.id === activeDealId) ?? null
  const type = dealTypeOf({ inputs: values })

  useEffect(() => {
    if (!newDealMenuOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setNewDealMenuOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [newDealMenuOpen])

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
    <div className="mb-4 flex flex-wrap items-center gap-2">
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
      {icState && icState !== 'draft' && (
        <button
          onClick={onOpenIc}
          title="Investment committee — open the IC Approval tab"
          className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${IC_STATE_STYLES[icState]}`}
        >
          {IC_STATE_LABELS[icState]}
        </button>
      )}
      <div className="relative">
        <button
          onClick={() => setNewDealMenuOpen((v) => !v)}
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
          autosaveState === 'error' ? 'text-red-500' : 'text-slate-400'
        }`}
      >
        {AUTOSAVE_LABEL[autosaveState]}
      </span>
    </div>
  )
}
