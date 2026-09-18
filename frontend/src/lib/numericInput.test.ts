import { describe, expect, it } from 'vitest'
import { formatAsTyped, formatNumericDisplay, fractionPercentHint, parseNumericInput } from './numericInput'

const value = (raw: string) => {
  const r = parseNumericInput(raw)
  return r.ok ? r.value : r.reason
}

describe('parseNumericInput', () => {
  it('accepts what analysts type and paste from Excel', () => {
    expect(value('1,250,000')).toBe(1_250_000)
    expect(value('$1,250,000')).toBe(1_250_000)
    expect(value('$12,500,000\n')).toBe(12_500_000) // Excel copy ends with a newline
    expect(value(' 1250000\t')).toBe(1_250_000)
    expect(value('1.25M')).toBe(1_250_000)
    expect(value('12.5k')).toBe(12_500)
    expect(value('2bn')).toBe(2_000_000_000)
    expect(value('5.5%')).toBe(5.5)
    expect(value('(250)')).toBe(-250)
    expect(value('($1,250)')).toBe(-1250)
    expect(value('-500')).toBe(-500)
    expect(value('-$500')).toBe(-500)
    expect(value('1e6')).toBe(1_000_000)
    expect(value('1 250 000')).toBe(1_250_000)
    expect(value('.5')).toBe(0.5)
  })

  it('rejects with a reason instead of silently reverting', () => {
    expect(value('abc')).toMatch(/isn't a number/)
    expect(value('100\t200')).toMatch(/several cells/)
    expect(parseNumericInput('')).toEqual({ ok: false, reason: 'empty' })
    expect(parseNumericInput('5.5%')).toMatchObject({ ok: true, hadPercentSign: true })
  })
})

describe('fractionPercentHint', () => {
  it('flags 0.055 typed into a percent field, not 5.5 or 0.055%', () => {
    expect(fractionPercentHint(0.055, false)).toMatch(/5\.5/)
    expect(fractionPercentHint(5.5, false)).toBeNull()
    expect(fractionPercentHint(0.055, true)).toBeNull()
    expect(fractionPercentHint(0.5, false)).toBeNull()
  })
})

describe('formatNumericDisplay', () => {
  it('keeps cents on currency and groups large numbers', () => {
    expect(formatNumericDisplay(32.5, 'currency')).toBe('32.50')
    expect(formatNumericDisplay(0.25, 'currency')).toBe('0.25')
    expect(formatNumericDisplay(12_500_000, 'currency')).toBe('12,500,000')
    expect(formatNumericDisplay(5.5, 'percent')).toBe('5.5')
    expect(formatNumericDisplay(125000, 'number')).toBe('125,000')
    expect(formatNumericDisplay(30, 'number')).toBe('30')
  })
})

describe('formatAsTyped', () => {
  it('inserts separators and keeps the caret after the same digit', () => {
    expect(formatAsTyped('1250000', 7)).toEqual({ text: '1,250,000', caret: 9 })
    expect(formatAsTyped('1,2500', 6)).toEqual({ text: '12,500', caret: 6 })
    expect(formatAsTyped('1250000', 1)).toEqual({ text: '1,250,000', caret: 1 })
    expect(formatAsTyped('1250.5', 6)).toEqual({ text: '1,250.5', caret: 7 })
    expect(formatAsTyped('1.2M', 4)).toEqual({ text: '1.2M', caret: 4 })
  })
})
