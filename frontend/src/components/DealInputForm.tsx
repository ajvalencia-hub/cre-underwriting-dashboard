import FieldRow from './fields/FieldRow'
import MarketContextPanel from './MarketContextPanel'
import { isVisible } from '../lib/visibility'
import type { InputSchema } from '../types/schema'

interface DealInputFormProps {
  schema: InputSchema
  values: Record<string, unknown>
  onFieldChange: (fieldId: string, value: unknown) => void
}

export default function DealInputForm({ schema, values, onFieldChange }: DealInputFormProps) {
  const visibleSections = schema.sections.filter((s) => isVisible(s.visibleWhen, values))

  return (
    <div className="max-w-3xl space-y-4 pb-16">
      <MarketContextPanel
        market={typeof values.market === 'string' ? values.market : ''}
        submarket={typeof values.submarket === 'string' ? values.submarket : ''}
        assetClass={typeof values.propertyType === 'string' ? values.propertyType : ''}
      />

      {visibleSections.map((section) => (
        <details
          key={section.id}
          id={`section-${section.id}`}
          open
          className="rounded border border-slate-200 bg-white"
        >
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-semibold text-slate-700">
            {section.label}
          </summary>
          <div className="divide-y divide-slate-50 px-3 pb-2">
            {section.fields
              .filter((f) => isVisible(f.visibleWhen, values))
              .map((field) => (
                <FieldRow
                  key={field.id}
                  field={field}
                  value={values[field.id]}
                  onChange={(v) => onFieldChange(field.id, v)}
                />
              ))}
          </div>
        </details>
      ))}
    </div>
  )
}
