// Settings > Workflow (F8): last active tab + the default type for "New
// Deal". Injectable storage for unit tests; App/Settings pass safeStorage.

export type NewDealTypePref = 'acquisition' | 'development' | 'ask'

export const LAST_TAB_KEY = 'cre.lastTab'
export const NEW_DEAL_TYPE_KEY = 'cre.newDealType'

interface KeyValueStore {
  get(key: string): string | null
  set(key: string, value: string): unknown
}

export function loadLastTab<T extends string>(
  storage: KeyValueStore,
  valid: readonly T[],
  fallback: T,
): T {
  const raw = storage.get(LAST_TAB_KEY)
  return raw !== null && (valid as readonly string[]).includes(raw) ? (raw as T) : fallback
}

export function saveLastTab(storage: KeyValueStore, tab: string): void {
  storage.set(LAST_TAB_KEY, tab)
}

export function loadNewDealTypePref(storage: KeyValueStore): NewDealTypePref {
  const raw = storage.get(NEW_DEAL_TYPE_KEY)
  return raw === 'acquisition' || raw === 'development' || raw === 'ask' ? raw : 'ask'
}

export function saveNewDealTypePref(storage: KeyValueStore, pref: NewDealTypePref): void {
  storage.set(NEW_DEAL_TYPE_KEY, pref)
}
