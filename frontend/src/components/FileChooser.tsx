import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import { isDesktop, pickFilesNative } from '../lib/platform'
import { toastError } from '../lib/toast'

interface FileChooserProps {
  /** HTML accept list, e.g. ".xlsx,.xlsm". Also filters the native dialog. */
  accept?: string
  multiple?: boolean
  disabled?: boolean
  /** Shown in the native dialog's file-type menu, e.g. "Excel workbooks". */
  description?: string
  /** Desktop button label. */
  label?: string
  /** Browser: className of the <input type=file> (unchanged from before). */
  className?: string
  /** Browser: render the input hidden (callers open it via ref.open()). */
  hidden?: boolean
  onFiles: (files: File[]) => void
}

export interface FileChooserHandle {
  /** Programmatically open the chooser (native dialog or hidden input). */
  open: () => void
}

/**
 * Browser: exactly the previous <input type="file">. Desktop app: a button
 * that opens the native macOS Open dialog. Either way the caller gets File[].
 */
const FileChooser = forwardRef<FileChooserHandle, FileChooserProps>(function FileChooser(
  { accept, multiple, disabled, description, label, className, hidden, onFiles },
  ref,
) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [picking, setPicking] = useState(false)
  const desktop = isDesktop()

  async function openNative() {
    if (picking || disabled) return
    setPicking(true)
    try {
      const files = await pickFilesNative({ accept, multiple, description })
      if (files.length > 0) onFiles(files)
    } catch (err) {
      toastError('Could not open the file', err)
    } finally {
      setPicking(false)
    }
  }

  useImperativeHandle(ref, () => ({
    open: () => {
      if (desktop) void openNative()
      else inputRef.current?.click()
    },
  }))

  if (desktop) {
    if (hidden) return null
    return (
      <button
        type="button"
        onClick={() => void openNative()}
        disabled={disabled || picking}
        className="rounded border border-slate-300 bg-white px-3 py-1 text-sm hover:bg-slate-50 disabled:opacity-50"
      >
        {label ?? (multiple ? 'Choose files…' : 'Choose file…')}
      </button>
    )
  }

  return (
    <input
      ref={inputRef}
      type="file"
      accept={accept}
      multiple={multiple}
      disabled={disabled}
      className={hidden ? 'hidden' : className}
      onChange={(e) => {
        const files = Array.from(e.target.files ?? [])
        e.target.value = ''
        if (files.length > 0) onFiles(files)
      }}
    />
  )
})

export default FileChooser
