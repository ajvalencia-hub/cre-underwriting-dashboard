import { openSavedFile, revealInFinder, saveFile, type SaveResult } from './platform'
import { toastSaved } from './toast'

/** Save a generated file (native Save dialog on desktop, download in a
 *  browser) and confirm where it went. Errors propagate to the caller. */
export async function saveOutput(blob: Blob, suggestedName: string): Promise<SaveResult> {
  const result = await saveFile(blob, suggestedName)
  toastSaved(result, { reveal: revealInFinder, open: openSavedFile })
  return result
}

export function textBlob(text: string, type: string): Blob {
  return new Blob([text], { type })
}
