export interface SettingEntry {
  key: string
  category: string
  label: string
  isSecret: boolean
  source: 'db' | 'env' | 'default'
  value?: string
  isSet?: boolean
  last4?: string | null
}

export interface ProviderHealth {
  reachable: boolean
  detail: string | null
}

export type ProviderHealthMap = Record<string, ProviderHealth>
