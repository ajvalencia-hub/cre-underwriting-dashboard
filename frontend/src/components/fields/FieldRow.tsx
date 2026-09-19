import { useState } from 'react'
import type { InputField } from '../../types/schema'
import { fieldDomId } from '../../lib/goToField'
import { validateField } from '../../lib/validateField'
import KeyValueField from './KeyValueField'
import ScalarInput from './ScalarInput'
import TableField from './TableField'

export interface FieldIndicator {
  verdict: 'caution' | 'warning'
  explanation: string
}

interface FieldRowProps {
  field: InputField
  value: unknown
  onChange: (value: unknown) => void
  /** Market-benchmark flag tied to this input — hover for the explanation.
   *  Context only; never blocks or mutates the field. */
  indicator?: FieldIndicator
  /** The section already says all of its fields are template-only. */
  hideTemplateOnlyNote?: boolean
}

const TEMPLATE_ONLY_NOTE = 'Not used by Compute — only written to an Excel template that maps it.'

export default function FieldRow({ field, value, onChange, indicator, hideTemplateOnlyNote }: FieldRowProps) {
  const error = validateField(field, value)
  // "Required" appears once the user has been in the field — not across a
  // brand-new deal before anything was typed. Range errors show at once.
  const [touched, setTouched] = useState(false)
  const shownError = error === 'Required' && !touched ? null : error
  const isWide = field.type === 'table' || field.type === 'keyvalue' || field.type === 'multiselect'
  const isScalar = !isWide
  const inputId = `input-${field.id}`

  return (
    <div id={fieldDomId(field.id)} className="rounded py-2 transition-colors" onBlur={() => setTouched(true)}>
      <label className="block text-xs font-medium text-slate-600" htmlFor={isScalar ? inputId : undefined}>
        {field.label}
        {field.required && <span className="text-red-400"> *</span>}
        {indicator && (
          <span
            title={indicator.explanation}
            className={`ml-1.5 cursor-help ${
              indicator.verdict === 'warning' ? 'text-red-500' : 'text-amber-500'
            }`}
          >
            ⚠
          </span>
        )}
      </label>
      <div className={`mt-1 ${isWide ? '' : 'max-w-xs'}`}>
        {field.type === 'table' && (
          <TableField
            field={field}
            value={(value as Record<string, unknown>[]) ?? []}
            onChange={onChange}
          />
        )}
        {field.type === 'keyvalue' && (
          <KeyValueField
            value={(value as { key: string; value: string }[]) ?? []}
            onChange={onChange}
          />
        )}
        {field.type === 'multiselect' && (
          <div className="flex flex-wrap gap-3">
            {field.options?.map((o) => {
              const selected = Array.isArray(value) && (value as string[]).includes(o)
              return (
                <label key={o} className="flex items-center gap-1 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={(e) => {
                      const arr = Array.isArray(value) ? [...(value as string[])] : []
                      onChange(e.target.checked ? [...arr, o] : arr.filter((x) => x !== o))
                    }}
                  />
                  {o}
                </label>
              )
            })}
          </div>
        )}
        {!['table', 'keyvalue', 'multiselect'].includes(field.type) && (
          <ScalarInput id={inputId} type={field.type} value={value} options={field.options} onChange={onChange} />
        )}
      </div>
      {shownError && <div className="mt-0.5 text-xs text-red-500">{shownError}</div>}
      {/* Without this an analyst reasonably assumes the number feeds the
          built-in results (audit: hotel ADR, draw schedule, loan term...). */}
      {field.templateOnly && !hideTemplateOnlyNote && (
        <div className="mt-0.5 text-xs text-slate-500">{TEMPLATE_ONLY_NOTE}</div>
      )}
    </div>
  )
}
