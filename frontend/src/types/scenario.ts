export type ScenarioKind = 'quickscreen' | 'full'

export interface Scenario {
  id: string
  scenarioName: string
  kind: ScenarioKind
  templateId: string | null
  mappingProfileId: string | null
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  createdAt: string
  updatedAt: string
}
