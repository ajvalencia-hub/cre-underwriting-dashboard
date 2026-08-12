// UI preferences (Settings > Appearance). Pure/injectable for unit tests —
// localStorage tier only: these are per-browser prefs, never server state.

export type ThemePref = 'light' | 'dark' | 'system'

const THEME_KEY = 'cre.themePref'

interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function loadThemePref(storage: StorageLike): ThemePref {
  const raw = storage.getItem(THEME_KEY)
  return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system'
}

export function saveThemePref(storage: StorageLike, pref: ThemePref): void {
  storage.setItem(THEME_KEY, pref)
}

/** Resolve the pref to an actual mode ('system' follows the OS). */
export function effectiveTheme(pref: ThemePref, systemDark: boolean): 'light' | 'dark' {
  if (pref === 'system') return systemDark ? 'dark' : 'light'
  return pref
}

interface RootLike {
  classList: { toggle(token: string, force?: boolean): unknown }
}

export function applyThemeClass(root: RootLike, isDark: boolean): void {
  root.classList.toggle('dark', isDark)
}

/** Boot-time wiring: apply the stored pref immediately (before first paint)
 *  and follow OS changes while the pref is 'system'. Returns the pref. */
export function initTheme(): ThemePref {
  const pref = loadThemePref(window.localStorage)
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  applyThemeClass(document.documentElement, effectiveTheme(pref, media.matches) === 'dark')
  media.addEventListener('change', (e) => {
    if (loadThemePref(window.localStorage) === 'system') {
      applyThemeClass(document.documentElement, e.matches)
    }
  })
  return pref
}

/** Settings-page setter: persist + apply in one step. */
export function setThemePref(pref: ThemePref): void {
  saveThemePref(window.localStorage, pref)
  const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  applyThemeClass(document.documentElement, effectiveTheme(pref, systemDark) === 'dark')
}
