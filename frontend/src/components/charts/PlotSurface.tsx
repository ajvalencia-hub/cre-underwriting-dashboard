import type { PointerEvent, ReactNode } from 'react'
import type { useActiveIndex } from './hooks'
import { Tooltip } from './Tooltip'
import type { PlotTip } from './types'

export interface PlotSurfaceProps {
  width: number
  height: number
  /** aria-label for the SVG (role="img"): a one-sentence data summary. */
  summary: string
  /** Number of navigable marks (arrow keys step through them). */
  count: number
  cursor: ReturnType<typeof useActiveIndex>
  /** Plot px -> mark index (or -1). */
  hitTest: (x: number, y: number) => number
  tip: PlotTip | null
  children: ReactNode
}

/** The focusable plot: one tab stop, arrow keys / Home / End step through the
 *  marks, Escape clears; pointer hover uses the chart's hit test. The same
 *  readout shows on hover and focus, and keyboard moves are announced. */
export function PlotSurface({ width, height, summary, count, cursor, hitTest, tip, children }: PlotSurfaceProps) {
  const onPointer = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const i = hitTest(e.clientX - r.left, e.clientY - r.top)
    if (i < 0) cursor.clear()
    else cursor.hover(i)
  }
  return (
    <div
      className="relative select-none outline-offset-2"
      style={{ width: '100%', height }}
      tabIndex={count > 0 ? 0 : -1}
      role="group"
      aria-label="Interactive chart: use the arrow keys to read values"
      onKeyDown={cursor.onKeyDown}
      onPointerMove={onPointer}
      onPointerDown={onPointer}
      onPointerLeave={cursor.clear}
      onBlur={cursor.clear}
    >
      {/* width="100%" + viewBox: the SVG never props its container open (a
          fixed px width would feed back into grid/flex measurement); once
          measured, the viewBox is 1:1 with the box. */}
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={summary}
        className="block overflow-visible"
      >
        {children}
      </svg>
      {tip && <Tooltip anchor={{ x: tip.x, y: tip.y }} box={{ width, height }} content={tip.content} />}
      <div className="sr-only" aria-live="polite">
        {cursor.viaKeyboard && tip ? tip.text : ''}
      </div>
    </div>
  )
}

