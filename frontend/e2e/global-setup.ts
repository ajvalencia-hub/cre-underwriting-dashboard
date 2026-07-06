import fs from 'node:fs'
import path from 'node:path'
import { scratchDbDir, scratchDbPath } from '../playwright.config'

// Best-effort sweep of scratch databases from PREVIOUS runs. The current
// run's db is already open by the backend webServer (which boots before
// globalSetup) and MUST be skipped: unlike Windows, Linux lets you unlink an
// open file without error, which silently detaches the backend's live
// connection from its directory entry and makes SQLite refuse further
// writes ("attempt to write a readonly database").
export default function globalSetup() {
  let entries: string[] = []
  try {
    entries = fs.readdirSync(scratchDbDir)
  } catch {
    return
  }
  const currentDbFile = path.basename(scratchDbPath)
  for (const entry of entries) {
    if (entry === currentDbFile) continue
    if (/^e2e-.*\.sqlite3$/.test(entry)) {
      try {
        fs.rmSync(path.join(scratchDbDir, entry))
      } catch {
        // held open by a still-running backend — leave it
      }
    }
  }
}
