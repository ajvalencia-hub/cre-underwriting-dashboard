import type { InputField } from '../types/schema'

export function validateField(field: InputField, value: unknown): string | null {
  const isEmpty = value === undefined || value === null || value === ''
  if (field.required && isEmpty) return 'Required'
  if (isEmpty) return null

  if (['number', 'currency', 'percent'].includes(field.type) && typeof value === 'number') {
    if (field.min !== undefined && value < field.min) return `Min ${field.min}`
    if (field.max !== undefined && value > field.max) return `Max ${field.max}`
  }
  return null
}
