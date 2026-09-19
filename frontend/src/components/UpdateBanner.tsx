import { useEffect, useState } from 'react'
import { openExternal, type UpdateCheckResult } from '../lib/platform'
import { checkForUpdates, dismissTag, dismissedTag, showUpdateBanner } from '../lib/updateCheck'
import { safeStorage } from '../lib/safeStorage'

// safeStorage never throws (private mode, blocked storage).
const storage = () => safeStorage

/** Roadmap #31: desktop only — at launch (at most once a day, if enabled
 *  in Settings) ask GitHub for a newer release and offer the download. The
 *  app never installs anything itself. */
export default function UpdateBanner() {
  const [result, setResult] = useState<UpdateCheckResult | null>(null)
  const [dismissed, setDismissed] = useState(() => dismissedTag(storage()))

  useEffect(() => {
    checkForUpdates(false)
      .then(setResult)
      .catch(() => setResult(null)) // an update check never gets in the way
  }, [])

  if (!showUpdateBanner(result, dismissed) || !result?.latest) return null
  const latest = result.latest
  return (
    <div
      role="status"
      className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800"
    >
      <span>
        CRE Underwriting {latest.tag.replace(/^v/, '')} is available — you have {result.currentVersion}.
      </span>
      <span className="flex gap-2">
        <button
          onClick={() => openExternal(latest.zipUrl ?? latest.url)}
          className="rounded bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700"
        >
          Download
        </button>
        <button onClick={() => openExternal(latest.url)} className="px-2 py-1 text-xs underline">
          What's new
        </button>
        <button
          onClick={() => {
            dismissTag(storage(), latest.tag)
            setDismissed(latest.tag)
          }}
          className="px-2 py-1 text-xs underline"
        >
          Not now
        </button>
      </span>
    </div>
  )
}
