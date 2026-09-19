// Roadmap #31: what the UI says about the desktop update check.
import { desktopApi, type UpdateCheckResult } from './platform'

const DISMISSED_KEY = 'cre.updateDismissed'

export async function checkForUpdates(force: boolean): Promise<UpdateCheckResult | null> {
  const api = desktopApi()
  if (!api?.check_for_updates) return null
  const result = await api.check_for_updates(force)
  return 'status' in result ? result : null
}

export async function setUpdateChecks(enabled: boolean): Promise<boolean> {
  const api = desktopApi()
  if (!api?.set_update_checks) return false
  const result = await api.set_update_checks(enabled)
  return 'enabled' in result
}

export function dismissedTag(storage: Pick<Storage, 'getItem'> | null): string | null {
  try {
    return storage?.getItem(DISMISSED_KEY) ?? null
  } catch {
    return null
  }
}

export function dismissTag(storage: Pick<Storage, 'setItem'> | null, tag: string): void {
  try {
    storage?.setItem(DISMISSED_KEY, tag)
  } catch {
    // not remembering the dismissal only means the banner shows again
  }
}

/** The launch banner shows for a newer release the user hasn't dismissed. */
export function showUpdateBanner(result: UpdateCheckResult | null, dismissed: string | null): boolean {
  return result?.status === 'available' && !!result.latest && result.latest.tag !== dismissed
}

export function describeUpdateCheck(result: UpdateCheckResult): string {
  switch (result.status) {
    case 'available':
      return `Version ${result.latest?.tag.replace(/^v/, '')} is available (you have ${result.currentVersion}).`
    case 'current':
      return `You have the latest version (${result.currentVersion}).`
    case 'noReleases':
      return `No releases are published yet (you have ${result.currentVersion}).`
    case 'unknown':
      return `The latest release's tag (${result.latest?.tag}) isn't a version number this app can compare.`
    case 'off':
      return 'Checking for updates is off.'
    case 'error':
      return result.error ?? "Couldn't check for updates."
  }
}
