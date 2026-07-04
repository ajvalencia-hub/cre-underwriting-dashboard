import fs from 'node:fs'
import path from 'node:path'
import { scratchDbDir } from '../playwright.config'

// Best-effort sweep of scratch databases from PREVIOUS runs. The current
// run's db is already open by the backend webServer (which boots before
// globalSetup), so deletion failures are expected and ignored.
export default function globalSetup() {
  let entries: string[] = []
  try {
    entries = fs.readdirSync(scratchDbDir)
  } catch {
    return
  }
  for (const entry of entries) {
    if (/^e2e-.*\.sqlite3$/.test(entry)) {
      try {
        fs.rmSync(path.join(scratchDbDir, entry))
      } catch {
        // held open by this run's backend — leave it
      }
    }
  }
}
