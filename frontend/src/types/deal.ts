// The union of both dealflows' stages (see lib/dealStages.ts + the backend
// registry in input_schema.json). Acquisition: screening → underwriting →
// loi → under_contract → closed. Development: screening → feasibility →
// site_control → entitlements → pre_construction → construction → lease_up
// → stabilized. Both end in dead.
export type DealStatus =
  | 'screening'
  | 'underwriting'
  | 'loi'
  | 'under_contract'
  | 'closed'
  | 'feasibility'
  | 'site_control'
  | 'entitlements'
  | 'pre_construction'
  | 'construction'
  | 'lease_up'
  | 'stabilized'
  | 'dead'

export interface Deal {
  id: string
  name: string
  inputs: Record<string, unknown>
  status: DealStatus
  activeTemplateId: string | null
  activeMappingProfileId: string | null
  createdAt: string
  updatedAt: string
  /** Soft-delete marker (F2): set = archived, hidden from the default list. */
  archivedAt?: string | null
  /** Free-text labels (wave 2); optional until every backend build emits it. */
  tags?: string[]
}

/** `GET /api/deals?fields=summary`: no inputs blob, just the headline facts. */
export interface DealSummaryRow extends Omit<Deal, 'inputs'> {
  summary: { dealType: string | null; dealName: string; address: string; market: string }
}
