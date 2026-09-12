// Recently viewed deals (F9): the last N deal ids, newest first, kept in
// (safe) storage and surfaced by the command palette when the query is empty.

export const RECENT_DEALS_KEY = 'cre.recentDeals'
export const RECENT_DEALS_MAX = 8

interface KeyValueStore {
  get(key: string): string | null
  set(key: string, value: string): unknown
}

export function pushRecent(list: readonly string[], id: string, max = RECENT_DEALS_MAX): string[] {
  return [id, ...list.filter((x) => x !== id)].slice(0, max)
}

export function parseRecent(raw: string | null): string[] {
  if (!raw) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

export function loadRecent(storage: KeyValueStore): string[] {
  return parseRecent(storage.get(RECENT_DEALS_KEY))
}

/** Record a visit and return the updated list. */
export function recordRecent(storage: KeyValueStore, id: string, max = RECENT_DEALS_MAX): string[] {
  const next = pushRecent(loadRecent(storage), id, max)
  storage.set(RECENT_DEALS_KEY, JSON.stringify(next))
  return next
}
