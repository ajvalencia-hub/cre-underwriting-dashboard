import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ACQUISITION_QUICK_SCREEN_INPUTS_KEY,
  QUICK_SCREEN_INPUTS_KEY,
  QUICK_SCREEN_MODE_KEY,
  createAutosaver,
  createSaveConcurrency,
  hydrateDealState,
  serializeDealInputs,
} from './dealPersistence'
import {
  ACQUISITION_QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_DEFAULTS,
  serializeAcquisitionQuickScreenInputs,
  serializeQuickScreenInputs,
} from './quickScreenMath'

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

  it('cancel drops the pending value but keeps the autosaver usable (B12)', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)
    saver.schedule(1)
    saver.cancel()
    expect(saver.getState()).toBe('idle')
    await vi.advanceTimersByTimeAsync(3000)
    expect(save).not.toHaveBeenCalled()

    saver.schedule(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save).toHaveBeenCalledWith(2)
  })

  it('cancel during an in-flight save swallows its failure instead of surfacing error', async () => {
    let rejectFirst!: (e: Error) => void
    const save = vi
      .fn<(v: number) => Promise<void>>()
      .mockImplementationOnce(() => new Promise<void>((_, reject) => (rejectFirst = reject)))
      .mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)
    saver.schedule(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(saver.getState()).toBe('saving')

    saver.cancel()
    rejectFirst(new Error('404 deal deleted'))
    await vi.advanceTimersByTimeAsync(0)
    expect(saver.getState()).toBe('idle')

    // Nothing left to retry — a flush is a no-op.
    await saver.flush()
    expect(save).toHaveBeenCalledTimes(1)
  })
})

describe('createSaveConcurrency', () => {
  it('sends the last recorded ETag as If-Match and nothing when unknown', () => {
    const guard = createSaveConcurrency<{ id: string }>()
    expect(guard.ifMatchFor('a')).toBeUndefined()
    guard.recordEtag('a', '"v1"')
    expect(guard.ifMatchFor('a')).toBe('"v1"')
    expect(guard.etagFor('a')).toBe('"v1"')
    guard.recordEtag('a', '"v2"') // every single-deal response refreshes it
    expect(guard.ifMatchFor('a')).toBe('"v2"')
    guard.recordEtag('a', null)
    expect(guard.ifMatchFor('a')).toBeUndefined()
  })

  it('blocks only the conflicted deal until the user chooses', () => {
    const guard = createSaveConcurrency<{ id: string }>()
    guard.recordEtag('a', '"v1"')
    guard.markConflict({ dealId: 'a', current: { id: 'a' }, etag: '"v9"' })
    expect(guard.isBlocked('a')).toBe(true)
    expect(guard.isBlocked('b')).toBe(false)
    expect(guard.conflict()?.dealId).toBe('a')
  })

  it('Overwrite retries unconditionally until a fresh ETag is recorded', () => {
    const guard = createSaveConcurrency<{ id: string }>()
    guard.recordEtag('a', '"v1"')
    guard.markConflict({ dealId: 'a', current: { id: 'a' }, etag: '"v9"' })
    expect(guard.chooseOverwrite()).toBe('a')
    expect(guard.isBlocked('a')).toBe(false)
    expect(guard.conflict()).toBeNull()
    expect(guard.ifMatchFor('a')).toBeUndefined()
    // The PUT succeeded: the response's ETag re-arms the guard.
    guard.recordEtag('a', '"v10"')
    expect(guard.ifMatchFor('a')).toBe('"v10"')
  })

  it('Reload hands back the server copy and adopts its ETag', () => {
    const guard = createSaveConcurrency<{ id: string; name: string }>()
    guard.recordEtag('a', '"v1"')
    const current = { id: 'a', name: 'edited elsewhere' }
    guard.markConflict({ dealId: 'a', current, etag: '"v9"' })
    expect(guard.chooseReload()).toEqual({ dealId: 'a', current, etag: '"v9"' })
    expect(guard.isBlocked('a')).toBe(false)
    expect(guard.ifMatchFor('a')).toBe('"v9"')
    // Without an ETag on the 412 the stale one is dropped (caller refetches).
    guard.markConflict({ dealId: 'a', current, etag: null })
    guard.chooseReload()
    expect(guard.ifMatchFor('a')).toBeUndefined()
  })

  it('choosing with no pending conflict is a no-op', () => {
    const guard = createSaveConcurrency<{ id: string }>()
    expect(guard.chooseOverwrite()).toBeNull()
    expect(guard.chooseReload()).toBeNull()
  })

  it('forget clears the ETag, the overwrite flag and any pending conflict', () => {
    const guard = createSaveConcurrency<{ id: string }>()
    guard.recordEtag('a', '"v1"')
    guard.markConflict({ dealId: 'a', current: { id: 'a' }, etag: null })
    guard.forget('a')
    expect(guard.conflict()).toBeNull()
    expect(guard.isBlocked('a')).toBe(false)
    expect(guard.ifMatchFor('a')).toBeUndefined()
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
    expect(hydrated.acquisitionQuickScreen).toEqual(ACQUISITION_QUICK_SCREEN_DEFAULTS)
    expect(hydrated.quickScreenMode).toBe('development')
  })

  it('B6: round-trips the acquisition napkin and the active screen', () => {
    const acquisition = { ...ACQUISITION_QUICK_SCREEN_DEFAULTS, purchasePrice: 12_500_000 }
    const blob = serializeDealInputs({}, QUICK_SCREEN_DEFAULTS, acquisition, 'acquisition')
    expect(blob[ACQUISITION_QUICK_SCREEN_INPUTS_KEY]).toEqual(acquisition)
    expect(blob[QUICK_SCREEN_MODE_KEY]).toBe('acquisition')

    const hydrated = hydrateDealState({ dealType: 'acquisition' }, blob, new URLSearchParams())
    expect(hydrated.acquisitionQuickScreen).toEqual(acquisition)
    expect(hydrated.quickScreenMode).toBe('acquisition')
    // Neither persistence key leaks into the Deal Inputs form values.
    expect(ACQUISITION_QUICK_SCREEN_INPUTS_KEY in hydrated.formValues).toBe(false)
    expect(QUICK_SCREEN_MODE_KEY in hydrated.formValues).toBe(false)
    expect(hydrated.formValues).toEqual({ dealType: 'acquisition' })
  })
})

describe('hydrateDealState (acquisition napkin + screen)', () => {
  it('merges a partial stored acquisition napkin over defaults', () => {
    const hydrated = hydrateDealState(
      {},
      { [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: { rent: 1_900 } },
      new URLSearchParams(),
    )
    expect(hydrated.acquisitionQuickScreen.rent).toBe(1_900)
    expect(hydrated.acquisitionQuickScreen.quantity).toBe(ACQUISITION_QUICK_SCREEN_DEFAULTS.quantity)
    expect(hydrated.quickScreenFromUrl).toBe(false)
  })

  it('URL acq_ params and ?screen= win on first load and flag the URL override', () => {
    const url = serializeAcquisitionQuickScreenInputs({
      ...ACQUISITION_QUICK_SCREEN_DEFAULTS,
      purchasePrice: 7_000_000,
    })
    url.set('screen', 'acquisition')
    const hydrated = hydrateDealState(
      {},
      {
        [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: { purchasePrice: 1 },
        [QUICK_SCREEN_MODE_KEY]: 'development',
      },
      url,
    )
    expect(hydrated.acquisitionQuickScreen.purchasePrice).toBe(7_000_000)
    expect(hydrated.quickScreenMode).toBe('acquisition')
    expect(hydrated.quickScreenFromUrl).toBe(true)
  })

  it('ignores a junk stored mode', () => {
    const hydrated = hydrateDealState({}, { [QUICK_SCREEN_MODE_KEY]: 'weird' }, new URLSearchParams())
    expect(hydrated.quickScreenMode).toBe('development')
  })
})
