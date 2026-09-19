import { seriesColor } from './color'
import type { LegendItem } from './types'

function Swatch({ item }: { item: LegendItem }) {
  const color = item.color ?? (item.slot ? seriesColor(item.slot) : 'var(--viz-deemphasis)')
  if (item.shape === 'line') {
    return (
      <svg width={14} height={8} aria-hidden="true" className="shrink-0">
        <line x1={1} y1={4} x2={13} y2={4} strokeWidth={2} strokeLinecap="round" style={{ stroke: color }} />
      </svg>
    )
  }
  if (item.shape === 'dot') {
    return (
      <svg width={10} height={10} aria-hidden="true" className="shrink-0">
        <circle cx={5} cy={5} r={4} style={{ fill: color }} />
      </svg>
    )
  }
  return (
    <svg width={10} height={10} aria-hidden="true" className="shrink-0">
      <rect x={0} y={0} width={10} height={10} rx={2} style={{ fill: color }} />
    </svg>
  )
}

/** Series key: the swatch mirrors the mark (line / rect / dot); the label is
 *  in a text token, never the series color. Charts pass it for ≥2 series only. */
export function Legend({ items, className = '' }: { items: LegendItem[]; className?: string }) {
  if (items.length === 0) return null
  return (
    <ul className={`m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs text-viz-secondary ${className}`}>
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <Swatch item={item} />
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  )
}
