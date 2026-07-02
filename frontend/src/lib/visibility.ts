import type { FieldCondition, VisibleWhen } from '../types/schema'

type FormValues = Record<string, unknown>

function matches(condition: FieldCondition, values: FormValues): boolean {
  const value = values[condition.field]
  if (condition.equals !== undefined) {
    return value === condition.equals
  }
  if (condition.contains !== undefined) {
    return Array.isArray(value) && value.includes(condition.contains)
  }
  return true
}

export function isVisible(visibleWhen: VisibleWhen | null | undefined, values: FormValues): boolean {
  if (!visibleWhen) return true
  if (visibleWhen.all && !visibleWhen.all.every((c) => matches(c, values))) return false
  if (visibleWhen.any && !visibleWhen.any.some((c) => matches(c, values))) return false
  return true
}
