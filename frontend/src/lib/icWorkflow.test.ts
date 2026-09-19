import { describe, expect, it } from 'vitest'
import { allowedSteps, describeEvent, isLockedField, needsReason, statusLine } from './icWorkflow'
import type { IcEvent, IcSummary } from './api'

const summary = (patch: Partial<IcSummary>): IcSummary => ({
  state: 'draft',
  locked: false,
  requiredApprovals: null,
  approvers: [],
  lastSubmission: null,
  events: [],
  ...patch,
})

describe('icWorkflow', () => {
  it('offers the steps the server allows in each state', () => {
    expect(allowedSteps('draft')).toEqual(['submit', 'comment'])
    expect(allowedSteps('approved')).toEqual(['reopen', 'comment'])
    expect(allowedSteps('submitted')).toContain('approve')
  })

  it('asks for a reason to reject, return, reopen or comment', () => {
    expect(needsReason('submit')).toBe(false)
    expect(needsReason('approve')).toBe(false)
    expect(needsReason('reopen')).toBe(true)
  })

  it('keeps the napkin and dates editable while locked', () => {
    expect(isLockedField('purchasePrice')).toBe(true)
    expect(isLockedField('criticalDates')).toBe(false)
    expect(isLockedField('quickScreen')).toBe(false)
  })

  it('describes steps and progress in words', () => {
    const submit = { kind: 'submit', actor: 'Ana', requiredApprovals: 2 } as IcEvent
    expect(describeEvent(submit)).toBe('Ana submitted to IC (2 approvals needed)')
    expect(statusLine(summary({ state: 'submitted', requiredApprovals: 2, approvers: ['Ben'] }))).toBe(
      '1 of 2 approvals (Ben). Inputs are locked.',
    )
  })
})
