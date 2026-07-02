import type { FieldType } from '../../types/schema'

interface ScalarInputProps {
  type: FieldType
  value: unknown
  onChange: (value: unknown) => void
  options?: string[]
}

const baseClass = 'w-full rounded border border-slate-300 px-2 py-1 text-sm'

export default function ScalarInput({ type, value, onChange, options }: ScalarInputProps) {
  const numericStr = value === undefined || value === null || value === '' ? '' : String(value)

  switch (type) {
    case 'text':
      return (
        <input
          type="text"
          className={baseClass}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )
    case 'number':
      return (
        <input
          type="number"
          className={baseClass}
          value={numericStr}
          onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
        />
      )
    case 'currency':
      return (
        <div className="flex items-center gap-1">
          <span className="text-slate-400">$</span>
          <input
            type="number"
            step="any"
            className={baseClass}
            value={numericStr}
            onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
          />
        </div>
      )
    case 'percent':
      return (
        <div className="flex items-center gap-1">
          <input
            type="number"
            step="any"
            className={baseClass}
            value={value === undefined || value === null || value === '' ? '' : String(Number(value) * 100)}
            onChange={(e) =>
              onChange(e.target.value === '' ? undefined : Number(e.target.value) / 100)
            }
          />
          <span className="text-slate-400">%</span>
        </div>
      )
    case 'date':
      return (
        <input
          type="date"
          className={baseClass}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )
    case 'select':
      return (
        <select
          className={baseClass}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="" disabled>
            Select…
          </option>
          {options?.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      )
    case 'boolean':
      return (
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
      )
    default:
      return null
  }
}
