export interface Scenario {
  id: string
  scenarioName: string
  templateId: string
  mappingProfileId: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  createdAt: string
  updatedAt: string
}
