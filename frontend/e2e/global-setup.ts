import fs from 'node:fs'
import path from 'node:path'
import { scratchDbDir, scratchDbPath } from '../playwright.config'

// Best-effort sweep of scratch databases from PREVIOUS runs. The current
// run's db is already open by the backend webServer (which boots before
// globalSetup) and must be skipped explicitly: Windows refuses to delete an
// open file, but macOS/Linux unlink it, leaving the backend with a
// "readonly database" on its first write.
export default function globalSetup() {
  let entries: string[] = []
  try {
    entries = fs.readdirSync(scratchDbDir)
  } catch {
    return
  }
  for (const entry of entries) {
    if (/^e2e-.*\.sqlite3$/.test(entry) && path.join(scratchDbDir, entry) !== scratchDbPath) {
      try {
        fs.rmSync(path.join(scratchDbDir, entry))
      } catch {
        // held open by this run's backend — leave it
      }
    }
  }
}
