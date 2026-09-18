import { useEffect, useState } from 'react'
import { desktopApi, type DesktopSettings } from './platform'
import { toastError } from './toast'

/** Desktop app only: current settings from the Python side, refreshed after each change. */
export function useDesktopSettings(active: boolean) {
  const [settings, setSettings] = useState<DesktopSettings | null>(null)
  useEffect(() => {
    const api = desktopApi()
    if (!active || !api) return
    api.get_settings().then(setSettings).catch((err) => toastError('Could not read desktop settings', err))
  }, [active])
  return [settings, setSettings] as const
}
