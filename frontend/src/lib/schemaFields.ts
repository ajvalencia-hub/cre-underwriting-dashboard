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
