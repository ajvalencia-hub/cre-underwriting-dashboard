import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ACQUISITION_QUICK_SCREEN_INPUTS_KEY,
  QUICK_SCREEN_INPUTS_KEY,
  createAutosaver,
  hydrateDealState,
  serializeDealInputs,
} from './dealPersistence'
import { ACQUISITION_QUICK_SCREEN_DEFAULTS, QUICK_SCREEN_DEFAULTS } from './quickScreenMath'

describe('createAutosaver', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('retries a failed save on its own and reports unsaved work until it lands', async () => {
    const save = vi
      .fn<(v: number) => Promise<void>>()
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)

    saver.schedule(7)
    await vi.advanceTimersByTimeAsync(2000)
    expect(saver.getState()).toBe('error')
    expect(saver.hasUnsaved()).toBe(true)

    await vi.advanceTimersByTimeAsync(3000) // first retry
    expect(save).toHaveBeenCalledTimes(2)
    expect(saver.getState()).toBe('error')

    await vi.advanceTimersByTimeAsync(10000) // second retry succeeds
    expect(save).toHaveBeenCalledTimes(3)
    expect(save).toHaveBeenLastCalledWith(7)
    expect(saver.getState()).toBe('saved')
    expect(saver.hasUnsaved()).toBe(false)
  })

  it('flush says whether everything reached the server', async () => {
    const save = vi.fn<(v: number) => Promise<void>>().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)
    saver.schedule(1)
    expect(await saver.flush()).toBe(false)
    expect(await saver.flush()).toBe(true)
    expect(await saver.flush()).toBe(true) // nothing pending
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

  it('flush during an in-flight save waits for it (and the value queued behind it)', async () => {
    let resolveFirst!: () => void
    const save = vi
      .fn<(v: number) => Promise<void>>()
      .mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))
      .mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)

    saver.schedule(1)
    await vi.advanceTimersByTimeAsync(2000) // save of 1 now in flight
    saver.schedule(2)
    let flushed: boolean | undefined
    void saver.flush().then((ok) => (flushed = ok))
    await vi.advanceTimersByTimeAsync(0)
    expect(flushed).toBeUndefined() // it used to resolve false right here

    resolveFirst()
    await vi.advanceTimersByTimeAsync(0)
    expect(flushed).toBe(true)
    expect(save).toHaveBeenLastCalledWith(2)
    expect(saver.hasUnsaved()).toBe(false)
  })

  it('flush during an in-flight save that fails reports false', async () => {
    let rejectFirst!: (e: Error) => void
    const save = vi
      .fn<(v: number) => Promise<void>>()
      .mockImplementationOnce(() => new Promise<void>((_, rej) => (rejectFirst = rej)))
    const saver = createAutosaver<number>(save, 2000)

    saver.schedule(1)
    await vi.advanceTimersByTimeAsync(2000)
    const flushed = saver.flush()
    rejectFirst(new Error('offline'))
    expect(await flushed).toBe(false)
    expect(saver.hasUnsaved()).toBe(true)
    saver.dispose()
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

  it('restores the stored napkins, merged over defaults', () => {
    const hydrated = hydrateDealState(defaults, {
      [QUICK_SCREEN_INPUTS_KEY]: { rent: 1600 }, // partial: saved by an older version
      [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: { purchasePrice: 9_000_000 },
    })
    expect(hydrated.quickScreen.rent).toBe(1600)
    expect(hydrated.quickScreen.quantity).toBe(QUICK_SCREEN_DEFAULTS.quantity)
    expect(hydrated.acquisitionQuickScreen.purchasePrice).toBe(9_000_000)
    expect(hydrated.acquisitionQuickScreen.ltvPct).toBe(ACQUISITION_QUICK_SCREEN_DEFAULTS.ltvPct)
  })

  it('uses defaults when the deal has no napkin state', () => {
    const hydrated = hydrateDealState(defaults, {})
    expect(hydrated.quickScreen).toEqual(QUICK_SCREEN_DEFAULTS)
    expect(hydrated.acquisitionQuickScreen).toEqual(ACQUISITION_QUICK_SCREEN_DEFAULTS)
  })

  it('merges deal fields over schema defaults and strips the napkin keys', () => {
    const hydrated = hydrateDealState(defaults, {
      vacancyPct: 0.08,
      purchasePrice: 1_000_000,
      [QUICK_SCREEN_INPUTS_KEY]: {},
      [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: {},
    })
    expect(hydrated.formValues).toEqual({
      dealType: 'acquisition',
      vacancyPct: 0.08,
      purchasePrice: 1_000_000,
    })
  })
})

describe('serializeDealInputs', () => {
  it('round-trips both napkins through hydrateDealState', () => {
    const quickScreen = { ...QUICK_SCREEN_DEFAULTS, rent: 2100 }
    const acquisition = { ...ACQUISITION_QUICK_SCREEN_DEFAULTS, purchasePrice: 7_500_000 }
    const blob = serializeDealInputs({ purchasePrice: 5 }, quickScreen, acquisition)
    const hydrated = hydrateDealState({}, blob)
    expect(hydrated.formValues).toEqual({ purchasePrice: 5 })
    expect(hydrated.quickScreen).toEqual(quickScreen)
    expect(hydrated.acquisitionQuickScreen).toEqual(acquisition)
  })
})
