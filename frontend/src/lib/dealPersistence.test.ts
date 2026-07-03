import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  QUICK_SCREEN_INPUTS_KEY,
  createAutosaver,
  hydrateDealState,
  serializeDealInputs,
} from './dealPersistence'
import { QUICK_SCREEN_DEFAULTS, serializeQuickScreenInputs } from './quickScreenMath'

describe('createAutosaver', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('debounces: rapid schedules produce one save with the last value', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)

    saver.schedule(1)
    await vi.advanceTimersByTimeAsync(1000)
    saver.schedule(2)
    await vi.advanceTimersByTimeAsync(1000)
    expect(save).not.toHaveBeenCalled() // clock restarted at the second schedule

    await vi.advanceTimersByTimeAsync(1000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save).toHaveBeenCalledWith(2)
    expect(saver.getState()).toBe('saved')
  })

  it('walks pending -> saving -> saved', async () => {
    const states: string[] = []
    const saver = createAutosaver<number>(() => Promise.resolve(), 2000)
    saver.subscribe((s) => states.push(s))

    saver.schedule(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(states).toEqual(['pending', 'saving', 'saved'])
  })

  it('a value scheduled mid-save is saved after the in-flight save resolves', async () => {
    let resolveFirst!: () => void
    const save = vi
      .fn<(v: number) => Promise<void>>()
      .mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))
      .mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)

    saver.schedule(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(save).toHaveBeenCalledWith(1)

    saver.schedule(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(save).toHaveBeenCalledTimes(1) // still blocked behind the first save

    resolveFirst()
    await vi.advanceTimersByTimeAsync(0)
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith(2)
  })

  it('keeps the failed value so flush retries it', async () => {
    const save = vi
      .fn<(v: number) => Promise<void>>()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)

    saver.schedule(7)
    await vi.advanceTimersByTimeAsync(2000)
    expect(saver.getState()).toBe('error')

    await saver.flush()
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith(7)
    expect(saver.getState()).toBe('saved')
  })

  it('flush saves immediately without waiting for the debounce', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)

    saver.schedule(3)
    await saver.flush()
    expect(save).toHaveBeenCalledWith(3)

    // The original timer must not double-fire later.
    await vi.advanceTimersByTimeAsync(3000)
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('dispose cancels pending work', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)
    saver.schedule(1)
    saver.dispose()
    await vi.advanceTimersByTimeAsync(3000)
    expect(save).not.toHaveBeenCalled()
  })
})

describe('hydrateDealState', () => {
  const defaults = { dealType: 'acquisition', vacancyPct: 0.05 }

  it('URL quick-screen params win over the stored deal state on first load', () => {
    const url = serializeQuickScreenInputs({ ...QUICK_SCREEN_DEFAULTS, rent: 2500 })
    const hydrated = hydrateDealState(
      defaults,
      { [QUICK_SCREEN_INPUTS_KEY]: { ...QUICK_SCREEN_DEFAULTS, rent: 1600 } },
      url,
    )
    expect(hydrated.quickScreen.rent).toBe(2500)
    expect(hydrated.quickScreenFromUrl).toBe(true)
  })

  it('falls back to the stored quick screen, merged over defaults', () => {
    const hydrated = hydrateDealState(
      defaults,
      { [QUICK_SCREEN_INPUTS_KEY]: { rent: 1600 } }, // partial: saved by an older version
      new URLSearchParams(),
    )
    expect(hydrated.quickScreen.rent).toBe(1600)
    expect(hydrated.quickScreen.quantity).toBe(QUICK_SCREEN_DEFAULTS.quantity)
    expect(hydrated.quickScreenFromUrl).toBe(false)
  })

  it('uses defaults when the deal has no quick screen state', () => {
    const hydrated = hydrateDealState(defaults, {}, new URLSearchParams())
    expect(hydrated.quickScreen).toEqual(QUICK_SCREEN_DEFAULTS)
  })

  it('merges deal fields over schema defaults and strips the quickScreen key', () => {
    const hydrated = hydrateDealState(
      defaults,
      { vacancyPct: 0.08, purchasePrice: 1_000_000, [QUICK_SCREEN_INPUTS_KEY]: {} },
      new URLSearchParams(),
    )
    expect(hydrated.formValues).toEqual({
      dealType: 'acquisition',
      vacancyPct: 0.08,
      purchasePrice: 1_000_000,
    })
    expect(QUICK_SCREEN_INPUTS_KEY in hydrated.formValues).toBe(false)
  })
})

describe('serializeDealInputs', () => {
  it('round-trips through hydrateDealState', () => {
    const quickScreen = { ...QUICK_SCREEN_DEFAULTS, rent: 2100 }
    const blob = serializeDealInputs({ purchasePrice: 5 }, quickScreen)
    const hydrated = hydrateDealState({}, blob, new URLSearchParams())
    expect(hydrated.formValues).toEqual({ purchasePrice: 5 })
    expect(hydrated.quickScreen).toEqual(quickScreen)
  })
})
