export interface StatDelta {
  /** Pre-formatted, signed, vs a named period: "+1.2 pts vs T12". */
  text: string
  direction: 'up' | 'down' | 'flat'
  /** Whether this move is good for the deal (up isn't always good: vacancy, LTV). */
  sentiment?: 'good' | 'bad' | 'neutral'
}

export interface StatTileProps {
  /** Sentence case, no trailing colon. */
  label: string
  /** Pre-formatted with the app's formatters ($4.2M, 14.8%, 1.31x). */
  value: string
  delta?: StatDelta
  /** One short line of context under the value. */
  hint?: string
  /** The one number the view leads with (≥48px). Exactly one per view. */
  hero?: boolean
}

const ICON = { up: '▲', down: '▼', flat: '▬' } as const
const WORD = { up: 'up', down: 'down', flat: 'unchanged' } as const

/** A number that doesn't need a chart: label, value, optional delta. Status
 *  color on the delta is always paired with an arrow icon + text. */
export function StatTile({ label, value, delta, hint, hero = false }: StatTileProps) {
  const tone =
    delta?.sentiment === 'good' ? 'var(--viz-delta-good)' : delta?.sentiment === 'bad' ? 'var(--viz-delta-bad)' : 'var(--viz-text-muted)'
  return (
    <div className="min-w-0">
      <div className="text-xs text-viz-muted">{label}</div>
      <div className={`${hero ? 'text-5xl' : 'text-2xl'} mt-0.5 font-semibold leading-tight text-viz-primary`}>{value}</div>
      {delta && (
        <div className="mt-0.5 flex items-center gap-1 text-xs" style={{ color: tone }}>
          <span aria-hidden="true" className="text-[9px]">
            {ICON[delta.direction]}
          </span>
          <span className="sr-only">{WORD[delta.direction]}</span>
          <span>{delta.text}</span>
        </div>
      )}
      {hint && <div className="mt-0.5 text-xs text-viz-muted">{hint}</div>}
    </div>
  )
}

/** A KPI row of stat tiles (wraps on narrow widths). */
export function StatTileRow({ tiles, className = '' }: { tiles: (StatTileProps & { key?: string })[]; className?: string }) {
  if (tiles.length === 0) return null
  return (
    <div className={`grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-x-6 gap-y-3 ${className}`}>
      {tiles.map(({ key, ...t }, i) => (
        <StatTile key={key ?? `${t.label}-${i}`} {...t} />
      ))}
    </div>
  )
}
