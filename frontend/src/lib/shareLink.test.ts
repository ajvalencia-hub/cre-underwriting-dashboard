import { describe, expect, it } from 'vitest'
import { ACQUISITION_QUICK_SCREEN_DEFAULTS, QUICK_SCREEN_DEFAULTS } from './quickScreenMath'
import { DESKTOP_SHARE_PREFIX, buildShareLink, parseShareLink, shareParams } from './shareLink'

describe('quick screen share links', () => {
  const dev = { ...QUICK_SCREEN_DEFAULTS, exitCapRatePct: 0.0525 }
  const acq = { ...ACQUISITION_QUICK_SCREEN_DEFAULTS, purchasePrice: 12_500_000 }

  it('round-trips the desktop link form', () => {
    const link = buildShareLink(shareParams(dev, acq, 'acquisition'), null)
    expect(link.startsWith(`${DESKTOP_SHARE_PREFIX}?`)).toBe(true)
    const parsed = parseShareLink(link)
    expect(parsed?.mode).toBe('acquisition')
    expect(parsed?.development?.exitCapRatePct).toBe(0.0525)
    expect(parsed?.acquisition?.purchasePrice).toBe(12_500_000)
  })

  it('accepts a browser URL, surrounding whitespace, and a fragment', () => {
    const link = buildShareLink(shareParams(dev, acq, 'development'), 'http://localhost:5173/')
    const parsed = parseShareLink(`  ${link}#top \n`)
    expect(parsed?.mode).toBe('development')
    expect(parsed?.development?.exitCapRatePct).toBe(0.0525)
  })

  it('rejects text without quick screen parameters', () => {
    expect(parseShareLink('https://example.com/?foo=1')).toBeNull()
    expect(parseShareLink('')).toBeNull()
    expect(parseShareLink('not a link')).toBeNull()
  })
})
