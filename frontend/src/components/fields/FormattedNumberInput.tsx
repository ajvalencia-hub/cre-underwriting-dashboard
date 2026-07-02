import { useState } from 'react'

type NumberFormat = 'currency' | 'percent' | 'number'

interface FormattedNumberInputProps {
  value: number
  onChange: (value: number) => void
  format: NumberFormat
  min?: number
  max?: number
  step: number
  decimals?: number
}

// Editing scale: percent fields are typed/displayed as whole percents (e.g. "6")
// while the underlying value stays a fraction (0.06), matching ScalarInput's convention.
function toEditScale(value: number, format: NumberFormat): number {
  return format === 'percent' ? value * 100 : value
}
function fromEditScale(value: number, format: NumberFormat): number {
  return format === 'percent' ? value / 100 : value
}

function formatDisplay(value: number, format: NumberFormat, decimals: number): string {
  switch (format) {
    case 'currency':
      return `$${Math.round(value).toLocaleString()}`
    case 'percent':
      return `${(value * 100).toFixed(decimals)}%`
    default:
      return value.toLocaleString()
  }
}

export default function FormattedNumberInput({
  value,
  onChange,
  format,
  min,
  max,
  step,
  decimals = 2,
}: FormattedNumberInputProps) {
  const [focused, setFocused] = useState(false)
  const [draft, setDraft] = useState('')

  const error =
    min !== undefined && value < min
      ? `Min ${formatDisplay(min, format, decimals)}`
      : max !== undefined && value > max
        ? `Max ${formatDisplay(max, format, decimals)}`
        : null

  function commit(raw: number) {
    let next = raw
    if (min !== undefined) next = Math.max(min, next)
    if (max !== undefined) next = Math.min(max, next)
    onChange(fromEditScale(next, format))
  }

  function handleFocus() {
    setFocused(true)
    setDraft(String(Math.round(toEditScale(value, format) * 1e6) / 1e6))
  }

  function handleBlur() {
    setFocused(false)
    const parsed = Number(draft.replace(/,/g, ''))
    if (Number.isFinite(parsed)) commit(parsed)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
    e.preventDefault()
    const editStep = toEditScale(step, format)
    const current = focused ? Number(draft.replace(/,/g, '')) || 0 : toEditScale(value, format)
    const next = current + (e.key === 'ArrowUp' ? editStep : -editStep)
    setDraft(String(Math.round(next * 1e6) / 1e6))
    commit(next)
  }

  const displayValue = focused
    ? draft
    : format === 'currency'
      ? Math.round(value).toLocaleString()
      : String(Math.round(toEditScale(value, format) * 1e6) / 1e6)

  return (
    <div>
      <div className="flex items-center gap-1">
        {format === 'currency' && <span className="text-slate-400">$</span>}
        <input
          type="text"
          inputMode="decimal"
          className={`w-full rounded border px-2 py-1 text-right text-sm ${
            error ? 'border-red-300' : 'border-slate-300'
          }`}
          value={displayValue}
          onFocus={handleFocus}
          onBlur={handleBlur}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        {format === 'percent' && <span className="text-slate-400">%</span>}
      </div>
      {error && <div className="mt-0.5 text-[11px] text-red-500">{error}</div>}
    </div>
  )
}
