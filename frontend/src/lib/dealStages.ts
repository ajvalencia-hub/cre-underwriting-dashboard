// Deal-stage registry: THE frontend source of truth for pipeline stages,
// replacing the hand-copies that used to live in PipelinePage and
// pipelineViews. The stage ID SETS must mirror
// backend/app/data/input_schema.json `dealStages` — a vitest reads that file
// and fails on drift. Acquisitions keep the original six transaction stages
// (zero migration); developments get project-lifecycle stages. The stored
// status column accepts the union, so a legacy status on the "wrong" type
// stays valid — boards surface it as "(legacy)" until the user moves it.

import type { Deal, DealStatus } from '../types/deal'

export type DealType = 'acquisition' | 'development'

export const STAGES_BY_TYPE: Record<DealType, DealStatus[]> = {
  acquisition: ['screening', 'underwriting', 'loi', 'under_contract', 'closed', 'dead'],
  development: [
    'screening', 'feasibility', 'site_control', 'entitlements',
    'pre_construction', 'construction', 'lease_up', 'stabilized', 'dead',
  ],
}

/** Union in registry order (acquisition first, then new development stages). */
export const ALL_STAGES: DealStatus[] = [
  ...STAGES_BY_TYPE.acquisition,
  ...STAGES_BY_TYPE.development.filter((s) => !STAGES_BY_TYPE.acquisition.includes(s)),
]

/** Stages valid for BOTH types — the only bulk options for a mixed selection. */
export const SHARED_STAGES: DealStatus[] = STAGES_BY_TYPE.acquisition.filter((s) =>
  STAGES_BY_TYPE.development.includes(s),
)

export const STAGE_LABELS: Record<DealStatus, string> = {
  screening: 'Screening',
  underwriting: 'Underwriting',
  loi: 'LOI',
  under_contract: 'Under Contract',
  closed: 'Closed',
  feasibility: 'Feasibility',
  site_control: 'Site Control',
  entitlements: 'Entitlements',
  pre_construction: 'Pre-Construction',
  construction: 'Construction',
  lease_up: 'Lease-Up',
  stabilized: 'Stabilized',
  dead: 'Dead',
}

export const STAGE_STYLES: Record<DealStatus, string> = {
  screening: 'bg-slate-100 text-slate-600',
  underwriting: 'bg-sky-100 text-sky-700',
  loi: 'bg-violet-100 text-violet-700',
  under_contract: 'bg-amber-100 text-amber-700',
  closed: 'bg-emerald-100 text-emerald-700',
  feasibility: 'bg-sky-100 text-sky-700',
  site_control: 'bg-violet-100 text-violet-700',
  entitlements: 'bg-indigo-100 text-indigo-700',
  pre_construction: 'bg-amber-100 text-amber-700',
  construction: 'bg-orange-100 text-orange-700',
  lease_up: 'bg-teal-100 text-teal-700',
  stabilized: 'bg-emerald-100 text-emerald-700',
  dead: 'bg-slate-200 text-slate-400',
}

/** Terminal stages: the dealflow is over — staleness never badges, and the
 *  pipeline hides them behind the "show closed" toggle. */
export const TERMINAL_STAGES: DealStatus[] = ['closed', 'stabilized', 'dead']

/** Staleness thresholds (days) per stage. Long-lived development stages get
 *  relaxed thresholds so a deal in entitlement review or under construction
 *  doesn't badge red forever; everything else keeps the original 14/30. */
const DEFAULT_THRESHOLDS = { stale: 14, veryStale: 30 }
const STAGE_THRESHOLDS: Partial<Record<DealStatus, { stale: number; veryStale: number }>> = {
  entitlements: { stale: 45, veryStale: 90 },
  pre_construction: { stale: 30, veryStale: 60 },
  construction: { stale: 45, veryStale: 90 },
  lease_up: { stale: 30, veryStale: 60 },
}

export function stalenessThresholds(status: DealStatus): { stale: number; veryStale: number } {
  return STAGE_THRESHOLDS[status] ?? DEFAULT_THRESHOLDS
}

/** The deal's type from its inputs blob; null = untyped (a legacy or
 *  just-created-empty deal that predates typed creation). */
export function dealTypeOf(deal: Pick<Deal, 'inputs'>): DealType | null {
  const raw = deal.inputs?.dealType
  return raw === 'acquisition' || raw === 'development' ? raw : null
}

export function stagesFor(type: DealType): DealStatus[] {
  return STAGES_BY_TYPE[type]
}

/** Rank for stage-sorting (union order); unknown values sort last. */
export function stageRank(status: DealStatus): number {
  const index = ALL_STAGES.indexOf(status)
  return index === -1 ? ALL_STAGES.length : index
}

/** Options for the status dropdown of one deal: its type's stages, plus its
 *  CURRENT status appended when it isn't in that set (a legacy value —
 *  never silently rewritten, the user moves it). */
export function stageOptionsForDeal(deal: Pick<Deal, 'inputs' | 'status'>): DealStatus[] {
  const type = dealTypeOf(deal)
  const base = type ? stagesFor(type) : ALL_STAGES
  return base.includes(deal.status) ? base : [...base, deal.status]
}

/** Bulk-status options for a selection: one type -> that type's stages;
 *  mixed or untyped -> only the stages shared by both flows. */
export function bulkStageOptions(deals: Pick<Deal, 'inputs'>[]): DealStatus[] {
  const types = new Set(deals.map((d) => dealTypeOf(d)))
  if (types.size === 1) {
    const only = [...types][0]
    if (only !== null) return stagesFor(only)
  }
  return SHARED_STAGES
}
