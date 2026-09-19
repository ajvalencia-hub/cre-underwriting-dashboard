// Chart formatters for the multi-deal views — thin wrappers over the app's
// money helpers so negative money stays -$1,234 everywhere.
import { formatMoney, formatMoneyCompact } from '../../lib/money'

export const fmtMoney = (v: number) => formatMoney(v)
export const fmtMoneyCompact = (v: number) => formatMoneyCompact(v)
/** Money with cents for small per-SF values ($1.85, $245.10). */
export const fmtMoneyCents = (v: number) =>
  `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
/** Axis ticks: whole percents (steps are 1/2/5 × 10^k, so 5%, 10%…). */
export const fmtPct0 = (v: number) => `${Math.round(v * 100)}%`
export const fmtPct1 = (v: number) => `${(v * 100).toFixed(1)}%`
export const fmtPct2 = (v: number) => `${(v * 100).toFixed(2)}%`
export const fmtMultiple = (v: number) => `${v.toFixed(2)}x`
export const fmtYear = (v: number) => String(Math.round(v))
export const fmtSf = (v: number) => `${Math.round(v).toLocaleString()} SF`

/** The card surface every chart sits on (marks' gaps/rings use --viz-surface). */
export const CARD = 'rounded border border-slate-200 bg-white p-3'
