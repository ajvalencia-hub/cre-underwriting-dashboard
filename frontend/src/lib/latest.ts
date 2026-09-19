// Request sequencing (B5): a monotonically increasing token so a component
// can ignore the resolution of any fetch that is no longer the newest one
// (A→B→C must never end on B).

export interface LatestGuard {
  /** Start a new request; returns its token. */
  next(): number
  /** True while `token` is still the newest request. */
  isCurrent(token: number): boolean
  /** Invalidate every outstanding request without starting a new one. */
  invalidate(): void
}

export function createLatestGuard(): LatestGuard {
  let current = 0
  return {
    next() {
      current += 1
      return current
    },
    isCurrent: (token) => token === current,
    invalidate() {
      current += 1
    },
  }
}
