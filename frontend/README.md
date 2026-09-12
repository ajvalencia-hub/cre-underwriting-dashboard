# Frontend

React 19 + TypeScript + Vite + Tailwind 4 single-page app for the CRE
Underwriting Dashboard. No router: `src/App.tsx` owns the tab state and all
cross-tab state; see [`../ARCHITECTURE.md`](../ARCHITECTURE.md) for the module
map and state ownership.

```bash
npm ci
npm run dev        # http://localhost:5173 — proxies /api to http://127.0.0.1:8000
npm test           # vitest over src/lib/*.test.ts
npm run build      # tsc -b && vite build → dist/
npm run lint       # oxlint
npm run e2e        # Playwright smoke (boots a scratch-DB backend + Vite on 8123/5273)
```

Node 22+ (`.nvmrc` at the repo root; `engines.node` in `package.json`).
`VITE_API_PORT` points the dev proxy at a different backend port (the e2e
harness uses it). In the Docker image the backend serves `dist/` itself.

Layout: `src/pages/` one component per tab, `src/components/` shared UI
(the schema-driven `DealInputForm` and its `fields/` primitives, modals,
drawers), `src/lib/` framework-free pure modules each with a `*.test.ts`,
`src/lib/api.ts` the typed fetch layer, `src/types/` API payload types,
`e2e/` the Playwright canary.
