import { useEffect, useMemo, useState } from 'react'
import {
  ACQUISITION_QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS,
  computeAcquisitionQuickScreen,
  computeQuickScreen,
  mapAcquisitionQuickScreenToOutputMetrics,
  mapQuickScreenToOutputMetrics,
  type AcquisitionQuickScreenInputs,
  type QuickScreenInputs,
} from '../lib/quickScreenMath'
import { shareParams, type SharedScreen } from '../lib/shareLink'

export type QuickScreenMode = 'development' | 'acquisition'

/** Fields a Quick Screen can't estimate — the sidebar marks them. */
const FULL_MODEL_ONLY_IDS: ReadonlySet<string> = new Set<string>(QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS)

/** Both napkins (development and acquisition), which one is showing, their
 *  results, the sidebar estimates of the active one, and the sharable URL
 *  kept in sync with all three. Split out of App.tsx (roadmap #32). */
export function useQuickScreens() {
  const [development, setDevelopment] = useState<QuickScreenInputs>(QUICK_SCREEN_DEFAULTS)
  const [acquisition, setAcquisition] = useState<AcquisitionQuickScreenInputs>(ACQUISITION_QUICK_SCREEN_DEFAULTS)
  const [mode, setMode] = useState<QuickScreenMode>('development')

  const developmentResults = useMemo(() => computeQuickScreen(development), [development])
  const acquisitionResults = useMemo(() => computeAcquisitionQuickScreen(acquisition), [acquisition])
  // Sidebar estimates follow the ACTIVE napkin.
  const outputs = useMemo(
    () =>
      mode === 'acquisition'
        ? mapAcquisitionQuickScreenToOutputMetrics(acquisitionResults, acquisition)
        : mapQuickScreenToOutputMetrics(developmentResults, development),
    [mode, developmentResults, development, acquisitionResults, acquisition],
  )

  // Keep the sharable URL in sync with BOTH napkins + the active screen.
  useEffect(() => {
    const handle = setTimeout(() => {
      const params = shareParams(development, acquisition, mode)
      window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`)
    }, 500)
    return () => clearTimeout(handle)
  }, [development, acquisition, mode])

  function applyShared(shared: SharedScreen) {
    if (shared.development) setDevelopment(shared.development)
    if (shared.acquisition) setAcquisition(shared.acquisition)
    setMode(shared.mode)
  }

  return {
    development,
    setDevelopment,
    developmentResults,
    acquisition,
    setAcquisition,
    mode,
    setMode,
    outputs,
    fullModelOnlyIds: FULL_MODEL_ONLY_IDS,
    applyShared,
  }
}
