import { describe, expect, it } from 'vitest'
import {
  applyThemeClass,
  effectiveTheme,
  loadThemePref,
  saveThemePref,
} from './uiPrefs'

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial }
  return {
    getItem: (key: string) => (key in data ? data[key] : null),
    setItem: (key: string, value: string) => {
      data[key] = value
    },
  }
}

describe('theme pref storage', () => {
  it('round-trips and defaults junk to system', () => {
    const storage = memoryStorage()
    expect(loadThemePref(storage)).toBe('system')
    saveThemePref(storage, 'dark')
    expect(loadThemePref(storage)).toBe('dark')
    expect(loadThemePref(memoryStorage({ 'cre.themePref': 'neon' }))).toBe('system')
  })
})

describe('effectiveTheme', () => {
  it('explicit prefs ignore the OS; system follows it', () => {
    expect(effectiveTheme('light', true)).toBe('light')
    expect(effectiveTheme('dark', false)).toBe('dark')
    expect(effectiveTheme('system', true)).toBe('dark')
    expect(effectiveTheme('system', false)).toBe('light')
  })
})

describe('applyThemeClass', () => {
  it('toggles the dark class on the given root', () => {
    const calls: [string, boolean | undefined][] = []
    const root = { classList: { toggle: (t: string, f?: boolean) => calls.push([t, f]) } }
    applyThemeClass(root, true)
    applyThemeClass(root, false)
    expect(calls).toEqual([
      ['dark', true],
      ['dark', false],
    ])
  })
})
