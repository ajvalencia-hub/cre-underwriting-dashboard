import { useEffect, useState } from 'react'

// App.tsx pins its header with `sticky -top-6` (24px scroll before it sticks).
const HEADER_STICKY_TOP = -24

/** Pixels the pinned app header covers at the top of the scroll area, kept
 *  current as it wraps/resizes — for anything else that needs to stick
 *  below it. */
export function useHeaderOffset(): number {
  const [offset, setOffset] = useState(0)
  useEffect(() => {
    const header = document.querySelector('[data-app-header]')
    if (!header) return
    const update = () => setOffset(Math.max(0, header.getBoundingClientRect().height + HEADER_STICKY_TOP))
    update()
    const observer = new ResizeObserver(update)
    observer.observe(header)
    return () => observer.disconnect()
  }, [])
  return offset
}
