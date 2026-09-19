// localStorage that never throws. Browsers raise SecurityError when storage
// is disabled (private mode, third-party iframes, strict privacy settings) —
// touching window.localStorage directly at boot is a blank page (B13). Every
// read/write here is wrapped; failures degrade to "no stored value".

export interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem?(key: string): void
}

export interface SafeStorage extends StorageLike {
  /** Stored value, or null when missing or storage is unavailable. */
  get(key: string): string | null
  /** True when the write succeeded. */
  set(key: string, value: string): boolean
  remove(key: string): boolean
  removeItem(key: string): void
}

/** Build a safe wrapper over a backing store resolved lazily (so the
 *  resolution itself — which is what throws — is also guarded). */
export function createSafeStorage(resolve: () => StorageLike | null | undefined): SafeStorage {
  function backing(): StorageLike | null {
    try {
      return resolve() ?? null
    } catch {
      return null
    }
  }
  const storage: SafeStorage = {
    get(key) {
      try {
        return backing()?.getItem(key) ?? null
      } catch {
        return null
      }
    },
    set(key, value) {
      try {
        const store = backing()
        if (!store) return false
        store.setItem(key, value)
        return true
      } catch {
        return false
      }
    },
    remove(key) {
      try {
        const store = backing()
        if (!store) return false
        if (store.removeItem) store.removeItem(key)
        else store.setItem(key, '')
        return true
      } catch {
        return false
      }
    },
    // StorageLike adapters so existing injectable helpers (loadViews,
    // loadThemePref, …) accept the safe wrapper directly.
    getItem: (key) => storage.get(key),
    setItem: (key, value) => {
      storage.set(key, value)
    },
    removeItem: (key) => {
      storage.remove(key)
    },
  }
  return storage
}

export const safeStorage: SafeStorage = createSafeStorage(() =>
  typeof window === 'undefined' ? null : window.localStorage,
)
