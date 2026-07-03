// Deal autosave + hydration logic, framework-free so it can be unit-tested
// without rendering. App.tsx wraps this in refs/effects; nothing here touches
// React or the DOM (localStorage key excepted, used by App only).

import {
  QUICK_SCREEN_DEFAULTS,
  parseQuickScreenInputs,
  type QuickScreenInputs,
} from './quickScreenMath'

export const ACTIVE_DEAL_STORAGE_KEY = 'cre-active-deal-id'

/** Key inside Deal.inputs holding the Quick Screen state, beside the Deal
 *  Inputs field ids. No schema field id collides with it. */
export const QUICK_SCREEN_INPUTS_KEY = 'quickScreen'

// ---------------------------------------------------------------------------
// Autosave: debounced, coalescing, never overlapping saves.
// ---------------------------------------------------------------------------

export type AutosaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

export interface Autosaver<T> {
  /** Record a new value and (re)start the debounce clock. */
  schedule: (value: T) => void
  /** Save any unsaved value immediately (e.g. before switching deals). */
  flush: () => Promise<void>
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
// Hydration: deal inputs JSON -> form values + quick screen state.
// ---------------------------------------------------------------------------

export interface HydratedDealState {
  formValues: Record<string, unknown>
  quickScreen: QuickScreenInputs
  /** True when URL params supplied the quick screen (they win on first load,
   *  then the autosave syncs them into the deal). */
  quickScreenFromUrl: boolean
}

export function hydrateDealState(
  schemaDefaults: Record<string, unknown>,
  dealInputs: Record<string, unknown>,
  urlParams: URLSearchParams,
): HydratedDealState {
  const { [QUICK_SCREEN_INPUTS_KEY]: stored, ...fieldValues } = dealInputs

  const fromUrl = parseQuickScreenInputs(urlParams)
  let quickScreen: QuickScreenInputs
  if (fromUrl !== null) {
    quickScreen = fromUrl
  } else if (typeof stored === 'object' && stored !== null && !Array.isArray(stored)) {
    // Merge over defaults so a deal saved before a new quick-screen input
    // existed still hydrates every field.
    quickScreen = { ...QUICK_SCREEN_DEFAULTS, ...(stored as Partial<QuickScreenInputs>) }
  } else {
    quickScreen = QUICK_SCREEN_DEFAULTS
  }

  return {
    formValues: { ...schemaDefaults, ...fieldValues },
    quickScreen,
    quickScreenFromUrl: fromUrl !== null,
  }
}

/** Inverse of hydrateDealState: pack current state into the Deal.inputs blob. */
export function serializeDealInputs(
  formValues: Record<string, unknown>,
  quickScreen: QuickScreenInputs,
): Record<string, unknown> {
  return { ...formValues, [QUICK_SCREEN_INPUTS_KEY]: quickScreen }
}
