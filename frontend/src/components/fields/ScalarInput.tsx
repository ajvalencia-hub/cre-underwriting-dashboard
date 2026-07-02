import { useState } from 'react'
import type { FieldType } from '../../types/schema'

interface ScalarInputProps {
  type: FieldType
  value: unknown
  onChange: (value: unknown) => void
  options?: string[]
  min?: number
  max?: number
  step?: number
}

const baseClass = 'w-full rounded border px-2 py-1 text-sm'

// Percent fields are typed/displayed as whole percents (e.g. "6") while the
// underlying value stays a fraction (0.06).
function toEditScale(value: number, type: FieldType): number {
  return type === 'percent' ? value * 100 : value
}
function fromEditScale(value: number, type: FieldType): number {
  return type === 'percent' ? value / 100 : value
}

function formatNumeric(value: number, type: FieldType): string {
  if (type === 'currency') return Math.round(value).toLocaleString()
  return String(Math.round(value * 1e6) / 1e6)
}

function NumericInput({ type, value, onChange, options: _options, min, max, step }: ScalarInputProps) {
  const [focused, setFocused] = useState(false)
  const [draft, setDraft] = useState('')

  const numValue = value === undefined || value === null || value === '' ? null : Number(value)
  const rangeError =
    numValue !== null && min !== undefined && numValue < min
      ? `Min ${type === 'percent' ? `${(min * 100).toFixed(2)}%` : min.toLocaleString()}`
      : numValue !== null && max !== undefined && numValue > max
        ? `Max ${type === 'percent' ? `${(max * 100).toFixed(2)}%` : max.toLocaleString()}`
        : null

  function commit(raw: string) {
    if (raw.trim() === '') {
      onChange(undefined)
      return
    }
    const parsed = Number(raw.replace(/,/g, ''))
    if (!Number.isFinite(parsed)) return
    // Convert to value-scale (fraction, for percent) before clamping — min/max
    // are always expressed in value-scale, but `parsed` is still edit-scale.
    let next = fromEditScale(parsed, type)
    if (min !== undefined) next = Math.max(min, next)
    if (max !== undefined) next = Math.min(max, next)
    onChange(next)
  }

  function handleFocus() {
    setFocused(true)
    setDraft(numValue === null ? '' : String(toEditScale(numValue, type)))
  }

  function handleBlur(e: React.FocusEvent<HTMLInputElement>) {
    // Read the DOM's live value directly rather than the `draft` state — if a
    // blur follows an input event in rapid succession (programmatic fills,
    // very fast typing), React's batching can invoke this closure before it
    // captures the just-set draft, committing a stale value otherwise.
    setFocused(false)
    commit(e.target.value)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      commit(e.currentTarget.value)
      return
    }
    if (!step || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return
    e.preventDefault()
    const editStep = toEditScale(step, type)
    const current = focused
      ? Number(draft.replace(/,/g, '')) || 0
      : numValue === null
        ? 0
        : toEditScale(numValue, type)
    const next = current + (e.key === 'ArrowUp' ? editStep : -editStep)
    setDraft(String(Math.round(next * 1e6) / 1e6))
    commit(String(next))
  }

  const displayValue = focused
    ? draft
    : numValue === null
      ? ''
      : formatNumeric(toEditScale(numValue, type), type)

  return (
    <div>
      <div className="flex items-center gap-1">
        {type === 'currency' && <span className="text-slate-400">$</span>}
        <input
          type="text"
          inputMode="decimal"
          className={`${baseClass} text-right ${rangeError ? 'border-red-300' : 'border-slate-300'}`}
          value={displayValue}
          onFocus={handleFocus}
          onBlur={handleBlur}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        {type === 'percent' && <span className="text-slate-400">%</span>}
      </div>
      {rangeError && <div className="mt-0.5 text-[11px] text-red-500">{rangeError}</div>}
    </div>
  )
}

export default function ScalarInput({ type, value, onChange, options, min, max, step }: ScalarInputProps) {
  switch (type) {
    case 'text':
      return (
        <input
          type="text"
          className={baseClass + ' border-slate-300'}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )
    case 'number':
    case 'currency':
    case 'percent':
      return (
        <NumericInput type={type} value={value} onChange={onChange} options={options} min={min} max={max} step={step} />
      )
    case 'date':
      return (
        <input
          type="date"
          className={baseClass + ' border-slate-300'}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )
    case 'select':
      return (
        <select
          className={baseClass + ' border-slate-300'}
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
