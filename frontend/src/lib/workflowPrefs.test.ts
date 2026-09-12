import { describe, expect, it } from 'vitest'
import {
  loadLastTab,
  loadNewDealTypePref,
  saveLastTab,
  saveNewDealTypePref,
} from './workflowPrefs'

function memory() {
  const data = new Map<string, string>()
  return {
    get: (k: string) => data.get(k) ?? null,
    set: (k: string, v: string) => data.set(k, v),
  }
}

const TABS = ['pipeline', 'quickscreen', 'dashboard'] as const

describe('last tab', () => {
  it('round-trips a valid tab and falls back on junk or missing', () => {
    const storage = memory()
    expect(loadLastTab(storage, TABS, 'quickscreen')).toBe('quickscreen')
    saveLastTab(storage, 'dashboard')
    expect(loadLastTab(storage, TABS, 'quickscreen')).toBe('dashboard')
    saveLastTab(storage, 'removed-tab')
    expect(loadLastTab(storage, TABS, 'quickscreen')).toBe('quickscreen')
  })
})

describe('new deal type pref', () => {
  it('defaults to ask and round-trips', () => {
    const storage = memory()
    expect(loadNewDealTypePref(storage)).toBe('ask')
    saveNewDealTypePref(storage, 'development')
    expect(loadNewDealTypePref(storage)).toBe('development')
    storage.set('cre.newDealType', 'weird')
    expect(loadNewDealTypePref(storage)).toBe('ask')
  })
})
