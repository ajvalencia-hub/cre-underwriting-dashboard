// Monte Carlo seed parsing (B18): blank = random; anything else must be a
// non-negative whole number — `Number('abc')` is NaN, which the API would
// silently treat as "no seed" and the run would not be reproducible.

export type SeedParse =
  | { ok: true; seed: number | undefined }
  | { ok: false; error: string }

export function parseSeed(raw: string): SeedParse {
  const text = raw.trim()
  if (text === '') return { ok: true, seed: undefined }
  if (!/^\d+$/.test(text)) {
    return { ok: false, error: 'Seed must be a non-negative whole number (or blank for random).' }
  }
  const value = Number(text)
  if (!Number.isSafeInteger(value)) return { ok: false, error: 'Seed is too large.' }
  return { ok: true, seed: value }
}
