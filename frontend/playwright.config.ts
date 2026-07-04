import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// The smoke drives the REAL stack: a scratch-database FastAPI backend on
// 8123 and a Vite dev server on 5273 proxying to it — ports chosen to never
// collide with a developer's normal 8000/5173 session.

const backendDir = path.resolve(__dirname, '../backend')
const pythonBin =
  process.platform === 'win32'
    ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
    : path.join(backendDir, '.venv', 'bin', 'python')
// Per-run scratch database. NOT under test-results/ — that's Playwright's
// outputDir, which it wipes at startup (empirically: after this config's
// mkdir ran). The unique name provides the fresh-DB guarantee; globalSetup
// best-effort sweeps older ones.
export const scratchDbDir = path.resolve(__dirname, '.e2e-scratch')
fs.mkdirSync(scratchDbDir, { recursive: true })
const scratchDbPath = path.join(scratchDbDir, `e2e-${Date.now()}.sqlite3`)

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  globalSetup: './e2e/global-setup.ts',
  use: {
    baseURL: 'http://127.0.0.1:5273',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: [
    {
      // The scratch DB path is injected INSIDE the python command (not via
      // webServer env) so it works identically regardless of how the runner
      // spawns the process.
      command:
        `"${pythonBin}" -c "import os; os.environ['CRE_DB_PATH'] = r'${scratchDbPath}'; ` +
        `import uvicorn; uvicorn.run('app.main:app', port=8123)"`,
      cwd: backendDir,
      port: 8123,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --port 5273 --strictPort --host 127.0.0.1',
      cwd: __dirname,
      port: 5273,
      env: { VITE_API_PORT: '8123' },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
