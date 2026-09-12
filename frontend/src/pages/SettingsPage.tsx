import { memo, useEffect, useState } from 'react'
import {
  UNAUTHORIZED_EVENT,
  backupDownloadUrl,
  fetchAuthStatus,
  fetchBackups,
  fetchIntegrations,
  logout,
  restoreBackup,
  runBackupNow,
  type AuthStatus,
  type BackupSnapshot,
  type IntegrationStatus,
} from '../lib/api'
import { safeStorage } from '../lib/safeStorage'
import { loadThemePref, setThemePref, type ThemePref } from '../lib/uiPrefs'
import {
  loadNewDealTypePref,
  saveNewDealTypePref,
  type NewDealTypePref,
} from '../lib/workflowPrefs'

interface SettingsPageProps {
  active: boolean
}

const THEME_OPTIONS: { value: ThemePref; label: string; hint: string }[] = [
  { value: 'light', label: 'Light', hint: 'Always light' },
  { value: 'dark', label: 'Dark', hint: 'Always dark' },
  { value: 'system', label: 'System', hint: 'Follow the OS setting' },
]

const NEW_DEAL_TYPE_OPTIONS: { value: NewDealTypePref; label: string; hint: string }[] = [
  { value: 'ask', label: 'Ask each time', hint: 'The New Deal button opens the type chooser' },
  { value: 'acquisition', label: 'Acquisition', hint: 'One click creates an acquisition' },
  { value: 'development', label: 'Development', hint: 'One click creates a development' },
]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold tracking-wide text-slate-500">{title}</div>
      <div className="mt-3">{children}</div>
    </div>
  )
}

function SnapshotTable({
  kind,
  snapshots,
  onRestore,
  busy,
}: {
  kind: 'daily' | 'weekly'
  snapshots: BackupSnapshot[]
  onRestore: (kind: string, name: string) => void
  busy: boolean
}) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {kind} ({snapshots.length})
      </div>
      {snapshots.length === 0 ? (
        <div className="mt-1 text-xs text-slate-400">No {kind} snapshots yet.</div>
      ) : (
        <table className="mt-1 w-full text-xs">
          <thead>
            <tr className="text-left text-slate-400">
              <th className="pr-3 font-medium">Snapshot</th>
              <th className="pr-3 font-medium">Created</th>
              <th className="pr-3 text-right font-medium">Uploads listed</th>
              <th className="pr-3 font-medium">DB</th>
              <th />
            </tr>
          </thead>
          <tbody className="text-slate-600">
            {snapshots.map((snap) => (
              <tr key={snap.name}>
                <td className="pr-3 font-mono">{snap.name}</td>
                <td className="pr-3">
                  {snap.createdAt ? new Date(snap.createdAt).toLocaleString() : '—'}
                </td>
                <td className="pr-3 text-right tabular-nums">{snap.uploadCount}</td>
                <td className="pr-3">{snap.hasDb ? '✓' : '—'}</td>
                <td className="text-right">
                  {snap.hasDb && (
                    // F4: plain link — the session cookie authenticates it.
                    <a
                      href={backupDownloadUrl(kind, snap.name)}
                      download={`${snap.name}.sqlite3`}
                      className="mr-2 rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-50"
                    >
                      Download
                    </a>
                  )}
                  <button
                    onClick={() => onRestore(kind, snap.name)}
                    disabled={busy || !snap.hasDb}
                    className="rounded border border-amber-400 px-2 py-0.5 text-amber-700 hover:bg-amber-50 disabled:opacity-40"
                  >
                    Restore…
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/** Settings v1: appearance (theme), backups (J16 endpoints), integrations.
 *  Wave 2 (perf): memoised — its only prop is the `active` boolean. */
const SettingsPage = memo(function SettingsPage({ active }: SettingsPageProps) {
  // B13: prefs read through safeStorage.
  const [theme, setTheme] = useState<ThemePref>(() => loadThemePref(safeStorage))
  const [newDealType, setNewDealType] = useState<NewDealTypePref>(() => loadNewDealTypePref(safeStorage))
  const [backups, setBackups] = useState<{ daily: BackupSnapshot[]; weekly: BackupSnapshot[] } | null>(null)
  const [integrations, setIntegrations] = useState<IntegrationStatus[] | null>(null)
  const [auth, setAuth] = useState<AuthStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!active) return
    fetchBackups().then(setBackups).catch(() => setBackups(null))
    fetchIntegrations().then(setIntegrations).catch(() => setIntegrations(null))
    fetchAuthStatus().then(setAuth).catch(() => setAuth(null))
  }, [active])

  function handleTheme(pref: ThemePref) {
    setTheme(pref)
    setThemePref(pref)
  }

  function handleNewDealType(pref: NewDealTypePref) {
    setNewDealType(pref)
    saveNewDealTypePref(safeStorage, pref)
  }

  // F1: end the cookie session, then raise the gate (same path as a 401).
  async function handleSignOut() {
    setError(null)
    try {
      await logout()
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign out failed.')
    }
  }

  async function handleBackupNow() {
    setBusy(true)
    setNotice(null)
    setError(null)
    try {
      const result = await runBackupNow()
      setNotice(`Snapshot ${result.created} created.`)
      setBackups(await fetchBackups())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Backup failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handleRestore(kind: string, name: string) {
    const sure = window.confirm(
      `Restore snapshot ${kind}/${name}?\n\nThis OVERWRITES the live database with the ` +
        'snapshot state. You must restart the backend afterward so the restored ' +
        'database is loaded.',
    )
    if (!sure) return
    setBusy(true)
    setNotice(null)
    setError(null)
    try {
      const result = await restoreBackup(kind, name)
      setNotice(
        `Restored ${result.restored}. ${result.note} The snapshot's manifest lists ` +
          `${result.uploads.length} upload file(s) that should still exist on disk.`,
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Restore failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-4">
      <h2 className="text-sm font-semibold text-slate-700">Settings</h2>
      {notice && (
        <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {notice}
        </div>
      )}
      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      <Section title="APPEARANCE">
        <div className="flex flex-wrap gap-4">
          {THEME_OPTIONS.map((option) => (
            <label key={option.value} className="flex items-center gap-1.5 text-sm text-slate-700">
              <input
                type="radio"
                name="theme"
                checked={theme === option.value}
                onChange={() => handleTheme(option.value)}
              />
              {option.label}
              <span className="text-[11px] text-slate-400">({option.hint})</span>
            </label>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-slate-400">
          Stored in this browser. Generated documents (memo charts, decks, Excel) keep
          their light rendering by design.
        </p>
      </Section>

      <Section title="WORKFLOW">
        <div className="text-xs font-medium text-slate-600">Default type for "New Deal"</div>
        <div className="mt-1 flex flex-wrap gap-4">
          {NEW_DEAL_TYPE_OPTIONS.map((option) => (
            <label key={option.value} className="flex items-center gap-1.5 text-sm text-slate-700">
              <input
                type="radio"
                name="newDealType"
                checked={newDealType === option.value}
                onChange={() => handleNewDealType(option.value)}
              />
              {option.label}
              <span className="text-[11px] text-slate-400">({option.hint})</span>
            </label>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-slate-400">
          The last workflow tab you were on is remembered automatically and reopened on the
          next visit. Both prefs are stored in this browser.
        </p>
      </Section>

      {auth?.required && (
        <Section title="SESSION">
          <div className="flex items-center gap-3">
            <button
              onClick={() => void handleSignOut()}
              className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              Sign out
            </button>
            <span className="text-[11px] text-slate-400">
              Ends this browser's API-token session; you will be asked for the token again.
            </span>
          </div>
        </Section>
      )}

      <Section title="BACKUPS">
        <div className="flex items-center gap-3">
          <button
            onClick={() => void handleBackupNow()}
            disabled={busy}
            className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-700 disabled:opacity-40"
          >
            {busy ? 'Working…' : 'Back up now'}
          </button>
          <span className="text-[11px] text-slate-400">
            Consistent SQLite snapshot (online-backup API) + an uploads manifest.
            Rotation keeps 7 daily / 4 weekly.
          </span>
        </div>
        {backups === null ? (
          <div className="mt-3 text-xs text-slate-400">
            Backups unavailable — is the backend reachable?
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            <SnapshotTable kind="daily" snapshots={backups.daily} onRestore={handleRestore} busy={busy} />
            <SnapshotTable kind="weekly" snapshots={backups.weekly} onRestore={handleRestore} busy={busy} />
          </div>
        )}
      </Section>

      <Section title="INTEGRATIONS">
        {integrations === null ? (
          <div className="text-xs text-slate-400">Status unavailable.</div>
        ) : (
          <ul className="space-y-2">
            {integrations.map((item) => (
              <li key={item.envVar} className="flex items-start gap-2 text-xs">
                <span
                  aria-label={item.configured ? 'configured' : 'not configured'}
                  className={`mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full ${
                    item.configured ? 'bg-emerald-500' : 'bg-slate-300'
                  }`}
                />
                <div>
                  <span className="font-medium text-slate-700">{item.label}</span>{' '}
                  <span className={item.configured ? 'text-emerald-600' : 'text-slate-400'}>
                    {item.configured ? 'configured' : 'not set'}
                  </span>
                  <span className="ml-1 font-mono text-[10px] text-slate-400">{item.envVar}</span>
                  <div className="text-slate-500">{item.purpose}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-[11px] text-slate-400">
          Keys are set in <code>backend/.env</code> (see <code>.env.example</code>) or the
          Docker compose environment — values never leave the server; this panel only
          shows whether each is present. Every source degrades gracefully when unset.
        </p>
      </Section>
    </div>
  )
})

export default SettingsPage
