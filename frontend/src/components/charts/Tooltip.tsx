import { useLayoutEffect, useRef, useState } from 'react'
import { placeTooltip } from '../../lib/chartLayout'
import type { TooltipContentData } from './types'

/** Hover/focus readout, positioned inside the chart's own box (so a
 *  scrolling card never clips it). Values lead (strong), labels follow; each
 *  row is keyed with a short stroke of the series color. aria-hidden: the
 *  plot's live region announces the same text for keyboard users. */
export function Tooltip({
  anchor,
  box,
  content,
}: {
  anchor: { x: number; y: number }
  box: { width: number; height: number }
  content: TooltipContentData
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<{ width: number; height: number } | null>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const width = el.offsetWidth
    const height = el.offsetHeight
    setSize((s) => (s && s.width === width && s.height === height ? s : { width, height }))
    // Re-measure whenever the content or the box it wraps within changes.
  }, [content, box.width])
  const pos = size ? placeTooltip(anchor, size, box) : { left: 0, top: 0 }
  return (
    <div
      ref={ref}
      aria-hidden="true"
      className="viz-tooltip pointer-events-none absolute z-10 rounded px-2 py-1.5 text-xs"
      style={{ left: pos.left, top: pos.top, visibility: size ? 'visible' : 'hidden', maxWidth: Math.max(140, box.width) }}
    >
      {content.title && <div className="mb-0.5 text-[11px] text-viz-muted">{content.title}</div>}
      {content.rows.map((row) => (
        <div key={row.key} className="flex items-center gap-1.5 whitespace-nowrap leading-5">
          {row.color && (
            <svg width={12} height={4} aria-hidden="true" className="shrink-0">
              <line x1={1} y1={2} x2={11} y2={2} strokeWidth={2} strokeLinecap="round" style={{ stroke: row.color }} />
            </svg>
          )}
          <span className="viz-tabular font-semibold text-viz-primary">{row.value}</span>
          <span className="text-viz-secondary">{row.label}</span>
        </div>
      ))}
    </div>
  )
}
