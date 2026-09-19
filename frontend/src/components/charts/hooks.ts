import { useCallback, useLayoutEffect, useState, type KeyboardEvent } from 'react'
import { stepIndex } from '../../lib/chartLayout'

/** Width of an element, tracked with ResizeObserver (WebView2 / WKWebView
 *  both support it). Returns a callback ref, so it re-attaches when the
 *  element mounts late (e.g. after an empty state). Starts at `fallback` so
 *  the first paint (and SSR/tests) still lays out. */
export function useElementWidth<T extends HTMLElement>(fallback = 560) {
  const [el, setEl] = useState<T | null>(null)
  const [width, setWidth] = useState(fallback)
  useLayoutEffect(() => {
    if (!el) return
    const read = () => {
      const w = Math.floor(el.clientWidth)
      if (w > 0) setWidth(w)
    }
    read()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [el])
  return [setEl, width] as const
}

/** Active-mark cursor shared by pointer hover and arrow-key navigation. */
export function useActiveIndex(count: number) {
  const [active, setActive] = useState(-1)
  const [viaKeyboard, setViaKeyboard] = useState(false)
  const safe = active < count ? active : -1

  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      const next = stepIndex(safe, count, e.key)
      if (next === undefined) return
      e.preventDefault()
      setViaKeyboard(true)
      setActive(next)
    },
    [safe, count],
  )
  const hover = useCallback((i: number) => {
    setViaKeyboard(false)
    setActive(i)
  }, [])
  const clear = useCallback(() => setActive(-1), [])
  return { active: safe, viaKeyboard, onKeyDown, hover, clear }
}
