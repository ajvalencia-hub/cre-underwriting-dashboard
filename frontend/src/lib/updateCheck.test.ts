import { describe, expect, it } from 'vitest'
import { describeUpdateCheck, showUpdateBanner } from './updateCheck'
import type { UpdateCheckResult } from './platform'

const base: UpdateCheckResult = {
  status: 'available',
  currentVersion: '1.0.0',
  enabled: true,
  releasesPage: 'https://github.com/r/releases',
  latest: { tag: 'v1.1.0', url: 'https://github.com/r/releases/tag/v1.1.0', zipUrl: null, publishedAt: null },
}

describe('update check wording', () => {
  it('shows the banner for a newer release until that release is dismissed', () => {
    expect(showUpdateBanner(base, null)).toBe(true)
    expect(showUpdateBanner(base, 'v1.1.0')).toBe(false)
    expect(showUpdateBanner(base, 'v1.0.5')).toBe(true)
    expect(showUpdateBanner({ ...base, status: 'current' }, null)).toBe(false)
    expect(showUpdateBanner(null, null)).toBe(false)
  })

  it('says what happened in words', () => {
    expect(describeUpdateCheck(base)).toBe('Version 1.1.0 is available (you have 1.0.0).')
    expect(describeUpdateCheck({ ...base, status: 'noReleases' })).toContain('No releases')
    expect(describeUpdateCheck({ ...base, status: 'error', error: "Couldn't reach GitHub: timed out" })).toContain('timed out')
  })
})
