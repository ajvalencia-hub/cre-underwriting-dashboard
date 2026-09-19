import { useEffect, type RefObject } from 'react'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Keyboard behaviour for a modal dialog: focus moves to its first field on open,
 * Tab / Shift+Tab stay inside, Escape closes, and focus returns to where it
 * was when the dialog closes.
 */
export function useModalFocus(ref: RefObject<HTMLElement | null>, onClose: () => void): void {
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const root = ref.current
    // Start in the first field the user types into, else the first control.
    ;(root?.querySelector<HTMLElement>('input:not([disabled]), select:not([disabled]), textarea:not([disabled])') ??
      root?.querySelector<HTMLElement>(FOCUSABLE))?.focus()

    function onKey(e: KeyboardEvent) {
      if (!root) return
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null)
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      previous?.focus()
    }
    // onClose is read at event time through the closure below; re-running
    // on every render would steal focus back to the first field.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
