import { describe, expect, it, vi } from 'vitest'
import { createToastStore, errorMessage } from './toast'

describe('createToastStore', () => {
  it('pushes, notifies subscribers, and dismisses by id', () => {
    const store = createToastStore()
    const seen: number[] = []
    store.subscribe((toasts) => seen.push(toasts.length))
    const id = store.push('boom')
    expect(store.getToasts()).toEqual([{ id, kind: 'error', message: 'boom' }])
    store.dismiss(id)
    expect(store.getToasts()).toEqual([])
    expect(seen).toEqual([1, 0])
  })

  it('caps the visible queue at maxVisible, dropping the oldest', () => {
    const store = createToastStore(2)
    store.push('a')
    store.push('b')
    store.push('c')
    expect(store.getToasts().map((t) => t.message)).toEqual(['b', 'c'])
  })

  it('collapses an identical consecutive message', () => {
    const store = createToastStore()
    const first = store.push('same')
    const second = store.push('same')
    expect(second).toBe(first)
    expect(store.getToasts()).toHaveLength(1)
  })

  it('dismissing an unknown id does not notify', () => {
    const store = createToastStore()
    const listener = vi.fn()
    store.subscribe(listener)
    store.dismiss(999)
    expect(listener).not.toHaveBeenCalled()
  })

  it('unsubscribe stops notifications', () => {
    const store = createToastStore()
    const listener = vi.fn()
    const off = store.subscribe(listener)
    off()
    store.push('x')
    expect(listener).not.toHaveBeenCalled()
  })
})

describe('errorMessage', () => {
  it('prefers Error.message, then strings, then the fallback', () => {
    expect(errorMessage(new Error('nope'))).toBe('nope')
    expect(errorMessage('plain')).toBe('plain')
    expect(errorMessage(42, 'fallback')).toBe('fallback')
    expect(errorMessage(new Error(''), 'fallback')).toBe('fallback')
  })
})
