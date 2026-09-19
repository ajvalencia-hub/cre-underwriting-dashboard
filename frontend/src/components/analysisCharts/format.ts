// Chart formatters built on the app's own number formatting (money.ts), so
// chart tooltips and tables read like the rest of the app.
import { formatMoney, formatMoneyCompact } from '../../lib/money'

export const money = (v: number) => formatMoney(v)
export const moneyCompact = (v: number) => formatMoneyCompact(v)
export const pct = (digits = 2) => (v: number) => `${(v * 100).toFixed(digits)}%`
export const pct2 = pct(2)
export const pct1 = pct(1)
export const pct0 = pct(0)
export const mult = (v: number) => `${v.toFixed(2)}x`
export const count = (v: number) => Math.round(v).toLocaleString()
