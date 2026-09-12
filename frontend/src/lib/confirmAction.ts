/** Single choke point for destructive-action confirmation (F7). Today it is
 *  window.confirm; swapping in a modal later means changing one function. */
export function confirmAction(message: string): boolean {
  if (typeof window === 'undefined' || typeof window.confirm !== 'function') return true
  return window.confirm(message)
}
