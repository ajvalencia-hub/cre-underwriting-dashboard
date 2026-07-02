export interface SensitivityDriver {
  fieldId: string
  values: number[]
}

export interface SensitivityPoint {
  driverValues: Record<string, number>
  outputs: Record<string, unknown>
  warnings: string[]
}

export interface SensitivityResponse {
  points: SensitivityPoint[]
}
