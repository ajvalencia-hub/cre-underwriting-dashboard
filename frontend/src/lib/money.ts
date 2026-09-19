// Dollar amounts, sign first: -$2,116,364 (it used to render "$-2,116,364",
// easy to misread and not something Excel parses as currency).

export function formatMoney(value: number, { round = true }: { round?: boolean } = {}): string {
  const abs = Math.abs(round ? Math.round(value) : value)
  const sign = value < 0 && abs !== 0 ? '-' : ''
  return `${sign}$${abs.toLocaleString()}`
}

/** $1.2M / $350k / $900, same sign rule. */
export function formatMoneyCompact(value: number): string {
  const abs = Math.abs(value)
  const sign = value < 0 && Math.round(abs) !== 0 ? '-' : ''
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${sign}$${Math.round(abs / 1_000)}k`
  return `${sign}$${Math.round(abs)}`
}

/** Prefix a pre-formatted amount (e.g. "1,234.50" or "-1,234.50") with $. */
export function withDollar(text: string): string {
  return text.startsWith('-') ? `-$${text.slice(1)}` : `$${text}`
}
