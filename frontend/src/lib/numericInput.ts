// Parsing and formatting for currency / percent / number fields — built for
// values typed quickly or pasted from Excel: "$12,500,000", "5.50%", "(250)",
// "1.25M", "12.5k", a cell copied with a trailing tab or newline.

export type NumericKind = 'currency' | 'percent' | 'number'

export type ParseResult =
  | { ok: true; value: number; hadPercentSign: boolean }
  | { ok: false; reason: string }

const SUFFIX: Record<string, number> = { k: 1e3, m: 1e6, mm: 1e6, b: 1e9, bn: 1e9 }

/** Returns the number as typed (percent fields: in whole-percent units). */
export function parseNumericInput(raw: string): ParseResult {
  // Excel copies end with a newline; a tab means several cells were copied.
  const text = raw.replace(/[\r\n]+$/, '').trim()
  if (text === '') return { ok: false, reason: 'empty' }
  if (/\t/.test(text) || /\n/.test(text)) {
    return { ok: false, reason: 'That looks like several cells — paste one value at a time.' }
  }
  let s = text.replace(/ /g, ' ')
  let negative = false
  // Accounting negatives: (1,250) or ($1,250)
  const paren = s.match(/^\((.*)\)$/)
  if (paren) {
    negative = true
    s = paren[1].trim()
  }
  if (s.startsWith('-') || s.startsWith('−')) {
    negative = !negative
    s = s.slice(1).trim()
  }
  s = s.replace(/^[$€£]\s*/, '').replace(/^-\s*/, () => {
    negative = !negative
    return ''
  })
  const hadPercentSign = /%\s*$/.test(s)
  if (hadPercentSign) s = s.replace(/%\s*$/, '').trim()
  let multiplier = 1
  const suffix = s.match(/^(.*?)\s*(k|m|mm|b|bn)$/i)
  if (suffix && !hadPercentSign) {
    multiplier = SUFFIX[suffix[2].toLowerCase()]
    s = suffix[1]
  }
  // Thousands separators: commas, or spaces between digit groups.
  s = s.replace(/,/g, '').replace(/(\d)\s+(?=\d{3}\b)/g, '$1')
  if (!/^\d*\.?\d+(e[+-]?\d+)?$/i.test(s) && !/^\d+\.$/.test(s)) {
    return { ok: false, reason: `"${text}" isn't a number — try 1,250,000, 1.25M or 5.5%.` }
  }
  const value = Number(s) * multiplier * (negative ? -1 : 1)
  if (!Number.isFinite(value)) return { ok: false, reason: `"${text}" isn't a number.` }
  return { ok: true, value, hadPercentSign }
}

/**
 * A percent typed as a fraction ("0.055" meaning 5.5%) is the classic 100×
 * error. Values under 0.2 typed without a % sign get a hint — real
 * sub-0.2% inputs are rare, and the hint doesn't change the value.
 */
export function fractionPercentHint(editValue: number, hadPercentSign: boolean): string | null {
  if (hadPercentSign || editValue <= 0 || editValue >= 0.2) return null
  return `That's ${editValue}% — percentages are typed as whole numbers (5.5 for 5.5%). If you meant ${+(editValue * 100).toFixed(6)}%, type ${+(editValue * 100).toFixed(6)}.`
}

function decimalsOf(value: number): number {
  const text = String(value)
  if (/e/i.test(text)) return 6
  return text.includes('.') ? text.split('.')[1].length : 0
}

/** Display format when the field isn't being edited. */
export function formatNumericDisplay(editValue: number, kind: NumericKind): string {
  const rounded = Math.round(editValue * 1e6) / 1e6
  if (kind === 'currency') {
    // Keep cents when there are any: $32.50/SF must not display as "33".
    const cents = Math.abs(rounded - Math.round(rounded)) > 1e-9
    return rounded.toLocaleString('en-US', {
      minimumFractionDigits: cents ? 2 : 0,
      maximumFractionDigits: cents ? Math.max(2, Math.min(4, decimalsOf(rounded))) : 0,
    })
  }
  if (kind === 'number' && Math.abs(rounded) >= 10000) {
    return rounded.toLocaleString('en-US', { maximumFractionDigits: 6 })
  }
  return String(rounded)
}

/**
 * Live thousands separators while typing plain digits into a currency
 * field, keeping the caret after the same digit. Anything that isn't plain
 * digits (e.g. "1.2M", "$", "(") is left alone until the field is left.
 */
export function formatAsTyped(raw: string, caret: number): { text: string; caret: number } {
  if (!/^-?[\d,]*\.?\d*$/.test(raw)) return { text: raw, caret }
  const digitsBeforeCaret = raw.slice(0, caret).replace(/[^\d.-]/g, '').length
  const negative = raw.startsWith('-')
  const unsigned = raw.replace(/[,-]/g, '')
  const [intPart, fracPart] = unsigned.split('.')
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const text = `${negative ? '-' : ''}${grouped}${fracPart !== undefined ? `.${fracPart}` : ''}`
  let seen = 0
  let pos = 0
  while (pos < text.length && seen < digitsBeforeCaret) {
    if (/[\d.-]/.test(text[pos])) seen++
    pos++
  }
  return { text, caret: pos }
}
