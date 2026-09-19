import { isVisible } from './visibility'
import type { InputField, InputSchema } from '../types/schema'

export interface FlatField extends InputField {
  sectionId: string
  sectionLabel: string
}

export function flattenFields(schema: InputSchema): FlatField[] {
  return schema.sections.flatMap((section) =>
    section.fields.map((field) => ({
      ...field,
      sectionId: section.id,
      sectionLabel: section.label,
    })),
  )
}

/** Fields VISIBLE for the given deal values — section and field visibleWhen
 *  both applied. Analysis tools (sensitivity, goal-seek, risk drivers) use
 *  this instead of flattenFields so an acquisition is never offered
 *  landCost, nor a development purchasePrice: sweeping a field the engine
 *  ignores for that deal type produces a silent flat grid. */
export function visibleFields(
  schema: InputSchema,
  values: Record<string, unknown>,
): FlatField[] {
  return schema.sections
    .filter((section) => isVisible(section.visibleWhen, values))
    .flatMap((section) =>
      section.fields
        .filter((field) => isVisible(field.visibleWhen ?? null, values))
        .map((field) => ({
          ...field,
          sectionId: section.id,
          sectionLabel: section.label,
        })),
    )
}

/** Each field's schema default — what a new deal's form holds. */
export function defaultValuesFor(schema: InputSchema): Record<string, unknown> {
  const values: Record<string, unknown> = {}
  for (const field of flattenFields(schema)) {
    if (field.default !== undefined) values[field.id] = field.default
  }
  return values
}
