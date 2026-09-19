// Quick Screen share links. In a browser the page URL itself is the share
// link (the app keeps it in sync). The desktop app has no address bar and
// its local URL (random port) is meaningless to anyone else, so "Copy share
// link" produces an app link a colleague pastes into "Open shared link…".
// Both forms carry the same query parameters, and both are accepted back.

import {
  parseAcquisitionQuickScreenInputs,
  parseQuickScreenInputs,
  serializeAcquisitionQuickScreenInputs,
  serializeQuickScreenInputs,
  type AcquisitionQuickScreenInputs,
  type QuickScreenInputs,
} from './quickScreenMath'

export type ScreenMode = 'development' | 'acquisition'

export const DESKTOP_SHARE_PREFIX = 'cre-underwriting://quick-screen'

export function shareParams(
  development: QuickScreenInputs,
  acquisition: AcquisitionQuickScreenInputs,
  mode: ScreenMode,
): URLSearchParams {
  const params = serializeQuickScreenInputs(development)
  serializeAcquisitionQuickScreenInputs(acquisition, params)
  if (mode === 'acquisition') params.set('screen', 'acquisition')
  return params
}

/** `base` is the page URL without its query (browser) or null (desktop). */
export function buildShareLink(params: URLSearchParams, base: string | null): string {
  return `${base ?? DESKTOP_SHARE_PREFIX}?${params.toString()}`
}

export interface SharedScreen {
  development: QuickScreenInputs | null
  acquisition: AcquisitionQuickScreenInputs | null
  mode: ScreenMode
}

/** Accepts either link form (or a bare query string). Null if the text
 *  doesn't contain Quick Screen parameters. */
export function parseShareLink(text: string): SharedScreen | null {
  const trimmed = text.trim()
  const q = trimmed.indexOf('?')
  const query = q >= 0 ? trimmed.slice(q + 1) : trimmed
  if (!query) return null
  const params = new URLSearchParams(query.split('#')[0])
  const development = parseQuickScreenInputs(params)
  const acquisition = parseAcquisitionQuickScreenInputs(params)
  if (development === null && acquisition === null) return null
  const mode: ScreenMode =
    params.get('screen') === 'acquisition' || (development === null && acquisition !== null)
      ? 'acquisition'
      : 'development'
  return { development, acquisition, mode }
}
