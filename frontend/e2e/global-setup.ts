import fs from 'node:fs'
import path from 'node:path'
import { scratchDbDir, scratchDbPath } from '../playwright.config'

// Best-effort sweep of scratch databases from PREVIOUS runs. The current
// run's db is already open by the backend webServer (which boots before
// globalSetup) and must be skipped explicitly: on Linux/macOS unlinking an
// open file SUCCEEDS, and SQLite then fails every write with "attempt to
// write a readonly database".
export default function globalSetup() {
  let entries: string[] = []
  try {
    entries = fs.readdirSync(scratchDbDir)
  } catch {
    return
  }
  for (const entry of entries) {
    const full = path.join(scratchDbDir, entry)
    if (/^e2e-.*\.sqlite3$/.test(entry) && full !== scratchDbPath) {
      try {
        fs.rmSync(full)
      } catch {
        // locked (e.g. Windows) — leave it
      }
    }
  }
}
