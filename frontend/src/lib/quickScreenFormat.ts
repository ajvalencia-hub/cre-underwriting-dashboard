// Display-only formatting helpers shared across the Quick Screen panel, the
// sensitivity grid, and the summary sidebar. No math lives here.

export function formatMoney(value: number): string {
  return `$${Math.round(value).toLocaleString()}`
}

export function formatMoneyCompact(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `$${Math.round(value / 1_000)}k`
  return `$${Math.round(value)}`
}

export function formatPct(value: number, decimals = 2): string {
  return `${(value * 100).toFixed(decimals)}%`
}

export function formatBps(value: number): string {
  return `${value.toFixed(0)} bps`
}
