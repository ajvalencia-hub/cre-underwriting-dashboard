// Deal tags (wave 2): pure helpers behind the header chip row, the pipeline
// tag filter and the bulk add/remove actions. Tags are free text, trimmed,
// whitespace-collapsed and lower-cased so "Core" and "core " are one tag;
// the backend stores whatever it is sent, so normalisation lives here.

import type { Deal } from '../types/deal'

export const MAX_TAGS = 20
export const MAX_TAG_LENGTH = 40

export function normalizeTag(raw: string): string {
  return raw.trim().replace(/\s+/g, ' ').toLowerCase().slice(0, MAX_TAG_LENGTH)
}

export function dealTags(deal: Pick<Deal, 'tags'>): string[] {
  return Array.isArray(deal.tags) ? deal.tags : []
}

export type AddTagResult = { ok: true; tags: string[] } | { ok: false; error: string }

/** Append a tag; rejects blanks, duplicates and the 21st tag. */
export function addTag(tags: readonly string[], raw: string, max = MAX_TAGS): AddTagResult {
  const tag = normalizeTag(raw)
  if (!tag) return { ok: false, error: 'Enter a tag first.' }
  if (tags.includes(tag)) return { ok: false, error: `Already tagged "${tag}".` }
  if (tags.length >= max) return { ok: false, error: `A deal can carry at most ${max} tags.` }
  return { ok: true, tags: [...tags, tag] }
}

/** Case-insensitive: the backend keeps the first spelling it saw, so a tag
 *  imported as "Core" must still be removable by "core". */
export function removeTag(tags: readonly string[], tag: string): string[] {
  const target = normalizeTag(tag)
  return tags.filter((t) => normalizeTag(t) !== target)
}

/** Every distinct tag across the list with its usage count, most used first
 *  (ties alphabetical) — the pipeline's filter chips. */
export function allTags(deals: readonly Pick<Deal, 'tags'>[]): { tag: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const deal of deals) {
    for (const tag of dealTags(deal)) counts.set(tag, (counts.get(tag) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
}

/** AND semantics: a deal passes when it carries EVERY selected tag. An
 *  empty selection passes everything. */
export function hasAllTags(deal: Pick<Deal, 'tags'>, selected: readonly string[]): boolean {
  if (selected.length === 0) return true
  const own = new Set(dealTags(deal).map(normalizeTag))
  return selected.every((tag) => own.has(normalizeTag(tag)))
}

export function filterByTags<T extends Pick<Deal, 'tags'>>(deals: readonly T[], selected: readonly string[]): T[] {
  return deals.filter((deal) => hasAllTags(deal, selected))
}

export function toggleTag(selected: readonly string[], tag: string): string[] {
  return selected.includes(tag) ? selected.filter((t) => t !== tag) : [...selected, tag]
}
