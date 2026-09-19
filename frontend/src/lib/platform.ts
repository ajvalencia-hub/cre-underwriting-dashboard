// Desktop vs browser file handling. In the desktop app (pywebview) the
// Python side exposes window.pywebview.api; opening and saving files go
// through native macOS or Windows dialogs. In a browser everything falls back to the
// existing <input type=file> / anchor-download behaviour.

interface DesktopPickedFile {
  name: string
  base64: string
}

type DesktopPickResult = { files: DesktopPickedFile[] } | { error: string }
type DesktopSaveResult = { path: string } | { cancelled: true } | { error: string }

export interface DesktopSettings {
  storedKeys: string[]
  extraToolDir: string | null
  restartNeeded: boolean
  dataFolder: string
  /** Newer shells report the OS and its user-facing names. */
  platform?: 'macos' | 'windows'
  secretStore?: string
  fileBrowser?: string
}

/** Windows vs macOS wording for the few labels that name an OS feature.
 *  Derived from the user agent so it works before (and without) the shell's
 *  settings — both WebView2 and WKWebView report their OS. */
export function isWindowsHost(userAgent: string = globalThis.navigator?.userAgent ?? ''): boolean {
  return /Windows/i.test(userAgent)
}

export function fileBrowserLabel(userAgent?: string): string {
  return isWindowsHost(userAgent) ? 'File Explorer' : 'Finder'
}

export function secretStoreLabel(userAgent?: string): string {
  return isWindowsHost(userAgent) ? 'Windows Credential Manager' : 'macOS Keychain'
}

/** Roadmap #31: result of the GitHub Releases check (desktop/cre_desktop/updates.py). */
export interface UpdateCheckResult {
  status: 'available' | 'current' | 'noReleases' | 'unknown' | 'off' | 'error'
  currentVersion: string
  enabled: boolean
  releasesPage: string
  checkedAt?: number
  error?: string
  latest?: { tag: string; url: string; zipUrl: string | null; publishedAt: string | null }
}

export interface DesktopApi {
  pick_files(options: { accept: string[]; multiple: boolean; description: string }): Promise<DesktopPickResult>
  save_file(options: { suggestedName: string; base64: string }): Promise<DesktopSaveResult>
  reveal_path(path: string): Promise<void>
  open_path(path: string): Promise<void>
  get_settings(): Promise<DesktopSettings>
  set_api_key(name: string, value: string): Promise<DesktopSettings | { error: string }>
  choose_tool_folder(): Promise<DesktopSettings>
  clear_tool_folder(): Promise<DesktopSettings>
  restart(): Promise<void>
  open_external(url: string): Promise<void>
  set_unsaved(unsaved: boolean): Promise<void>
  /** Absent in builds before the update check. */
  check_for_updates?(force: boolean): Promise<UpdateCheckResult | { error: string }>
  set_update_checks?(enabled: boolean): Promise<{ enabled: boolean; currentVersion: string } | { error: string }>
}

declare global {
  interface Window {
    pywebview?: { api: DesktopApi }
  }
}

export function desktopApi(): DesktopApi | null {
  const api = typeof window !== 'undefined' ? window.pywebview?.api : undefined
  // pywebview first injects `api: {}` and adds the methods in a second step.
  return typeof api?.set_unsaved === 'function' ? api : null
}

/** In the desktop window, resolve once pywebview's bridge is usable. It is
 *  injected only after the page finishes loading, so rendering straight away
 *  would start in browser mode (browser downloads, no quit prompt). The
 *  gate's hint cookie says whether to wait; the timeout keeps a broken bridge
 *  from leaving a blank window. */
export function whenDesktopReady(timeoutMs = 5000): Promise<void> {
  if (isDesktop() || !document.cookie.split('; ').includes('cre_desktop=1')) return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      window.removeEventListener('pywebviewready', done)
      clearTimeout(timer)
      resolve()
    }
    const timer = setTimeout(done, timeoutMs)
    window.addEventListener('pywebviewready', done)
  })
}

export function isDesktop(): boolean {
  return desktopApi() !== null
}

const MIME_BY_EXT: Record<string, string> = {
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  xlsm: 'application/vnd.ms-excel.sheet.macroEnabled.12',
  xls: 'application/vnd.ms-excel',
  csv: 'text/csv',
  pdf: 'application/pdf',
  json: 'application/json',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  txt: 'text/plain',
}

function mimeFor(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  return MIME_BY_EXT[ext] ?? 'application/octet-stream'
}

async function base64ToFile(name: string, base64: string): Promise<File> {
  const type = mimeFor(name)
  const blob = await (await fetch(`data:${type};base64,${base64}`)).blob()
  return new File([blob], name, { type })
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const url = String(reader.result)
      resolve(url.slice(url.indexOf(',') + 1))
    }
    reader.onerror = () => reject(reader.error ?? new Error('Could not read file data'))
    reader.readAsDataURL(blob)
  })
}

/** Split an HTML accept attribute (".xlsx,.xlsm,text/csv") into entries. */
export function parseAccept(accept: string | undefined): string[] {
  return (accept ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

/** Desktop only: native Open dialog. Resolves [] when the user cancels. */
export async function pickFilesNative(options: {
  accept?: string
  multiple?: boolean
  description?: string
}): Promise<File[]> {
  const api = desktopApi()
  if (!api) throw new Error('Native file dialogs are only available in the desktop app')
  const result = await api.pick_files({
    accept: parseAccept(options.accept),
    multiple: Boolean(options.multiple),
    description: options.description ?? 'Supported files',
  })
  if ('error' in result) throw new Error(result.error)
  return Promise.all(result.files.map((f) => base64ToFile(f.name, f.base64)))
}

export type SaveResult =
  | { status: 'saved'; path: string }
  | { status: 'downloaded'; filename: string }
  | { status: 'cancelled' }

/** Save generated output. Desktop: native Save dialog. Browser: download. */
export async function saveFile(blob: Blob, suggestedName: string): Promise<SaveResult> {
  const api = desktopApi()
  if (!api) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = suggestedName
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    return { status: 'downloaded', filename: suggestedName }
  }
  const result = await api.save_file({ suggestedName, base64: await blobToBase64(blob) })
  if ('error' in result) throw new Error(result.error)
  if ('cancelled' in result) return { status: 'cancelled' }
  return { status: 'saved', path: result.path }
}

/** Open an https link outside the app (default browser); a plain anchor
 *  in the desktop window would navigate the app itself. */
export function openExternal(url: string): void {
  const api = desktopApi()
  if (api) void api.open_external(url)
  else window.open(url, '_blank', 'noreferrer')
}

/** Desktop: make closing the window / Cmd+Q ask while edits are unsaved. */
export function reportUnsavedToShell(unsaved: boolean): void {
  void desktopApi()?.set_unsaved(unsaved)
}

export function revealInFinder(path: string): void {
  void desktopApi()?.reveal_path(path)
}

export function openSavedFile(path: string): void {
  void desktopApi()?.open_path(path)
}
