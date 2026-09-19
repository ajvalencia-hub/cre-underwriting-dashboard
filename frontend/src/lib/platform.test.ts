import { describe, expect, it } from 'vitest'
import { fileBrowserLabel, secretStoreLabel } from './platform'

describe('OS-specific labels', () => {
  const win = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Edg/153.0'
  const mac = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15'
  it('names File Explorer / Credential Manager on Windows and Finder / Keychain on macOS', () => {
    expect(fileBrowserLabel(win)).toBe('File Explorer')
    expect(secretStoreLabel(win)).toBe('Windows Credential Manager')
    expect(fileBrowserLabel(mac)).toBe('Finder')
    expect(secretStoreLabel(mac)).toBe('macOS Keychain')
  })
})
