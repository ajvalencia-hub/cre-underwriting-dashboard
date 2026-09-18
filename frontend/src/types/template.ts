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
  numberFormat?: string
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
  /** 1-based row number of rows[0] (the grid is a window of the sheet). */
  startRow?: number
}
