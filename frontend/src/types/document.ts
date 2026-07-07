export type DocumentType = 'offering_memorandum' | 'rent_roll' | 't12_operating_statement' | 'other'
export type ClassificationSource = 'heuristic' | 'llm' | 'manual'

export interface DocumentSummary {
  id: string
  filename: string
  fileHash: string
  fileExt: string
  dealId: string | null
  documentType: DocumentType
  typeConfidence: number
  typeSource: ClassificationSource
  typeRationale: string
  createdAt: string
  /** True when an upload deduplicated onto an existing record (same content). */
  reused?: boolean
}

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  offering_memorandum: 'Offering Memorandum',
  rent_roll: 'Rent Roll',
  t12_operating_statement: 'T-12 / Operating Statement',
  other: 'Other',
}
