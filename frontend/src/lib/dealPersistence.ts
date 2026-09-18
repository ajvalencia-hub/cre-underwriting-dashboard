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

// ---------------------------------------------------------------------------
// Autosave: debounced, coalescing, never overlapping saves.
// ---------------------------------------------------------------------------

export type AutosaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

export interface Autosaver<T> {
  /** Record a new value and (re)start the debounce clock. */
  schedule: (value: T) => void
  /** Save any unsaved value immediately (e.g. before switching deals).
   *  Resolves true when nothing is left unsaved. */
  flush: () => Promise<boolean>
  /** True while there are edits the server hasn't accepted yet. */
  hasUnsaved: () => boolean
  dispose: () => void
  getState: () => AutosaveState
  subscribe: (listener: (state: AutosaveState) => void) => () => void
}

/** After a failed save, retry on its own (it used to wait for the next edit). */
export const RETRY_DELAYS_MS = [3000, 10000, 30000]

export function createAutosaver<T>(
  save: (value: T) => Promise<void>,
  delayMs = 2000,
): Autosaver<T> {
  let timer: ReturnType<typeof setTimeout> | null = null
  let failures = 0
  let state: AutosaveState = 'idle'
  let latest: { value: T } | null = null // most recent value not yet saved
  let saving = false
  let disposed = false
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
      failures = 0
      if (latest !== null) {
        // A newer value arrived while this save was in flight — chain it.
        await saveNow()
      } else {
        setState('saved')
      }
    } catch {
      saving = false
      // Keep the failed value so a later schedule/flush retries it, unless a
      // newer one already superseded it.
      if (latest === null) latest = { value }
      setState('error')
      const retryIn = RETRY_DELAYS_MS[Math.min(failures, RETRY_DELAYS_MS.length - 1)]
      failures++
      if (!disposed && timer === null) {
        timer = setTimeout(() => {
          timer = null
          void saveNow()
        }, retryIn)
      }
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
    async flush() {
      await saveNow()
      return latest === null && !saving && state !== 'error'
    },
    hasUnsaved: () => latest !== null || saving,
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
  }
}

/** Inverse of hydrateDealState: pack current state into the Deal.inputs blob. */
export function serializeDealInputs(
  formValues: Record<string, unknown>,
  quickScreen: QuickScreenInputs,
  acquisitionQuickScreen: AcquisitionQuickScreenInputs,
): Record<string, unknown> {
  return {
    ...formValues,
    [QUICK_SCREEN_INPUTS_KEY]: quickScreen,
    [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: acquisitionQuickScreen,
  }
}
