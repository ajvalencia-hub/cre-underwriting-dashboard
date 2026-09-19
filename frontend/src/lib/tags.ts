// Deal tags (Run 6 wave 2): pure helpers behind the header chip editor, the
// pipeline tag filter and the bulk add/remove actions.
//
// The rules mirror the backend's `schemas.normalize_tags` exactly, so what
// the chip editor accepts is what the server stores: each tag is trimmed,
// blanks are dropped, duplicates are removed case-insensitively keeping the
// FIRST spelling ("Core" then "core" -> "Core"), a tag may be at most 40
// characters (longer is an error, not a silent cut) and a deal may carry at
// most 20 tags. Case is preserved.

import type { Deal } from '../types/deal'

export const MAX_TAGS = 20
export const MAX_TAG_LENGTH = 40

export function normalizeTag(raw: string): string {
  return raw.trim()
}

/** Case-insensitive identity (the backend dedupes with casefold). */
export function tagKey(tag: string): string {
  return normalizeTag(tag).toLowerCase()
}

export function dealTags(deal: Pick<Deal, 'tags'>): string[] {
  return Array.isArray(deal.tags) ? deal.tags : []
}

/** Split what was typed into the chip editor ("core, miami; value-add")
 *  into candidate tags — commas, semicolons and newlines separate. */
export function parseTagInput(raw: string): string[] {
  return raw
    .split(/[,;\n]/)
    .map(normalizeTag)
    .filter((t) => t !== '')
}

export type TagListResult = { ok: true; tags: string[] } | { ok: false; error: string }

/** Normalize a whole list the way the server will (see the file comment). */
export function normalizeTags(raw: readonly string[], max = MAX_TAGS): TagListResult {
  const seen = new Set<string>()
  const tags: string[] = []
  for (const item of raw) {
    const tag = normalizeTag(item)
    if (!tag) continue
    if (tag.length > MAX_TAG_LENGTH) {
      return { ok: false, error: `"${tag.slice(0, MAX_TAG_LENGTH)}…" is longer than ${MAX_TAG_LENGTH} characters.` }
    }
    const key = tag.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    tags.push(tag)
  }
  if (tags.length > max) return { ok: false, error: `A deal can carry at most ${max} tags.` }
  return { ok: true, tags }
}

/** Append what was typed (may hold several tags); rejects blanks, pure
 *  duplicates, over-long tags and going past the cap. */
export function addTags(tags: readonly string[], raw: string, max = MAX_TAGS): TagListResult {
  const incoming = parseTagInput(raw)
  if (incoming.length === 0) return { ok: false, error: 'Enter a tag first.' }
  const existing = new Set(tags.map(tagKey))
  const fresh = incoming.filter((t) => !existing.has(tagKey(t)))
  if (fresh.length === 0) {
    return { ok: false, error: incoming.length === 1 ? `Already tagged "${incoming[0]}".` : 'Already tagged.' }
  }
  return normalizeTags([...tags, ...fresh], max)
}

/** Single-tag convenience over addTags. */
export function addTag(tags: readonly string[], raw: string, max = MAX_TAGS): TagListResult {
  return addTags(tags, raw.replace(/[,;\n]/g, ' '), max)
}

/** Case-insensitive: a tag stored as "Core" is removable by "core". */
export function removeTag(tags: readonly string[], tag: string): string[] {
  const target = tagKey(tag)
  return tags.filter((t) => tagKey(t) !== target)
}

/** Every distinct tag (case-insensitively) across the list with its usage
 *  count, most used first (ties alphabetical) — the pipeline's filter chips.
 *  The first spelling seen is the one shown. */
export function allTags(deals: readonly Pick<Deal, 'tags'>[]): { tag: string; count: number }[] {
  const counts = new Map<string, { tag: string; count: number }>()
  for (const deal of deals) {
    for (const tag of dealTags(deal)) {
      const key = tagKey(tag)
      const entry = counts.get(key)
      if (entry) entry.count += 1
      else counts.set(key, { tag, count: 1 })
    }
  }
  return [...counts.values()].sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
}

/** AND semantics: a deal passes when it carries EVERY selected tag
 *  (case-insensitively). An empty selection passes everything. */
export function hasAllTags(deal: Pick<Deal, 'tags'>, selected: readonly string[]): boolean {
  if (selected.length === 0) return true
  const own = new Set(dealTags(deal).map(tagKey))
  return selected.every((tag) => own.has(tagKey(tag)))
}

export function filterByTags<T extends Pick<Deal, 'tags'>>(deals: readonly T[], selected: readonly string[]): T[] {
  return deals.filter((deal) => hasAllTags(deal, selected))
}

export function toggleTag(selected: readonly string[], tag: string): string[] {
  const key = tagKey(tag)
  return selected.some((t) => tagKey(t) === key) ? selected.filter((t) => tagKey(t) !== key) : [...selected, tag]
}
