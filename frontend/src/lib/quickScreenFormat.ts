// Display-only formatting helpers shared across the Quick Screen panel, the
// sensitivity grid, and the summary sidebar. No math lives here.

export { formatMoney, formatMoneyCompact } from './money'

export function formatPct(value: number, decimals = 2): string {
  return `${(value * 100).toFixed(decimals)}%`
}

export function formatBps(value: number): string {
  return `${value.toFixed(0)} bps`
}
