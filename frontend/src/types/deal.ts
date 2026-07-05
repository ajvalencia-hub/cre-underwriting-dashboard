export type DealStatus =
  | 'screening'
  | 'underwriting'
  | 'loi'
  | 'under_contract'
  | 'closed'
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
