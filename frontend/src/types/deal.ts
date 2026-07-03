export interface Deal {
  id: string
  name: string
  inputs: Record<string, unknown>
  activeTemplateId: string | null
  activeMappingProfileId: string | null
  createdAt: string
  updatedAt: string
}
