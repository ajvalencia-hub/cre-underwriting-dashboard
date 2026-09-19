import { useEffect, useState } from 'react'
import { ExternalToolsPanel, KeychainKeyRow, RestartBanner } from '../components/DesktopSettings'
import {
  fetchBackups,
  fetchExternalTools,
  fetchIntegrations,
  restoreBackup,
  runBackupNow,
  type AutomaticBackupStatus,
  type BackupKind,
  type BackupListing,
  type BackupSnapshot,
  type ExternalToolsStatus,
  type IntegrationStatus,
} from '../lib/api'
import { isDesktop } from '../lib/platform'
import { useDesktopSettings } from '../lib/useDesktopSettings'
import { loadThemePref, setThemePref, type ThemePref } from '../lib/uiPrefs'

interface SettingsPageProps {
  active: boolean
}

const THEME_OPTIONS: { value: ThemePref; label: string; hint: string }[] = [
  { value: 'light', label: 'Light', hint: 'Always light' },
  { value: 'dark', label: 'Dark', hint: 'Always dark' },
  { value: 'system', label: 'System', hint: 'Follow the OS setting' },
]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold tracking-wide text-slate-500">{title}</div>
      <div className="mt-3">{children}</div>
    </div>
  )
}

const KIND_LABEL: Record<BackupKind, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  pre_restore: 'Before restore',
  pre_migration: 'Before app update',
}

function SnapshotTable({
  kind,
  snapshots,
  onRestore,
  busy,
}: {
  kind: BackupKind
  snapshots: BackupSnapshot[]
  onRestore: (kind: BackupKind, name: string) => void
  busy: boolean
}) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {KIND_LABEL[kind]} ({snapshots.length})
      </div>
      {snapshots.length === 0 ? (
        <div className="mt-1 text-xs text-slate-500">No {KIND_LABEL[kind].toLowerCase()} snapshots yet.</div>
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

/** Automatic backups used to fail silently — say when one did. */
function AutomaticBackupLine({ status }: { status: AutomaticBackupStatus }) {
  const when = new Date(status.at).toLocaleString()
  if (!status.ok) {
    return (
      <div className="mt-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">
        The automatic backup at {when} failed: {status.error}. Use “Back up now”, and check free disk space.
      </div>
    )
  }
  return (
    <div className="mt-2 text-xs text-slate-500">
      Last automatic backup check: {when} —{' '}
      {status.result?.startsWith('skipped') ? 'a recent daily snapshot already existed' : `saved ${status.result}`}.
    </div>
  )
}

/** Settings v1: appearance (theme), backups (J16 endpoints), integrations. */
export default function SettingsPage({ active }: SettingsPageProps) {
  const [theme, setTheme] = useState<ThemePref>(() => loadThemePref(window.localStorage))
  const [backups, setBackups] = useState<BackupListing | null>(null)
  const [integrations, setIntegrations] = useState<IntegrationStatus[] | null>(null)
  const [tools, setTools] = useState<ExternalToolsStatus | null>(null)
  const [desktopSettings, setDesktopSettings] = useDesktopSettings(active)
  const [restoredNeedsRestart, setRestoredNeedsRestart] = useState(false)
  const desktop = isDesktop()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!active) return
    fetchBackups().then(setBackups).catch(() => setBackups(null))
    fetchIntegrations().then(setIntegrations).catch(() => setIntegrations(null))
    fetchExternalTools().then(setTools).catch(() => setTools(null))
  }, [active])

  function handleTheme(pref: ThemePref) {
    setTheme(pref)
    setThemePref(pref)
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

  async function handleRestore(kind: BackupKind, name: string) {
    const sure = window.confirm(
      `Restore snapshot ${kind}/${name}?\n\nThis replaces the live database with the snapshot. ` +
        'Your current data is saved first as a "Before restore" snapshot, so you can undo this. ' +
        `Restart ${desktop ? 'the app' : 'the backend'} afterward so the restored database is loaded.`,
    )
    if (!sure) return
    setBusy(true)
    setNotice(null)
    setError(null)
    try {
      const result = await restoreBackup(kind, name)
      setNotice(
        `Restored ${result.restored}. ${desktop ? 'Restart the app to load it.' : result.note} ` +
          (result.preRestoreSnapshot
            ? `Your data from before the restore is saved as "Before restore" ${result.preRestoreSnapshot}. `
            : '') +
          `The snapshot's manifest lists ${result.uploads.length} upload file(s) that should still exist on disk.`,
      )
      if (desktop) setRestoredNeedsRestart(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Restore failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-4">
      <h2 className="text-sm font-semibold text-slate-700">Settings</h2>
      <RestartBanner
        settings={
          desktopSettings && (desktopSettings.restartNeeded || restoredNeedsRestart)
            ? { ...desktopSettings, restartNeeded: true }
            : desktopSettings
        }
      />
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
            Keeps one per day for 7 days, 4 weekly, and the last 5 taken before a restore.
          </span>
        </div>
        {backups?.lastAutomatic && <AutomaticBackupLine status={backups.lastAutomatic} />}
        {backups === null ? (
          <div className="mt-3 text-xs text-slate-400">
            Backups unavailable — is the backend reachable?
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            <SnapshotTable kind="daily" snapshots={backups.daily} onRestore={handleRestore} busy={busy} />
            <SnapshotTable kind="weekly" snapshots={backups.weekly} onRestore={handleRestore} busy={busy} />
            {backups.pre_restore.length > 0 && (
              <SnapshotTable kind="pre_restore" snapshots={backups.pre_restore} onRestore={handleRestore} busy={busy} />
            )}
            {backups.pre_migration.length > 0 && (
              <SnapshotTable kind="pre_migration" snapshots={backups.pre_migration} onRestore={handleRestore} busy={busy} />
            )}
          </div>
        )}
      </Section>

      <Section title="EXTERNAL TOOLS">
        <ExternalToolsPanel tools={tools} settings={desktopSettings} onSettings={setDesktopSettings} />
      </Section>

      <Section title="INTEGRATIONS">
        {integrations === null ? (
          <div className="text-xs text-slate-400">Status unavailable.</div>
        ) : desktop && desktopSettings ? (
          <ul className="space-y-3">
            {integrations.map((item) => (
              <KeychainKeyRow
                key={item.envVar}
                item={item}
                stored={desktopSettings.storedKeys.includes(item.envVar)}
                onSettings={setDesktopSettings}
              />
            ))}
          </ul>
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
        {desktop ? (
          <p className="mt-3 text-[11px] text-slate-400">
            All optional — every source degrades gracefully when unset. Keys are stored in
            your macOS Keychain, never in a file, and are never shown again after saving.
          </p>
        ) : (
          <p className="mt-3 text-[11px] text-slate-400">
            Keys are set in <code>backend/.env</code> (see <code>.env.example</code>) or the
            Docker compose environment — values never leave the server; this panel only
            shows whether each is present. Every source degrades gracefully when unset.
          </p>
        )}
      </Section>

      {desktopSettings && (
        <Section title="DATA">
          <p className="text-xs text-slate-500">
            Deals, templates, documents and daily backups are stored in{' '}
            <span className="font-mono">{desktopSettings.dataFolder}</span>.
          </p>
        </Section>
      )}
    </div>
  )
}
