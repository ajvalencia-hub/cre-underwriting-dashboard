export type PreviewStatus =
  | 'ok'
  | 'unitWarning'
  | 'blank'
  | 'formula'
  | 'multiCell'
  | 'unresolved'
  | 'tableSkips'
  | 'unmapped'
  | 'output'

/** One row of POST /api/mappings/preview — what Generate would do with a field. */
export interface MappingPreviewRow {
  fieldId: string
  isOutput: boolean
  hasValue: boolean
  status: PreviewStatus
  target?: 'cell' | 'namedRange' | 'table'
  resolvedRef: string | null
  mergedFrom?: string
  cellValue?: string | number | boolean | null
  cellFormula?: string | null
  numberFormat?: string
  isFormula?: boolean
  writeValue?: string | number | boolean | null
  tableRows?: number
  tableColumns?: number
  message?: string | null
  /** Client-derived: other fields (same kind — input or output) resolving
   *  to this same cell. Inputs sharing a cell overwrite each other. */
  sharedWith?: string[]
}
