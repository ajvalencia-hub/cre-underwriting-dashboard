// Deal autosave + hydration logic, framework-free so it can be unit-tested
// without rendering. App.tsx wraps this in refs/effects; nothing here touches
// React or the DOM (localStorage key excepted, used by App only).

import {
  ACQUISITION_QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_DEFAULTS,
  type AcquisitionQuickScreenInputs,
  type QuickScreenInputs,
} from './quickScreenMath'

export const ACTIVE_DEAL_STORAGE_KEY = 'cre-active-deal-id'

/** Key inside Deal.inputs holding the Quick Screen state, beside the Deal
 *  Inputs field ids. No schema field id collides with it. */
export const QUICK_SCREEN_INPUTS_KEY = 'quickScreen'
/** Same for the acquisition napkin (it used to live only in the URL). */
export const ACQUISITION_QUICK_SCREEN_INPUTS_KEY = 'acquisitionQuickScreen'
/** Which napkin (development / acquisition) the deal's Quick Screen shows.
 *  Only written once the user has picked one (see serializeDealInputs), so
 *  hydrating an older deal never adds a key to its inputs. */
export const QUICK_SCREEN_MODE_KEY = 'quickScreenMode'

export type QuickScreenMode = 'development' | 'acquisition'

export function parseQuickScreenMode(raw: unknown): QuickScreenMode | null {
  return raw === 'development' || raw === 'acquisition' ? raw : null
}

// ---------------------------------------------------------------------------
// Autosave: debounced, coalescing, never overlapping saves.
// ---------------------------------------------------------------------------

/** 'blocked': the last save was refused in a way retrying can't fix (a 412
 *  edit conflict) — the value is kept, nothing retries until the caller
 *  resolves it (flush after Overwrite, or cancel after Reload). */
export type AutosaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error' | 'blocked'

export interface Autosaver<T> {
  /** Record a new value and (re)start the debounce clock. */
  schedule: (value: T) => void
  /** Save any unsaved value immediately (e.g. before switching deals).
   *  Resolves true when nothing is left unsaved. */
  flush: () => Promise<boolean>
  /** True while there are edits the server hasn't accepted yet. */
  hasUnsaved: () => boolean
  /** Drop the unsaved value, the debounce timer AND the retry timer without
   *  saving (the deal was deleted, or its server copy is being adopted). An
   *  in-flight save's outcome is ignored — it can't resurrect the value or
   *  start a retry. The autosaver stays usable; state becomes 'idle'. */
  cancel: () => void
  dispose: () => void
  getState: () => AutosaveState
  subscribe: (listener: (state: AutosaveState) => void) => () => void
}

export interface AutosaverOptions {
  /** False for failures a retry can't fix (e.g. a 412 conflict): the value
   *  is kept and the state becomes 'blocked' with no retry timer. Default:
   *  every failure retries. */
  shouldRetry?: (error: unknown) => boolean
}

/** After a failed save, retry on its own (it used to wait for the next edit). */
export const RETRY_DELAYS_MS = [3000, 10000, 30000]

export function createAutosaver<T>(
  save: (value: T) => Promise<void>,
  delayMs = 2000,
  options: AutosaverOptions = {},
): Autosaver<T> {
  let timer: ReturnType<typeof setTimeout> | null = null
  let failures = 0
  let state: AutosaveState = 'idle'
  let latest: { value: T } | null = null // most recent value not yet saved
  // The running save (and any newer values it chains). flush() awaits it,
  // so a save that's merely in progress isn't reported as a failure.
  let inflight: Promise<void> | null = null
  let disposed = false
  // Bumped by cancel(): a save started under an older generation is ignored.
  let generation = 0
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

  async function run(): Promise<void> {
    let savedAny = false
    while (latest !== null && !disposed) {
      const started = generation
      const { value } = latest
      latest = null
      setState('saving')
      try {
        await save(value)
        if (started !== generation) continue // cancelled mid-save: outcome ignored
        failures = 0
        savedAny = true
      } catch (err) {
        if (started !== generation) continue // cancelled mid-save: no retry
        // Keep the failed value so a later schedule/flush retries it, unless
        // a newer one already superseded it.
        if (latest === null) latest = { value }
        if (options.shouldRetry && !options.shouldRetry(err)) {
          // Retrying can't fix it: park until the caller resolves it.
          setState('blocked')
          return
        }
        setState('error')
        const retryIn = RETRY_DELAYS_MS[Math.min(failures, RETRY_DELAYS_MS.length - 1)]
        failures++
        if (!disposed && timer === null) {
          timer = setTimeout(() => {
            timer = null
            void saveNow()
          }, retryIn)
        }
        return
      }
    }
    setState(savedAny ? 'saved' : 'idle')
  }

  function saveNow(): Promise<void> {
    clearTimer()
    // A value scheduled mid-save is picked up by the running loop.
    if (inflight) return inflight
    if (latest === null || disposed) return Promise.resolve()
    inflight = run().finally(() => {
      inflight = null
    })
    return inflight
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
    async flush() {
      await saveNow()
      return latest === null && inflight === null && state !== 'error'
    },
    hasUnsaved: () => latest !== null || inflight !== null,
    cancel() {
      if (disposed) return
      generation++
      clearTimer() // the debounce timer or a pending retry
      latest = null
      failures = 0
      setState('idle')
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
// Hydration: deal inputs JSON -> form values + both Quick Screen napkins.
// A shared link never feeds in here: opening one is an explicit action
// (see shareLink.ts), so loading the app can't overwrite a deal's napkin.
// ---------------------------------------------------------------------------

export interface HydratedDealState {
  formValues: Record<string, unknown>
  quickScreen: QuickScreenInputs
  acquisitionQuickScreen: AcquisitionQuickScreenInputs
  /** The Quick Screen mode the deal stored, or null when it never stored
   *  one (the app then shows 'development' and writes nothing until the
   *  user picks a mode). */
  quickScreenMode: QuickScreenMode | null
}

function storedObject(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

export function hydrateDealState(
  schemaDefaults: Record<string, unknown>,
  dealInputs: Record<string, unknown>,
): HydratedDealState {
  const {
    [QUICK_SCREEN_INPUTS_KEY]: stored,
    [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: storedAcq,
    [QUICK_SCREEN_MODE_KEY]: storedMode,
    ...fieldValues
  } = dealInputs
  // Merge over defaults so a deal saved before a new napkin input existed
  // still hydrates every field.
  return {
    formValues: { ...schemaDefaults, ...fieldValues },
    quickScreen: { ...QUICK_SCREEN_DEFAULTS, ...(storedObject(stored) as Partial<QuickScreenInputs> | null) },
    acquisitionQuickScreen: {
      ...ACQUISITION_QUICK_SCREEN_DEFAULTS,
      ...(storedObject(storedAcq) as Partial<AcquisitionQuickScreenInputs> | null),
    },
    quickScreenMode: parseQuickScreenMode(storedMode),
  }
}

/** Inverse of hydrateDealState: pack current state into the Deal.inputs blob.
 *  `quickScreenMode` null (the default) writes no mode key — so a deal that
 *  never stored one round-trips unchanged. */
export function serializeDealInputs(
  formValues: Record<string, unknown>,
  quickScreen: QuickScreenInputs,
  acquisitionQuickScreen: AcquisitionQuickScreenInputs,
  quickScreenMode: QuickScreenMode | null = null,
): Record<string, unknown> {
  return {
    ...formValues,
    [QUICK_SCREEN_INPUTS_KEY]: quickScreen,
    [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: acquisitionQuickScreen,
    ...(quickScreenMode ? { [QUICK_SCREEN_MODE_KEY]: quickScreenMode } : {}),
  }
}

/** Which mode value the autosave should write. The stored value stays as
 *  it was when the user hasn't moved off it (so hydration never adds a key)
 *  and while the deal is IC-locked (the server's lock doesn't exempt this
 *  key, so writing it would be refused — the switch then stays on screen
 *  only). */
export function modeToPersist(
  stored: QuickScreenMode | null,
  current: QuickScreenMode,
  icLocked: boolean,
): QuickScreenMode | null {
  if (icLocked) return stored
  if (stored === null && current === 'development') return null
  return current
}

// ---------------------------------------------------------------------------
// Optimistic concurrency (Run 6 wave 2; browser mode only): one ETag per
// deal from the last single-deal response, sent back as If-Match on
// autosave PUTs. A 412 parks the autosave (see AutosaverOptions.shouldRetry
// — it must never enter the retry loop) until the user picks Reload (adopt
// the server copy) or Overwrite (retry without If-Match). Pure, so the
// decision logic is testable.
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
   *  user chose Overwrite (unconditional until a fresh ETag lands). */
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
  /** Subscribe to conflict changes (mark / resolve / forget). */
  subscribe(listener: (conflict: SaveConflict<D> | null) => void): () => void
}

export function createSaveConcurrency<D>(): SaveConcurrency<D> {
  const etags = new Map<string, string>()
  const overwriting = new Set<string>()
  const listeners = new Set<(conflict: SaveConflict<D> | null) => void>()
  let pending: SaveConflict<D> | null = null

  function setPending(next: SaveConflict<D> | null) {
    pending = next
    for (const listener of listeners) listener(next)
  }

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
      setPending(conflict)
    },
    conflict: () => pending,
    chooseOverwrite() {
      if (!pending) return null
      const { dealId } = pending
      overwriting.add(dealId)
      etags.delete(dealId)
      setPending(null)
      return dealId
    },
    chooseReload() {
      if (!pending) return null
      const conflict = pending
      overwriting.delete(conflict.dealId)
      if (conflict.etag) etags.set(conflict.dealId, conflict.etag)
      else etags.delete(conflict.dealId)
      setPending(null)
      return conflict
    },
    forget(dealId) {
      etags.delete(dealId)
      overwriting.delete(dealId)
      if (pending?.dealId === dealId) setPending(null)
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
  }
}
