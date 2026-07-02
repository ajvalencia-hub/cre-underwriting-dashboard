import type { FlatField } from './schemaFields'
import type { OutputMetric } from '../types/schema'

export function formatOutputValue(metric: OutputMetric, value: unknown): string {
  if (value === undefined || value === null || value === '') return '—'
  const num = Number(value)
  if (Number.isNaN(num)) return String(value)
  switch (metric.type) {
    case 'percent':
      return `${(num * 100).toFixed(2)}%`
    case 'currency':
      return `$${Math.round(num).toLocaleString()}`
    case 'multiple':
      return `${num.toFixed(2)}x`
    case 'years':
      return `${num.toFixed(1)} yrs`
    case 'number':
      return num.toLocaleString()
    default:
      return String(value)
  }
}

export function formatValue(field: FlatField | undefined, value: unknown): string {
  if (value === undefined || value === null || value === '') return '—'
  if (!field) return String(value)

  switch (field.type) {
    case 'currency':
      return `$${Number(value).toLocaleString()}`
    case 'percent':
      return `${(Number(value) * 100).toFixed(2)}%`
    case 'boolean':
      return value ? 'Yes' : 'No'
    case 'multiselect':
      return Array.isArray(value) ? (value as string[]).join(', ') : String(value)
    case 'table':
      return Array.isArray(value) ? `${value.length} row(s)` : '—'
    case 'keyvalue':
      return Array.isArray(value) ? `${value.length} entr${value.length === 1 ? 'y' : 'ies'}` : '—'
    default:
      return String(value)
  }
}
