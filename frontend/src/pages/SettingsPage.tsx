import { useEffect, useState } from 'react'
import {
  deleteSetting,
  fetchProviderHealth,
  fetchSettings,
  fetchUsageSummary,
  updateSetting,
} from '../lib/api'
import SettingRow from '../components/settings/SettingRow'
import type { ProviderHealthMap, SettingEntry, UsageSummary } from '../types/settings'

const CATEGORY_LABELS: Record<string, string> = {
  aiProviders: 'AI Providers',
  modelRouting: 'Model Routing',
  branding: 'Branding',
  limits: 'Limits',
  publicData: 'Public Data',
  map: 'Map',
  usage: 'Usage',
}

// Display order — categories not listed here (shouldn't happen, but a
// forward-compat catch-all) render after these, alphabetically.
const CATEGORY_ORDER = ['aiProviders', 'modelRouting', 'branding', 'limits', 'publicData', 'map', 'usage']

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`
}

function UsageSummaryBlock() {
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchUsageSummary()
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  if (error) return <div className="px-4 py-2 text-xs text-red-600">Failed to load usage: {error}</div>
  if (!summary) return <div className="px-4 py-2 text-xs text-slate-400">Loading usage…</div>

  const { today, thisMonth, byTask, budget } = summary

  return (
    <div className="space-y-3 border-b border-slate-100 px-4 py-3">
      <div className="flex flex-wrap gap-6 text-sm">
        <div>
          <div className="text-xs text-slate-400">Today</div>
          <div className="text-slate-700">
            {today.calls} calls · {today.inputTokens + today.outputTokens} tokens · {formatUsd(today.costUsd)}
          </div>
        </div>
        <div>
          <div className="text-xs text-slate-400">This month</div>
          <div className="text-slate-700">
            {thisMonth.calls} calls · {thisMonth.inputTokens + thisMonth.outputTokens} tokens ·{' '}
            {formatUsd(thisMonth.costUsd)}
            {thisMonth.unknownCostCalls > 0 && (
              <span className="text-slate-400"> (+{thisMonth.unknownCostCalls} unknown-cost calls)</span>
            )}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-slate-500">
        {Object.entries(byTask).map(([task, bucket]) => (
          <div key={task}>
            {task}: {bucket.calls} calls, {formatUsd(bucket.costUsd)}
          </div>
        ))}
      </div>
      {budget.monthlyBudgetUsd !== null && (
        <div
          className={
            budget.hardStopped
              ? 'text-xs font-medium text-red-600'
              : budget.softWarn
                ? 'text-xs font-medium text-amber-600'
                : 'text-xs text-slate-500'
          }
        >
          {formatUsd(budget.spentUsd)} of {formatUsd(budget.monthlyBudgetUsd)} monthly budget spent
          {budget.hardStopped && ' — write proposals are currently disabled until the budget is raised.'}
          {!budget.hardStopped && budget.softWarn && ' — approaching the limit.'}
        </div>
      )}
    </div>
  )
}

const HEALTH_PROVIDER_FOR_KEY: Record<string, string> = {
  anthropicApiKey: 'anthropic',
  openaiApiKey: 'openai',
  ollamaBaseUrl: 'ollama',
}

function groupByCategory(entries: SettingEntry[]): [string, SettingEntry[]][] {
  const groups = new Map<string, SettingEntry[]>()
  for (const entry of entries) {
    const list = groups.get(entry.category) ?? []
    list.push(entry)
    groups.set(entry.category, list)
  }
  const known = CATEGORY_ORDER.filter((c) => groups.has(c))
  const unknown = [...groups.keys()].filter((c) => !CATEGORY_ORDER.includes(c)).sort()
  return [...known, ...unknown].map((c) => [c, groups.get(c) ?? []])
}

export default function SettingsPage() {
  const [entries, setEntries] = useState<SettingEntry[] | null>(null)
  const [health, setHealth] = useState<ProviderHealthMap | null>(null)
  const [healthLoading, setHealthLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function reload() {
    fetchSettings()
      .then(setEntries)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    reload()
  }, [])

  async function testConnections() {
    setHealthLoading(true)
    try {
      setHealth(await fetchProviderHealth())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setHealthLoading(false)
    }
  }

  async function handleSave(key: string, value: string) {
    await updateSetting(key, value)
    reload()
  }

  async function handleRevert(key: string) {
    await deleteSetting(key)
    reload()
  }

  if (error) {
    return <div className="text-sm text-red-600">Failed to load settings: {error}</div>
  }
  if (!entries) {
    return <div className="text-sm text-slate-400">Loading settings…</div>
  }

  return (
    <div className="space-y-6">
      {groupByCategory(entries).map(([category, categoryEntries]) => (
        <div key={category} className="rounded-md border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
            <div className="text-sm font-semibold text-slate-700">
              {CATEGORY_LABELS[category] ?? category}
            </div>
            {category === 'aiProviders' && (
              <button
                type="button"
                disabled={healthLoading}
                onClick={() => void testConnections()}
                className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              >
                {healthLoading ? 'Testing…' : 'Test connection'}
              </button>
            )}
          </div>
          {category === 'usage' && <UsageSummaryBlock />}
          <div className="px-4">
            {categoryEntries.map((entry) => {
              const healthProvider = HEALTH_PROVIDER_FOR_KEY[entry.key]
              const status = healthProvider && health ? health[healthProvider] : undefined
              return (
                <SettingRow
                  key={entry.key}
                  entry={entry}
                  onSave={handleSave}
                  onRevert={handleRevert}
                  helperText={
                    status
                      ? status.reachable
                        ? 'Reachable ✓'
                        : `Unreachable${status.detail ? ` — ${status.detail}` : ''}`
                      : undefined
                  }
                />
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
