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

export interface UsageBucket {
  calls: number
  inputTokens: number
  outputTokens: number
  costUsd: number
  unknownCostCalls: number
}

export interface UsageSummary {
  thisDeal: UsageBucket | null
  today: UsageBucket
  thisMonth: UsageBucket
  byTask: Record<string, UsageBucket>
  budget: {
    monthlyBudgetUsd: number | null
    spentUsd: number
    softWarn: boolean
    hardStopped: boolean
  }
}
