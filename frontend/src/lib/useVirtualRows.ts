// Dependency-free row virtualization (H13): windows a long list against a
// scroll container so a 10,000-row comps import renders ~40 <tr>s. The
// window math is pure (exported for unit tests); the hook wires it to
// scroll events.

import { useCallback, useState } from 'react'

export interface VirtualWindow {
  start: number
  end: number // exclusive
  padTop: number
  padBottom: number
}

export function computeWindow(
  total: number,
  rowHeight: number,
  scrollTop: number,
  viewportHeight: number,
  overscan = 8,
): VirtualWindow {
  if (total <= 0 || rowHeight <= 0) {
    return { start: 0, end: 0, padTop: 0, padBottom: 0 }
  }
  const first = Math.floor(scrollTop / rowHeight)
  const visible = Math.ceil(viewportHeight / rowHeight)
  const start = Math.max(0, first - overscan)
  const end = Math.min(total, first + visible + overscan)
  return {
    start,
    end,
    padTop: start * rowHeight,
    padBottom: (total - end) * rowHeight,
  }
}

/** Threshold below which virtualization is skipped entirely — windowing a
 *  short list adds scroll-jank for nothing. */
export const VIRTUALIZE_THRESHOLD = 150

export function useVirtualRows(total: number, rowHeight: number, viewportHeight: number) {
  const [scrollTop, setScrollTop] = useState(0)
  const onScroll = useCallback(
    (e: { currentTarget: { scrollTop: number } }) => setScrollTop(e.currentTarget.scrollTop),
    [],
  )
  const active = total > VIRTUALIZE_THRESHOLD
  const window = active
    ? computeWindow(total, rowHeight, scrollTop, viewportHeight)
    : { start: 0, end: total, padTop: 0, padBottom: 0 }
  return { window, onScroll, active }
}
