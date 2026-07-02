export interface SourceRef {
  doc?: string | null
  page?: number | null
  sheet?: string | null
  cell?: string | null
  row?: number | null
}

export interface ExtractedField {
  value: unknown
  sourceRef: SourceRef
  confidence: number
  source: 'deterministic' | 'llm'
  rawText?: string | null
  notes?: string | null
}

export interface UnmatchedExtraction {
  suggestedLabel: string
  value: unknown
  rawText?: string | null
  sourceRef: SourceRef
  confidence: number
}

export interface CrossValidationCheck {
  severity: 'warning' | 'info'
  message: string
  relatedFieldIds: string[]
}

export interface ExtractionResult {
  id: string
  documentIds: string[]
  fields: Record<string, ExtractedField>
  unmatched: UnmatchedExtraction[]
  crossValidation: CrossValidationCheck[]
  warnings: string[]
  confirmedValues: Record<string, unknown>
  confirmedAt: string | null
  createdAt: string
}
