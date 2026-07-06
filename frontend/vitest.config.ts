import { defineConfig, defaultExclude } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    // e2e/ is Playwright's — its spec files crash under vitest's runner.
    exclude: [...defaultExclude, 'e2e/**'],
  },
})
