// Deal autosave + hydration logic, framework-free so it can be unit-tested
// without rendering. App.tsx wraps this in refs/effects; nothing here touches
// React or the DOM (localStorage key excepted, used by App only).

import {
  ACQUISITION_QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_DEFAULTS,
  parseAcquisitionQuickScreenInputs,
  parseQuickScreenInputs,
  type AcquisitionQuickScreenInputs,
  type QuickScreenInputs,
} from './quickScreenMath'

export const ACTIVE_DEAL_STORAGE_KEY = 'cre-active-deal-id'

/** Key inside Deal.inputs holding the Quick Screen state, beside the Deal
 *  Inputs field ids. No schema field id collides with it. */
export const QUICK_SCREEN_INPUTS_KEY = 'quickScreen'
/** B6: the acquisition napkin + which napkin is active ride the same blob. */
export const ACQUISITION_QUICK_SCREEN_INPUTS_KEY = 'acquisitionQuickScreen'
export const QUICK_SCREEN_MODE_KEY = 'quickScreenMode'

export type QuickScreenMode = 'development' | 'acquisition'

// ---------------------------------------------------------------------------
// Autosave: debounced, coalescing, never overlapping saves.
// ---------------------------------------------------------------------------

export type AutosaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

export interface Autosaver<T> {
  /** Record a new value and (re)start the debounce clock. */
  schedule: (value: T) => void
  /** Save any unsaved value immediately (e.g. before switching deals). */
  flush: () => Promise<void>
  /** Drop the pending value and timer without saving (B12: the deal was
   *  deleted — a PUT to its id would only fail). An in-flight save's
   *  failure is swallowed too; the autosaver stays usable afterwards. */
  cancel: () => void
  dispose: () => void
  getState: () => AutosaveState
  subscribe: (listener: (state: AutosaveState) => void) => () => void
}

export function createAutosaver<T>(
  save: (value: T) => Promise<void>,
  delayMs = 2000,
): Autosaver<T> {
  let timer: ReturnType<typeof setTimeout> | null = null
  let state: AutosaveState = 'idle'
  let latest: { value: T } | null = null // most recent value not yet saved
  let saving = false
  let disposed = false
  // Set by cancel() while a save is in flight: its outcome is discarded.
  let discardInFlight = false
  const listeners = new Set<(s: AutosaveState) => void>()

  function setState(next: AutosaveState) {
    if (disposed) return
    state = next
    for (const listener of listeners) listener(next)
  }

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  async function saveNow(): Promise<void> {
    clearTimer()
    if (saving || latest === null || disposed) return
    saving = true
    const { value } = latest
    latest = null
    setState('saving')
    try {
      await save(value)
      saving = false
      if (discardInFlight) {
        discardInFlight = false
        setState(latest === null ? 'idle' : 'pending')
      } else if (latest !== null) {
        // A newer value arrived while this save was in flight — chain it.
        await saveNow()
      } else {
        setState('saved')
      }
    } catch {
      saving = false
      if (discardInFlight) {
        discardInFlight = false
        setState(latest === null ? 'idle' : 'pending')
        return
      }
      // Keep the failed value so a later schedule/flush retries it, unless a
      // newer one already superseded it.
      if (latest === null) latest = { value }
      setState('error')
    }
  }

  return {
    schedule(value: T) {
      if (disposed) return
      latest = { value }
      setState('pending')
      clearTimer()
      timer = setTimeout(() => {
        void saveNow()
      }, delayMs)
    },
    flush: () => saveNow(),
    cancel() {
      if (disposed) return
      clearTimer()
      latest = null
      if (saving) discardInFlight = true
      else setState('idle')
    },
    dispose() {
      disposed = true
      clearTimer()
      listeners.clear()
    },
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}

// ---------------------------------------------------------------------------
// Optimistic concurrency (wave 2): one ETag per deal from the last
// single-deal response, sent back as If-Match on autosave PUTs. A 412 parks
// the autosave until the user picks Reload (adopt the server copy) or
// Overwrite (retry without If-Match). Pure so the decision logic is testable.
// ---------------------------------------------------------------------------

export interface SaveConflict<D> {
  dealId: string
  /** The server's copy, as returned in the 412 body. */
  current: D
  /** ETag of `current` when the 412 carried one (null otherwise). */
  etag: string | null
}

export interface SaveConcurrency<D> {
  /** Remember the ETag of a fresh single-deal response (null clears it).
   *  Also lifts a pending "overwrite" for that deal — the server has now
   *  acknowledged a write, so later PUTs guard again. */
  recordEtag(dealId: string, etag: string | null): void
  etagFor(dealId: string): string | null
  /** Header value for the next PUT: undefined when no ETag is known or the
   *  user chose Overwrite (unconditional write until a fresh ETag lands). */
  ifMatchFor(dealId: string): string | undefined
  /** True while a 412 for this deal awaits the user's choice — the autosave
   *  must not hit the network. */
  isBlocked(dealId: string): boolean
  markConflict(conflict: SaveConflict<D>): void
  conflict(): SaveConflict<D> | null
  /** Resolve by keeping the local edits: clears the block and drops the
   *  ETag so the retry goes out without If-Match. Returns the deal id. */
  chooseOverwrite(): string | null
  /** Resolve by adopting the server copy: clears the block, records the
   *  conflict's ETag (if any) and returns the conflict for the caller to
   *  apply. */
  chooseReload(): SaveConflict<D> | null
  /** Forget everything about a deal (deleted, or the conflict is moot). */
  forget(dealId: string): void
}

export function createSaveConcurrency<D>(): SaveConcurrency<D> {
  const etags = new Map<string, string>()
  const overwriting = new Set<string>()
  let pending: SaveConflict<D> | null = null
  return {
    recordEtag(dealId, etag) {
      if (etag) etags.set(dealId, etag)
      else etags.delete(dealId)
      overwriting.delete(dealId)
    },
    etagFor: (dealId) => etags.get(dealId) ?? null,
    ifMatchFor(dealId) {
      if (overwriting.has(dealId)) return undefined
      return etags.get(dealId)
    },
    isBlocked: (dealId) => pending !== null && pending.dealId === dealId,
    markConflict(conflict) {
      pending = conflict
    },
    conflict: () => pending,
    chooseOverwrite() {
      if (!pending) return null
      const { dealId } = pending
      pending = null
      overwriting.add(dealId)
      etags.delete(dealId)
      return dealId
    },
    chooseReload() {
      if (!pending) return null
      const conflict = pending
      pending = null
      overwriting.delete(conflict.dealId)
      if (conflict.etag) etags.set(conflict.dealId, conflict.etag)
      else etags.delete(conflict.dealId)
      return conflict
    },
    forget(dealId) {
      etags.delete(dealId)
      overwriting.delete(dealId)
      if (pending?.dealId === dealId) pending = null
    },
  }
}

// ---------------------------------------------------------------------------
// Hydration: deal inputs JSON -> form values + quick screen state.
// ---------------------------------------------------------------------------

export interface HydratedDealState {
  formValues: Record<string, unknown>
  quickScreen: QuickScreenInputs
  acquisitionQuickScreen: AcquisitionQuickScreenInputs
  quickScreenMode: QuickScreenMode
  /** True when URL params supplied any quick-screen state (they win on first
   *  load, then the autosave syncs them into the deal). */
  quickScreenFromUrl: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseQuickScreenMode(raw: unknown): QuickScreenMode | null {
  return raw === 'development' || raw === 'acquisition' ? raw : null
}

export function hydrateDealState(
  schemaDefaults: Record<string, unknown>,
  dealInputs: Record<string, unknown>,
  urlParams: URLSearchParams,
): HydratedDealState {
  const {
    [QUICK_SCREEN_INPUTS_KEY]: stored,
    [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: storedAcquisition,
    [QUICK_SCREEN_MODE_KEY]: storedMode,
    ...fieldValues
  } = dealInputs

  const fromUrl = parseQuickScreenInputs(urlParams)
  let quickScreen: QuickScreenInputs
  if (fromUrl !== null) {
    quickScreen = fromUrl
  } else if (isRecord(stored)) {
    // Merge over defaults so a deal saved before a new quick-screen input
    // existed still hydrates every field.
    quickScreen = { ...QUICK_SCREEN_DEFAULTS, ...(stored as Partial<QuickScreenInputs>) }
  } else {
    quickScreen = QUICK_SCREEN_DEFAULTS
  }

  const acquisitionFromUrl = parseAcquisitionQuickScreenInputs(urlParams)
  let acquisitionQuickScreen: AcquisitionQuickScreenInputs
  if (acquisitionFromUrl !== null) {
    acquisitionQuickScreen = acquisitionFromUrl
  } else if (isRecord(storedAcquisition)) {
    acquisitionQuickScreen = {
      ...ACQUISITION_QUICK_SCREEN_DEFAULTS,
      ...(storedAcquisition as Partial<AcquisitionQuickScreenInputs>),
    }
  } else {
    acquisitionQuickScreen = ACQUISITION_QUICK_SCREEN_DEFAULTS
  }

  const modeFromUrl = parseQuickScreenMode(urlParams.get('screen'))
  const quickScreenMode = modeFromUrl ?? parseQuickScreenMode(storedMode) ?? 'development'

  return {
    formValues: { ...schemaDefaults, ...fieldValues },
    quickScreen,
    acquisitionQuickScreen,
    quickScreenMode,
    quickScreenFromUrl: fromUrl !== null || acquisitionFromUrl !== null || modeFromUrl !== null,
  }
}

/** Inverse of hydrateDealState: pack current state into the Deal.inputs blob. */
export function serializeDealInputs(
  formValues: Record<string, unknown>,
  quickScreen: QuickScreenInputs,
  acquisitionQuickScreen: AcquisitionQuickScreenInputs = ACQUISITION_QUICK_SCREEN_DEFAULTS,
  quickScreenMode: QuickScreenMode = 'development',
): Record<string, unknown> {
  return {
    ...formValues,
    [QUICK_SCREEN_INPUTS_KEY]: quickScreen,
    [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: acquisitionQuickScreen,
    [QUICK_SCREEN_MODE_KEY]: quickScreenMode,
  }
}
