export type FieldType =
  | 'text'
  | 'number'
  | 'currency'
  | 'percent'
  | 'date'
  | 'select'
  | 'multiselect'
  | 'boolean'
  | 'table'
  | 'keyvalue'

export interface FieldCondition {
  field: string
  equals?: string | number | boolean
  contains?: string
}

export interface VisibleWhen {
  all?: FieldCondition[]
  any?: FieldCondition[]
}

export interface TableColumn {
  id: string
  label: string
  type: FieldType
  options?: string[]
}

export interface InputField {
  id: string
  label: string
  type: FieldType
  required?: boolean
  min?: number
  max?: number
  default?: string | number | boolean
  options?: string[]
  columns?: TableColumn[]
  minRows?: number
  maxRows?: number
  visibleWhen?: VisibleWhen
}

export interface InputSection {
  id: string
  label: string
  visibleWhen: VisibleWhen | null
  fields: InputField[]
}

export interface OutputMetric {
  id: string
  label: string
  type: 'percent' | 'multiple' | 'currency' | 'years' | 'number'
  group?: string
}

export interface InputSchema {
  version: number
  dealTypes: string[]
  propertyTypes: string[]
  outputs: OutputMetric[]
  sections: InputSection[]
}
