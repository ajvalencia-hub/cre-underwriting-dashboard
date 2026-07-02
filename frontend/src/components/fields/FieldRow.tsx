import type { InputField } from '../../types/schema'
import { validateField } from '../../lib/validateField'
import KeyValueField from './KeyValueField'
import ScalarInput from './ScalarInput'
import TableField from './TableField'

interface FieldRowProps {
  field: InputField
  value: unknown
  onChange: (value: unknown) => void
}

export default function FieldRow({ field, value, onChange }: FieldRowProps) {
  const error = validateField(field, value)
  const isWide = field.type === 'table' || field.type === 'keyvalue' || field.type === 'multiselect'

  return (
    <div className="py-2">
      <label className="block text-xs font-medium text-slate-600">
        {field.label}
        {field.required && <span className="text-red-400"> *</span>}
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
          <ScalarInput type={field.type} value={value} options={field.options} onChange={onChange} />
        )}
      </div>
      {error && <div className="mt-0.5 text-xs text-red-500">{error}</div>}
    </div>
  )
}
