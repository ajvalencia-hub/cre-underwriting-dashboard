// Are the numbers on screen current? Every computed result is stamped with
// the deal and the exact inputs it came from; anything that changes the
// inputs afterwards makes it stale, and the UI says so instead of showing
// old numbers as if they were current.

export type ResultSource = 'native' | 'excel'

export interface ResultStamp {
  source: ResultSource
  /** ms since epoch when the result arrived */
  at: number
  /** fingerprint of the inputs the result was computed from */
  inputsKey: string
  dealId: string | null
}

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value as Record<string, unknown>)
        .sort()
        .filter((k) => (value as Record<string, unknown>)[k] !== undefined)
        .map((k) => [k, stable((value as Record<string, unknown>)[k])]),
    )
  }
  return value
}

/** Order-independent fingerprint of a set of deal inputs. */
export function inputsKey(values: Record<string, unknown>): string {
  return JSON.stringify(stable(values))
}

export function stampResult(
  source: ResultSource,
  values: Record<string, unknown>,
  dealId: string | null,
  now: number = Date.now(),
): ResultStamp {
  return { source, at: now, inputsKey: inputsKey(values), dealId }
}

export function isStale(stamp: ResultStamp, currentKey: string, currentDealId: string | null): boolean {
  return stamp.dealId !== currentDealId || stamp.inputsKey !== currentKey
}

/** The more recent of two results (either may be missing). */
export function latestStamp(a: ResultStamp | null, b: ResultStamp | null): ResultStamp | null {
  if (!a) return b
  if (!b) return a
  return b.at > a.at ? b : a
}

export const SOURCE_LABEL: Record<ResultSource, string> = {
  native: 'Built-in engine',
  excel: 'Your Excel template',
}

export const SOURCE_TAG: Record<ResultSource, string> = {
  native: 'engine',
  excel: 'Excel',
}

export function describeStamp(stamp: ResultStamp): string {
  const time = new Date(stamp.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return `${SOURCE_LABEL[stamp.source]} · ${time}`
}

/**
 * For one metric, which result to show: the most recent result that has a
 * value for it. (A template only returns the outputs it maps, so older
 * engine numbers still fill the rest — each labelled with its source.)
 */
export function pickMetric(
  metricId: string,
  results: { stamp: ResultStamp; outputs: Record<string, unknown> }[],
): { value: unknown; stamp: ResultStamp } | null {
  let best: { value: unknown; stamp: ResultStamp } | null = null
  for (const r of results) {
    const value = r.outputs[metricId]
    if (value === undefined || value === null) continue
    if (!best || r.stamp.at > best.stamp.at) best = { value, stamp: r.stamp }
  }
  return best
}
