import { useState, type ReactNode } from 'react'
import { fetchServerFile } from '../lib/api'
import { isDesktop } from '../lib/platform'
import { saveOutput } from '../lib/saveOutput'
import { toastError } from '../lib/toast'

interface ServerFileLinkProps {
  href: string
  /** Used when the server doesn't name the file. */
  filename: string
  className?: string
  title?: string
  /** Browser only: open in a new tab (e.g. the share page) instead of downloading. */
  newTab?: boolean
  /** Browser only: the anchor's download attribute. */
  download?: string
  children: ReactNode
}

/**
 * A link to a server-generated file. Browser: the same <a> as before.
 * Desktop app: fetches the file and saves it through the native Save dialog
 * — a plain link there would navigate the app window itself (and replace the
 * whole app with an error page if the server refused).
 */
export default function ServerFileLink({ href, filename, className, title, newTab, download, children }: ServerFileLinkProps) {
  const [busy, setBusy] = useState(false)

  if (!isDesktop()) {
    return (
      <a
        href={href}
        className={className}
        title={title}
        download={download}
        {...(newTab ? { target: '_blank', rel: 'noreferrer' } : {})}
      >
        {children}
      </a>
    )
  }

  async function handleClick() {
    setBusy(true)
    try {
      const file = await fetchServerFile(href, filename)
      await saveOutput(file.blob, file.filename)
    } catch (err) {
      toastError(`Couldn't create ${filename}`, err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <button type="button" onClick={() => void handleClick()} disabled={busy} className={className} title={title}>
      {busy ? 'Preparing…' : children}
    </button>
  )
}
