import { useMemo, useState } from 'react'
import { addIcStep, type IcStepKind, type IcSummary } from '../lib/api'
import { formatOutputValue } from '../lib/formatValue'
import { headlineIds } from '../lib/headlineMetrics'
import {
  IC_STATE_LABELS,
  IC_STATE_STYLES,
  STEP_BUTTON_LABELS,
  allowedSteps,
  describeEvent,
  isLockedField,
  needsReason,
  statusLine,
} from '../lib/icWorkflow'
import { diffSnapshots, formatDiffValue } from '../lib/snapshotDiff'
import { toastError } from '../lib/toast'
import type { InputSchema, OutputMetric } from '../types/schema'

const ACTOR_KEY = 'cre.icActor'
const SHOWN_CHANGES = 15

function rememberedActor(): string {
  try {
    return localStorage.getItem(ACTOR_KEY) ?? ''
  } catch {
    return ''
  }
}

interface Props {
  dealId: string | null
  schema: InputSchema
  /** The Deal Inputs on screen, to show what changed since the IC version. */
  values: Record<string, unknown>
  /** The newest computed value of each output, beside the IC version's. */
  currentOutputs: Record<string, unknown>
  summary: IcSummary | null
  /** Saves pending edits first, so a submission stores what's on screen
   *  (and a save can't land on a deal that just locked). False = don't go on. */
  onBeforeStep: () => Promise<boolean>
  onSummary: (summary: IcSummary) => void
}

/** Roadmap #28: put the deal to the investment committee, record each
 *  member's decision with a name and reason, and keep the version they saw. */
export default function IcApprovalPage({
  dealId,
  schema,
  values,
  currentOutputs,
  summary,
  onBeforeStep,
  onSummary,
}: Props) {
  const [actor, setActor] = useState(rememberedActor)
  const [comment, setComment] = useState('')
  const [requiredApprovals, setRequiredApprovals] = useState(1)
  const [busy, setBusy] = useState(false)

  const submission = summary?.lastSubmission ?? null
  const changes = useMemo(() => {
    if (!submission) return null
    const now = Object.fromEntries(Object.entries(values).filter(([k]) => isLockedField(k)))
    return diffSnapshots(submission.inputs, now, schema)
  }, [submission, values, schema])

  if (!dealId || !summary) {
    return <p className="text-sm text-slate-500">Loading the investment-committee record…</p>
  }

  async function take(kind: IcStepKind) {
    if (!dealId) return
    setBusy(true)
    try {
      if (!(await onBeforeStep())) return
      const next = await addIcStep(dealId, {
        kind,
        actor,
        comment,
        ...(kind === 'submit' ? { requiredApprovals } : {}),
      })
      try {
        localStorage.setItem(ACTOR_KEY, actor.trim())
      } catch {
        // not remembering the name is harmless
      }
      setComment('')
      onSummary(next)
    } catch (err) {
      toastError(`Couldn't ${STEP_BUTTON_LABELS[kind].toLowerCase()}`, err)
    } finally {
      setBusy(false)
    }
  }

  const steps = allowedSteps(summary.state)
  const nameMissing = actor.trim() === ''
  // The go/no-go read first (as in the summary panel); the rest on request.
  const headline = headlineIds(submission?.inputs.dealType)
  const withValue = schema.outputs.filter((m) => submission && submission.outputs[m.id] !== undefined)
  const headlineMetrics = headline.flatMap((id) => withValue.filter((m) => m.id === id))
  const otherMetrics = withValue.filter((m) => !headline.includes(m.id))

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">Investment committee</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className={`rounded px-2 py-0.5 text-xs font-semibold ${IC_STATE_STYLES[summary.state]}`}>
            {IC_STATE_LABELS[summary.state]}
          </span>
          <span className="text-sm text-slate-600">{statusLine(summary)}</span>
        </div>
      </div>

      <section className="rounded-md border border-slate-200 bg-white p-4">
        <div className="grid gap-3 sm:grid-cols-[14rem_1fr]">
          <label className="text-sm text-slate-700">
            Your name
            <input
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
              placeholder="Recorded with each step"
            />
          </label>
          <label className="text-sm text-slate-700">
            Comment or reason
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
              placeholder="Required to return, reject, reopen or comment"
            />
          </label>
        </div>
        {summary.state === 'draft' && (
          <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
            Approvals needed
            <input
              type="number"
              min={1}
              max={9}
              value={requiredApprovals}
              onChange={(e) => setRequiredApprovals(Math.min(9, Math.max(1, Number(e.target.value) || 1)))}
              className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <span className="text-xs text-slate-500">distinct people</span>
          </label>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {steps.map((kind) => {
            const blocked = busy || nameMissing || (needsReason(kind) && comment.trim() === '')
            const primary = kind === 'submit' || kind === 'approve'
            return (
              <button
                key={kind}
                onClick={() => void take(kind)}
                disabled={blocked}
                className={`rounded px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 ${
                  primary
                    ? 'bg-slate-900 text-white hover:bg-slate-700'
                    : kind === 'reject'
                      ? 'border border-red-300 text-red-700 hover:bg-red-50'
                      : 'border border-slate-300 text-slate-700 hover:bg-slate-50'
                }`}
              >
                {STEP_BUTTON_LABELS[kind]}
              </button>
            )
          })}
        </div>
        {summary.state === 'draft' && (
          <p className="mt-2 text-xs text-slate-500">
            Submitting computes the deal and keeps that version for the committee. Its underwriting inputs are
            then locked until it's returned or reopened; the Quick Screen and critical dates stay editable.
          </p>
        )}
      </section>

      {submission && (
        <section className="rounded-md border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-900">
            Version put to the committee
            <span className="ml-2 font-normal text-slate-500">
              {submission.submittedBy}, {new Date(submission.submittedAt).toLocaleString()}
              {!submission.current && ' · since returned or reopened'}
            </span>
          </h3>
          <MetricTable metrics={headlineMetrics} ic={submission.outputs} current={currentOutputs} />
          {otherMetrics.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-slate-600">
                All {otherMetrics.length} other metrics
              </summary>
              <MetricTable metrics={otherMetrics} ic={submission.outputs} current={currentOutputs} />
            </details>
          )}
          {changes && (
            <div className="mt-4">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Inputs changed since this version
              </h4>
              {changes.scalars.length === 0 && changes.tables.length === 0 ? (
                <p className="mt-1 text-sm text-slate-600">None — the inputs match what the committee saw.</p>
              ) : (
                <ul className="mt-1 space-y-0.5 text-sm text-slate-700">
                  {changes.scalars.slice(0, SHOWN_CHANGES).map((c) => (
                    <li key={c.fieldId}>
                      {c.label}: {formatDiffValue(c.before, c.type)} → {formatDiffValue(c.after, c.type)}
                    </li>
                  ))}
                  {changes.scalars.length > SHOWN_CHANGES && (
                    <li className="text-slate-500">…and {changes.scalars.length - SHOWN_CHANGES} more</li>
                  )}
                  {changes.tables.map((t) => (
                    <li key={t.fieldId}>
                      {t.label}: {t.rows.length} row{t.rows.length === 1 ? '' : 's'} changed
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      )}

      <section>
        <h3 className="text-sm font-semibold text-slate-900">Record</h3>
        {summary.events.length === 0 ? (
          <p className="mt-1 text-sm text-slate-500">Nothing recorded yet.</p>
        ) : (
          <ol className="mt-2 space-y-2">
            {[...summary.events].reverse().map((event) => (
              <li key={event.id} className="rounded border border-slate-200 bg-white px-3 py-2 text-sm">
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="text-slate-800">{describeEvent(event)}</span>
                  <span className="text-xs text-slate-500">{new Date(event.createdAt).toLocaleString()}</span>
                </div>
                {event.comment && <p className="mt-1 whitespace-pre-wrap text-slate-600">{event.comment}</p>}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}

function MetricTable({
  metrics,
  ic,
  current,
}: {
  metrics: OutputMetric[]
  ic: Record<string, unknown>
  current: Record<string, unknown>
}) {
  return (
    <table className="mt-3 w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-slate-500">
          <th className="py-1 font-medium">Metric</th>
          <th className="py-1 text-right font-medium">IC version</th>
          <th className="py-1 text-right font-medium">Latest compute</th>
        </tr>
      </thead>
      <tbody>
        {metrics.map((metric) => (
          <tr key={metric.id} className="border-t border-slate-100">
            <td className="py-1 text-slate-700">{metric.label}</td>
            <td className="py-1 text-right tabular-nums">{formatOutputValue(metric, ic[metric.id])}</td>
            <td className="py-1 text-right tabular-nums text-slate-600">
              {current[metric.id] === undefined ? '—' : formatOutputValue(metric, current[metric.id])}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
