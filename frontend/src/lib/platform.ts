// Desktop vs browser file handling. In the desktop app (pywebview) the
// Python side exposes window.pywebview.api; opening and saving files go
// through native macOS dialogs. In a browser everything falls back to the
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
}

declare global {
  interface Window {
    pywebview?: { api: DesktopApi }
  }
}

export function desktopApi(): DesktopApi | null {
  return typeof window !== 'undefined' && window.pywebview?.api ? window.pywebview.api : null
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

export function revealInFinder(path: string): void {
  void desktopApi()?.reveal_path(path)
}

export function openSavedFile(path: string): void {
  void desktopApi()?.open_path(path)
}
