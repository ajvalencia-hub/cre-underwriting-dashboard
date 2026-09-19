import type { InputField } from '../types/schema'

/** A bound in the units the user types: 0.25 on a percent field is "25%". */
function formatBound(field: InputField, bound: number): string {
  if (field.type === 'percent') return `${+(bound * 100).toFixed(4)}%`
  if (field.type === 'currency') return `$${bound.toLocaleString('en-US')}`
  return bound.toLocaleString('en-US')
}

export function validateField(field: InputField, value: unknown): string | null {
  const isEmpty = value === undefined || value === null || value === ''
  if (field.required && isEmpty) return 'Required'
  if (isEmpty) return null

  // 0 switches some constraints off (e.g. the DSCR sizing floor) — valid.
  if (value === 0 && field.zeroDisables) return null
  if (['number', 'currency', 'percent'].includes(field.type) && typeof value === 'number') {
    if (field.min !== undefined && value < field.min) return `Min ${formatBound(field, field.min)}`
    if (field.max !== undefined && value > field.max) return `Max ${formatBound(field, field.max)}`
  }
  return null
}
