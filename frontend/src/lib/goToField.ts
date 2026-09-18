// Bring a form field into view from anywhere (compute errors, checklists):
// opens its collapsed section, scrolls to it, focuses the input and
// briefly highlights the row.

const HIGHLIGHT_MS = 2400

export function fieldDomId(fieldId: string): string {
  return `field-${fieldId}`
}

/** Engine messages sometimes append a hint: "grossPotentialRent (or a unitMix …)". */
export function fieldIdFromMissing(entry: string): string {
  return entry.match(/^[A-Za-z0-9_]+/)?.[0] ?? entry
}

export function openAndScrollTo(element: HTMLElement | null): boolean {
  if (!element) return false
  let parent = element.parentElement
  while (parent) {
    if (parent instanceof HTMLDetailsElement) parent.open = true
    parent = parent.parentElement
  }
  element.scrollIntoView({ behavior: 'smooth', block: 'center' })
  return true
}

export function goToField(fieldId: string): boolean {
  const row = document.getElementById(fieldDomId(fieldId))
  if (!openAndScrollTo(row) || !row) return false
  row.querySelector<HTMLElement>('input, select, textarea')?.focus({ preventScroll: true })
  row.classList.add('bg-amber-50')
  window.setTimeout(() => row.classList.remove('bg-amber-50'), HIGHLIGHT_MS)
  return true
}

/** A number field still showing text that couldn't be read as a number. The
 *  form keeps its previous value, so computing now would silently use that —
 *  bring the field into view instead. */
export function focusUnparsedEntry(): boolean {
  const input = document.querySelector<HTMLInputElement>('input[data-unparsed]')
  if (!openAndScrollTo(input) || !input) return false
  input.focus({ preventScroll: true })
  return true
}
