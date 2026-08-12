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
}
