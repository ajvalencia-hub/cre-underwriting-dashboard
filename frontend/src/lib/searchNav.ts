import type { SearchGroup, SearchItem } from './api'

/** J13: flatten grouped results into the linear order the arrow keys walk
 *  (group order preserved, items within a group in server rank order). */
export function flattenGroups(groups: SearchGroup[]): SearchItem[] {
  return groups.flatMap((g) => g.items)
}

/** Next active index for an arrow key. Wraps at both ends so the list is a
 *  ring; a length of 0 yields -1 (nothing to select). */
export function nextIndex(current: number, delta: number, length: number): number {
  if (length <= 0) return -1
  return (((current + delta) % length) + length) % length
}
