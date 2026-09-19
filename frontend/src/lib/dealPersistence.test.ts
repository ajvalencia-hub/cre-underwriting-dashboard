import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ACQUISITION_QUICK_SCREEN_INPUTS_KEY,
  QUICK_SCREEN_INPUTS_KEY,
  QUICK_SCREEN_MODE_KEY,
  createAutosaver,
  createSaveConcurrency,
  hydrateDealState,
  modeToPersist,
  parseQuickScreenMode,
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

  it('cancel drops the pending value but keeps the autosaver usable', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)
    saver.schedule(1)
    saver.cancel()
    expect(saver.getState()).toBe('idle')
    expect(saver.hasUnsaved()).toBe(false)
    await vi.advanceTimersByTimeAsync(3000)
    expect(save).not.toHaveBeenCalled()

    saver.schedule(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save).toHaveBeenCalledWith(2)
  })

  it('cancel during an in-flight save swallows its failure (no error, no retry)', async () => {
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
    await vi.advanceTimersByTimeAsync(60_000) // no retry timer was started
    expect(save).toHaveBeenCalledTimes(1)
    expect(await saver.flush()).toBe(true)
  })

  it('cancel also stops a pending retry timer', async () => {
    const save = vi.fn<(v: number) => Promise<void>>().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)
    saver.schedule(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(saver.getState()).toBe('error')
    saver.cancel()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(saver.getState()).toBe('idle')
    expect(saver.hasUnsaved()).toBe(false)
  })

  it('a value scheduled after cancel, while the cancelled save is in flight, still saves', async () => {
    let resolveFirst!: () => void
    const save = vi
      .fn<(v: number) => Promise<void>>()
      .mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))
      .mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000)
    saver.schedule(1)
    await vi.advanceTimersByTimeAsync(2000)
    saver.cancel()
    saver.schedule(2)
    resolveFirst()
    await vi.advanceTimersByTimeAsync(2000)
    expect(save).toHaveBeenLastCalledWith(2)
    expect(saver.getState()).toBe('saved')
  })

  it('a non-retryable failure (412) parks as blocked: no retry loop, flush reports unsaved', async () => {
    class Conflict extends Error {}
    const save = vi.fn<(v: number) => Promise<void>>().mockRejectedValueOnce(new Conflict('412')).mockResolvedValue(undefined)
    const saver = createAutosaver<number>(save, 2000, { shouldRetry: (err) => !(err instanceof Conflict) })
    saver.schedule(5)
    await vi.advanceTimersByTimeAsync(2000)
    expect(saver.getState()).toBe('blocked')
    expect(saver.hasUnsaved()).toBe(true)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(save).toHaveBeenCalledTimes(1) // never retried on its own

    // Overwrite = the caller flushes: the kept value goes out again.
    expect(await saver.flush()).toBe(true)
    expect(save).toHaveBeenLastCalledWith(5)
    expect(saver.getState()).toBe('saved')
  })

  it('blocked then cancel (Reload) drops the kept value', async () => {
    const save = vi.fn<(v: number) => Promise<void>>().mockRejectedValue(new Error('412'))
    const saver = createAutosaver<number>(save, 2000, { shouldRetry: () => false })
    saver.schedule(5)
    await vi.advanceTimersByTimeAsync(2000)
    expect(saver.getState()).toBe('blocked')
    saver.cancel()
    expect(saver.hasUnsaved()).toBe(false)
    expect(await saver.flush()).toBe(true)
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
    guard.recordEtag('a', '"v2"')
    expect(guard.ifMatchFor('a')).toBe('"v2"')
    guard.recordEtag('a', null)
    expect(guard.ifMatchFor('a')).toBeUndefined()
  })

  it('blocks only the conflicted deal until the user chooses, and notifies', () => {
    const guard = createSaveConcurrency<{ id: string }>()
    const seen: (string | null)[] = []
    guard.subscribe((c) => seen.push(c?.dealId ?? null))
    guard.recordEtag('a', '"v1"')
    guard.markConflict({ dealId: 'a', current: { id: 'a' }, etag: '"v9"' })
    expect(guard.isBlocked('a')).toBe(true)
    expect(guard.isBlocked('b')).toBe(false)
    expect(guard.conflict()?.dealId).toBe('a')
    guard.chooseOverwrite()
    expect(seen).toEqual(['a', null])
  })

  it('Overwrite retries unconditionally until a fresh ETag is recorded', () => {
    const guard = createSaveConcurrency<{ id: string }>()
    guard.recordEtag('a', '"v1"')
    guard.markConflict({ dealId: 'a', current: { id: 'a' }, etag: '"v9"' })
    expect(guard.chooseOverwrite()).toBe('a')
    expect(guard.isBlocked('a')).toBe(false)
    expect(guard.conflict()).toBeNull()
    expect(guard.ifMatchFor('a')).toBeUndefined()
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

describe('quick screen mode persistence', () => {
  it('round-trips a stored mode and ignores junk', () => {
    const blob = serializeDealInputs({}, QUICK_SCREEN_DEFAULTS, ACQUISITION_QUICK_SCREEN_DEFAULTS, 'acquisition')
    expect(blob[QUICK_SCREEN_MODE_KEY]).toBe('acquisition')
    expect(hydrateDealState({}, blob).quickScreenMode).toBe('acquisition')
    expect(hydrateDealState({}, { [QUICK_SCREEN_MODE_KEY]: 'banana' }).quickScreenMode).toBeNull()
    expect(parseQuickScreenMode('development')).toBe('development')
  })

  it('never adds the key to a deal that did not store one', () => {
    const blob = serializeDealInputs({ a: 1 }, QUICK_SCREEN_DEFAULTS, ACQUISITION_QUICK_SCREEN_DEFAULTS)
    expect(QUICK_SCREEN_MODE_KEY in blob).toBe(false)
    expect(hydrateDealState({}, blob).formValues).toEqual({ a: 1 }) // the mode key is stripped from fields
  })

  it('modeToPersist: default unwritten, a pick written, frozen while IC-locked', () => {
    expect(modeToPersist(null, 'development', false)).toBeNull()
    expect(modeToPersist(null, 'acquisition', false)).toBe('acquisition')
    expect(modeToPersist('acquisition', 'development', false)).toBe('development')
    expect(modeToPersist(null, 'acquisition', true)).toBeNull()
    expect(modeToPersist('acquisition', 'development', true)).toBe('acquisition')
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
