// Settings > Workflow: the default dealflow for "New Deal". 'ask' (the
// default) keeps the New Deal ▾ menu; a type makes the header's New Deal
// create that type directly. Only this preference is ported from Run 6's
// workflowPrefs — the last-tab half already lives in app/navigation.ts under
// the same `cre.lastTab` key.
import { safeStorage, type StorageLike } from './safeStorage'

export type NewDealTypePref = 'acquisition' | 'development' | 'ask'

export const NEW_DEAL_TYPE_KEY = 'cre.newDealType'

export function loadNewDealTypePref(storage: StorageLike = safeStorage): NewDealTypePref {
  let raw: string | null = null
  try {
    raw = storage.getItem(NEW_DEAL_TYPE_KEY)
  } catch {
    raw = null
  }
  return raw === 'acquisition' || raw === 'development' || raw === 'ask' ? raw : 'ask'
}

export function saveNewDealTypePref(pref: NewDealTypePref, storage: StorageLike = safeStorage): void {
  try {
    storage.setItem(NEW_DEAL_TYPE_KEY, pref)
  } catch {
    // storage unavailable — the choice just isn't remembered
  }
}

/** The type New Deal should create without asking, or null to ask (show
 *  the Acquisition / Development choice). Read at click time, so a change in
 *  Settings applies immediately. */
export function defaultNewDealType(storage: StorageLike = safeStorage): 'acquisition' | 'development' | null {
  const pref = loadNewDealTypePref(storage)
  return pref === 'ask' ? null : pref
}
