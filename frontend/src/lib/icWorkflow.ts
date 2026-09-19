// Roadmap #28: investment-committee sign-off, UI side. The rules mirror
// backend/app/services/ic_workflow.py, which enforces them; these only
// decide what to offer and how to say it.

import type { IcEvent, IcState, IcStepKind, IcSummary } from './api'

export const IC_STATE_LABELS: Record<IcState, string> = {
  draft: 'Draft',
  submitted: 'Submitted to IC',
  approved: 'IC approved',
  rejected: 'IC rejected',
}

export const IC_STATE_STYLES: Record<IcState, string> = {
  draft: 'bg-slate-100 text-slate-600',
  submitted: 'bg-amber-100 text-amber-800',
  approved: 'bg-emerald-100 text-emerald-800',
  rejected: 'bg-red-100 text-red-700',
}

const ALLOWED: Record<IcState, IcStepKind[]> = {
  draft: ['submit', 'comment'],
  submitted: ['approve', 'return', 'reject', 'reopen', 'comment'],
  approved: ['reopen', 'comment'],
  rejected: ['reopen', 'comment'],
}

export function allowedSteps(state: IcState): IcStepKind[] {
  return ALLOWED[state]
}

/** Saying no, sending back, reopening and commenting need words. */
export function needsReason(kind: IcStepKind): boolean {
  return kind === 'reject' || kind === 'return' || kind === 'reopen' || kind === 'comment'
}

export const STEP_BUTTON_LABELS: Record<IcStepKind, string> = {
  submit: 'Submit to IC',
  approve: 'Approve',
  return: 'Return for changes',
  reject: 'Reject',
  reopen: 'Reopen for edits',
  comment: 'Add comment',
}

/** Inputs that stay editable while the deal is locked (not underwriting). */
const UNLOCKED_KEYS = new Set(['quickScreen', 'acquisitionQuickScreen', 'criticalDates', '_provenance'])

export function isLockedField(fieldId: string): boolean {
  return !UNLOCKED_KEYS.has(fieldId)
}

export function describeEvent(event: IcEvent): string {
  switch (event.kind) {
    case 'submit': {
      const needed = event.requiredApprovals ?? 1
      return `${event.actor} submitted to IC (${needed} approval${needed === 1 ? '' : 's'} needed)`
    }
    case 'approve':
      return `${event.actor} approved`
    case 'reject':
      return `${event.actor} rejected`
    case 'return':
      return `${event.actor} returned it for changes`
    case 'reopen':
      return `${event.actor} reopened it for edits`
    case 'comment':
      return `${event.actor} commented`
  }
}

/** One line under the state badge. */
export function statusLine(summary: IcSummary): string {
  const sub = summary.lastSubmission
  switch (summary.state) {
    case 'draft':
      return sub
        ? 'Open for edits. The last version put to the committee is shown below.'
        : 'Not yet put to the investment committee.'
    case 'submitted': {
      const needed = summary.requiredApprovals ?? 1
      const who = summary.approvers.length ? ` (${summary.approvers.join(', ')})` : ''
      return `${summary.approvers.length} of ${needed} approval${needed === 1 ? '' : 's'}${who}. Inputs are locked.`
    }
    case 'approved':
      return `Approved by ${summary.approvers.join(', ')}. Inputs are locked.`
    case 'rejected':
      return 'Inputs are locked until the deal is reopened.'
  }
}
