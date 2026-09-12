// Stable DOM ids for form controls (accessibility, wave 2): labels bind to
// their inputs via htmlFor/id derived from the schema field id, so screen
// readers announce the label and clicking it focuses the control.

/** `${prefix}-${slug}`: anything outside [A-Za-z0-9_-] becomes '-'. */
export function fieldInputId(prefix: string, fieldId: string): string {
  const slug = fieldId.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '')
  return `${prefix}-${slug || 'field'}`
}
