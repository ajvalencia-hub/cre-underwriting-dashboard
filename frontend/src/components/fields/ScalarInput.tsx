import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  formatAsTyped,
  formatNumericDisplay,
  fractionPercentHint,
  parseNumericInput,
  type NumericKind,
} from '../../lib/numericInput'
import type { FieldType } from '../../types/schema'

interface ScalarInputProps {
  /** DOM id so a <label htmlFor> can point at the control. */
  id?: string
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

function kindOf(type: FieldType): NumericKind {
  return type === 'currency' ? 'currency' : type === 'percent' ? 'percent' : 'number'
}

function describeBound(value: number, type: FieldType): string {
  return type === 'percent' ? `${+(value * 100).toFixed(4)}%` : value.toLocaleString('en-US')
}

function NumericInput({ id, type, value, onChange, options: _options, min, max, step }: ScalarInputProps) {
  const [focused, setFocused] = useState(false)
  const [draft, setDraft] = useState('')
  // Text that couldn't be read as a number stays visible (with the reason)
  // instead of silently reverting to the previous value.
  const [invalid, setInvalid] = useState<string | null>(null)
  // Something the user should know about the value just committed: it was
  // limited to the allowed range, or looks like a fraction typed as a percent.
  const [note, setNote] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const pendingCaret = useRef<number | null>(null)

  // The value this field last wrote. Any other change to `value` came from
  // outside (deal switch, preset, History restore), so a leftover unreadable
  // entry or note no longer describes it — show the new value instead.
  const ownValue = useRef<unknown>(value)
  useEffect(() => {
    if (Object.is(value, ownValue.current)) return
    ownValue.current = value
    setInvalid(null)
    setNote(null)
  }, [value])

  useLayoutEffect(() => {
    if (pendingCaret.current !== null && inputRef.current) {
      inputRef.current.setSelectionRange(pendingCaret.current, pendingCaret.current)
      pendingCaret.current = null
    }
  })

  const numValue = value === undefined || value === null || value === '' ? null : Number(value)
  const rangeError =
    numValue !== null && min !== undefined && numValue < min
      ? `Min ${describeBound(min, type)}`
      : numValue !== null && max !== undefined && numValue > max
        ? `Max ${describeBound(max, type)}`
        : null

  function commit(raw: string) {
    const parsed = parseNumericInput(raw)
    if (!parsed.ok) {
      if (parsed.reason === 'empty') {
        setInvalid(null)
        setNote(null)
        ownValue.current = undefined
        onChange(undefined)
      } else {
        setInvalid(parsed.reason)
        setDraft(raw)
      }
      return
    }
    setInvalid(null)
    // Convert to value-scale (fraction, for percent) before clamping — min/max
    // are always expressed in value-scale, but `parsed` is still edit-scale.
    const typed = fromEditScale(parsed.value, type)
    let next = typed
    if (min !== undefined) next = Math.max(min, next)
    if (max !== undefined) next = Math.min(max, next)
    if (next !== typed) {
      setNote(
        `You entered ${describeBound(typed, type)}; the allowed range is ` +
          `${min !== undefined ? describeBound(min, type) : '…'}–${max !== undefined ? describeBound(max, type) : '…'}, ` +
          `so ${describeBound(next, type)} is used.`,
      )
    } else {
      setNote(type === 'percent' ? fractionPercentHint(parsed.value, parsed.hadPercentSign) : null)
    }
    ownValue.current = next
    onChange(next)
  }

  function handleFocus() {
    setFocused(true)
    if (invalid === null) {
      setDraft(numValue === null ? '' : formatNumericDisplay(toEditScale(numValue, type), kindOf(type)))
    }
  }

  function handleBlur(e: React.FocusEvent<HTMLInputElement>) {
    // Read the DOM's live value directly rather than the `draft` state — if a
    // blur follows an input event in rapid succession (programmatic fills,
    // very fast typing), React's batching can invoke this closure before it
    // captures the just-set draft, committing a stale value otherwise.
    setFocused(false)
    commit(e.target.value)
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (type === 'currency') {
      const { text, caret } = formatAsTyped(e.target.value, e.target.selectionStart ?? e.target.value.length)
      pendingCaret.current = caret
      setDraft(text)
    } else {
      setDraft(e.target.value)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      commit(e.currentTarget.value)
      return
    }
    if (!step || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return
    e.preventDefault()
    const editStep = toEditScale(step, type)
    // An empty/unparseable draft steps from the field's committed value, not
    // from 0 (audit L5) — clearing a "5.5%" cap rate and tapping ArrowUp
    // should land on 5.75, not 0.25.
    const draftParsed = parseNumericInput(draft)
    const committed = numValue === null ? 0 : toEditScale(numValue, type)
    const current = focused && draftParsed.ok ? draftParsed.value : committed
    const next = current + (e.key === 'ArrowUp' ? editStep : -editStep)
    setDraft(String(Math.round(next * 1e6) / 1e6))
    commit(String(next))
  }

  const displayValue =
    focused || invalid !== null
      ? draft
      : numValue === null
        ? ''
        : formatNumericDisplay(toEditScale(numValue, type), kindOf(type))

  const message = invalid ?? rangeError
  return (
    <div>
      <div className="flex items-center gap-1">
        {type === 'currency' && <span className="text-slate-400">$</span>}
        <input
          id={id}
          ref={inputRef}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          aria-invalid={message ? true : undefined}
          data-unparsed={invalid !== null ? '' : undefined}
          className={`${baseClass} text-right tabular-nums ${message ? 'border-red-300' : 'border-slate-300'}`}
          value={displayValue}
          onFocus={handleFocus}
          onBlur={handleBlur}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
        />
        {type === 'percent' && <span className="text-slate-400">%</span>}
      </div>
      {message && <div className="mt-0.5 text-[11px] text-red-500">{message}</div>}
      {!message && note && <div className="mt-0.5 text-[11px] text-amber-600">{note}</div>}
    </div>
  )
}

export default function ScalarInput({ id, type, value, onChange, options, min, max, step }: ScalarInputProps) {
  switch (type) {
    case 'text':
      return (
        <input
          id={id}
          type="text"
          className={baseClass + ' border-slate-300'}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )
    case 'textarea':
      return (
        <textarea
          id={id}
          rows={3}
          className={baseClass + ' border-slate-300'}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )
    case 'number':
    case 'currency':
    case 'percent':
      return (
        <NumericInput id={id} type={type} value={value} onChange={onChange} options={options} min={min} max={max} step={step} />
      )
    case 'date':
      return (
        <input
          id={id}
          type="date"
          className={baseClass + ' border-slate-300'}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )
    case 'select':
      return (
        <select
          id={id}
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
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
      )
    default:
      return null
  }
}
