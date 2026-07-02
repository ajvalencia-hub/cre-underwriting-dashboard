export interface SheetMeta {
  name: string
  maxRow: number
  maxCol: number
}

export interface NamedRangeMeta {
  name: string
  sheet: string
  ref: string
}

export interface TemplateSummary {
  id: string
  filename: string
  fileHash: string
  createdAt: string
  sheets: SheetMeta[]
  namedRanges: NamedRangeMeta[]
  reused: boolean
}

export interface GridCell {
  ref: string
  value: string | number | boolean | null
  isFormula: boolean
}

export interface SheetGrid {
  sheet: string
  columns: string[]
  rows: GridCell[][]
  totalRows: number
  totalCols: number
}
