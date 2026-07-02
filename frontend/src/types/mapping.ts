export type MappingTarget = 'namedRange' | 'cell' | 'table'
export type MappingSource = 'auto' | 'manual'

export interface MappingEntry {
  target: MappingTarget
  ref?: string | null
  anchor?: string | null
  sheet?: string | null
  columnOrder?: string[] | null
  source: MappingSource
}

export type MappingsById = Record<string, MappingEntry>

export interface MappingProfile {
  id: string
  templateId: string
  profileName: string
  mappings: MappingsById
  unmappedRequiredFields: string[]
  createdAt: string
  updatedAt: string
}

export interface AutoMatchResult {
  mappings: MappingsById
}
