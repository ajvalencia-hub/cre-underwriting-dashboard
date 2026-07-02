export interface MarketComp {
  name: string
  submarket: string
  type: 'sale' | 'lease'
  date: string
  pricePerUnit: number
  priceUnitLabel: string
  capRate: number
}

export interface MarketPricingTrends {
  capRateLow: number
  capRateHigh: number
  priceLow: number
  priceHigh: number
  priceUnitLabel: string
}

export interface MarketRentTrends {
  rentGrowthYoY: number
  vacancyPct: number
}

export interface MarketLocation {
  resolved: boolean
  lat?: number
  lon?: number
  countyName?: string
  cbsaName?: string
  [key: string]: unknown
}

// These sections come from real, free government data sources and always
// include at least "dataSource" ("unavailable" plus a "note" when the
// relevant API key isn't configured, or the real fields otherwise).
export type DataSection = { dataSource: string; note?: string; [key: string]: unknown }

export interface MarketContext {
  market: string
  submarket: string
  assetClass: string
  location: MarketLocation
  comps: MarketComp[]
  pricingTrends: MarketPricingTrends
  rentTrends: MarketRentTrends
  demographics: DataSection
  laborMarket: DataSection
  housing: DataSection
  macro: DataSection
  siteRisk: DataSection
  meta: { dataSource: string; note: string }
}
