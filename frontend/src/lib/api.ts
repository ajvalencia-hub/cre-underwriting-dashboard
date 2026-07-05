import type { Statement } from './cashflowStatement'
import type { InputSchema } from '../types/schema'
import type { SheetGrid, TemplateSummary } from '../types/template'
import type { AutoMatchResult, MappingProfile, MappingsById } from '../types/mapping'
import type { Deal } from '../types/deal'
import type { Scenario } from '../types/scenario'
import type { MarketContext } from '../types/marketContext'
import type { DocumentSummary, DocumentType } from '../types/document'
import type { ExtractionResult } from '../types/extraction'
import type { SensitivityDriver, SensitivityResponse } from '../types/sensitivity'

const API_BASE = '/api'

async function extractErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // response wasn't JSON
  }
  return `${res.status} ${res.statusText}`
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  return res.json() as Promise<T>
}

async function postJson<T>(path: string, body: unknown, method: 'POST' | 'PUT' = 'POST'): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  return res.json() as Promise<T>
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'DELETE' })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
}

export function fetchHealth() {
  return getJson<{ status: string }>('/health')
}

export function fetchInputSchema() {
  return getJson<InputSchema>('/schema')
}

export function fetchTemplates() {
  return getJson<TemplateSummary[]>('/templates')
}

export function fetchTemplate(templateId: string) {
  return getJson<TemplateSummary>(`/templates/${templateId}`)
}

export function deleteTemplate(templateId: string) {
  return del(`/templates/${templateId}`)
}

export function deleteMappingProfile(mappingId: string) {
  return del(`/mappings/${mappingId}`)
}

export async function uploadTemplate(file: File): Promise<TemplateSummary> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_BASE}/templates/upload`, { method: 'POST', body: form })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  return res.json() as Promise<TemplateSummary>
}

export function fetchSheetGrid(templateId: string, sheetName: string, maxRows = 60, maxCols = 30) {
  const params = new URLSearchParams({ max_rows: String(maxRows), max_cols: String(maxCols) })
  return getJson<SheetGrid>(
    `/templates/${templateId}/sheets/${encodeURIComponent(sheetName)}/grid?${params}`,
  )
}

export function fetchAutoMatch(templateId: string) {
  return getJson<AutoMatchResult>(`/mappings/auto-match/${templateId}`)
}

export function fetchMappingProfiles(templateId: string) {
  return getJson<MappingProfile[]>(`/mappings?template_id=${templateId}`)
}

export function fetchMappingProfile(mappingId: string) {
  return getJson<MappingProfile>(`/mappings/${mappingId}`)
}

export function saveMappingProfile(payload: {
  templateId: string
  profileName: string
  mappings: MappingsById
}) {
  return postJson<MappingProfile>('/mappings', payload, 'POST')
}

export function updateMappingProfile(
  mappingId: string,
  payload: { templateId: string; profileName: string; mappings: MappingsById },
) {
  return postJson<MappingProfile>(`/mappings/${mappingId}`, payload, 'PUT')
}

export interface GenerateResult {
  blob: Blob
  filename: string
  warnings: string[]
  writtenCount: number
  outputs: Record<string, unknown>
}

export async function generateWorkbook(payload: {
  templateId: string
  mappingProfileId: string
  values: Record<string, unknown>
  recalc?: boolean
}): Promise<GenerateResult> {
  const res = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  const warningsHeader = res.headers.get('X-Generation-Warnings')
  const warnings: string[] = warningsHeader ? JSON.parse(warningsHeader) : []
  const writtenCount = Number(res.headers.get('X-Generation-Written-Count') ?? '0')
  const outputsHeader = res.headers.get('X-Generation-Outputs')
  const outputs: Record<string, unknown> = outputsHeader ? JSON.parse(outputsHeader) : {}
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const filename = disposition.match(/filename="?([^"]+)"?/)?.[1] ?? 'generated.xlsx'
  const blob = await res.blob()
  return { blob, filename, warnings, writtenCount, outputs }
}

export async function exportNativeModel(
  values: Record<string, unknown>,
): Promise<{ blob: Blob; warnings: string[] }> {
  const res = await fetch(`${API_BASE}/generate/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  const warningsHeader = res.headers.get('X-Generation-Warnings')
  const warnings: string[] = warningsHeader ? JSON.parse(warningsHeader) : []
  return { blob: await res.blob(), warnings }
}

export function fetchScenarios(
  params: { templateId?: string; kind?: 'quickscreen' | 'full'; dealId?: string } = {},
) {
  const query = new URLSearchParams()
  if (params.templateId) query.set('template_id', params.templateId)
  if (params.kind) query.set('kind', params.kind)
  if (params.dealId) query.set('deal_id', params.dealId)
  const qs = query.toString()
  return getJson<Scenario[]>(`/scenarios${qs ? `?${qs}` : ''}`)
}

export function saveScenario(payload: {
  scenarioName: string
  kind?: 'quickscreen' | 'full'
  dealId?: string | null
  templateId?: string | null
  mappingProfileId?: string | null
  inputs: Record<string, unknown>
  outputs?: Record<string, unknown>
}) {
  return postJson<Scenario>('/scenarios', payload, 'POST')
}

export function updateScenario(
  scenarioId: string,
  payload: {
    scenarioName: string
    dealId?: string | null
    templateId?: string | null
    mappingProfileId?: string | null
    inputs: Record<string, unknown>
    outputs?: Record<string, unknown>
  },
) {
  return postJson<Scenario>(`/scenarios/${scenarioId}`, payload, 'PUT')
}

export interface DebtStressCell {
  rateBumpBps: number
  noiHaircutPct: number
  dscr: number | null
  refiProceeds: number
  governingConstraint: string
  refiShortfall: number
}

export interface DebtBlock {
  loanAmount: number
  sizedLoanAmount: number
  governingConstraint: string
  candidates: Record<string, number>
  sizingNoi: number
  value: number
  stress: DebtStressCell[]
  /** H3: present only when opex detail mode carries an insurance line. */
  insuranceStress?: { bumpPct: number; minDscr: number | null; leveredCfDeltaAnnual: number }[]
}

export interface ComputeResponse {
  outputs: Record<string, number | string>
  warnings: string[]
  debt: DebtBlock | null
  irrConvention: 'periodic_monthly' | 'xirr'
  waterfallStyle: 'european' | 'american'
  statement?: Statement
}

export function computeNative(
  values: Record<string, unknown>,
  options: { detail?: boolean } = {},
) {
  return postJson<ComputeResponse>(
    `/compute${options.detail ? '?detail=true' : ''}`,
    { values },
    'POST',
  )
}

export interface MarketRates {
  dataSource: string
  rates: Record<string, number | null>
  asOf?: Record<string, string>
  note?: string
}

export function fetchMarketRates() {
  return getJson<MarketRates>('/market/rates')
}

export type BenchmarkVerdict = 'ok' | 'caution' | 'warning'

export interface BenchmarkFlag {
  metric: string
  subjectValue: number | string | null
  benchmarkValue: number | string | null
  source: string
  asOf: string
  verdict: BenchmarkVerdict
  explanation: string
  relatedFieldIds: string[]
}

export interface BenchmarkResult {
  location: Record<string, unknown>
  flags: BenchmarkFlag[]
  unavailable: { source: string; note: string }[]
}

export function fetchBenchmarks(payload: {
  address: string
  market: string
  submarket: string
  assetClass: string
  subject: Record<string, unknown>
}) {
  return postJson<BenchmarkResult>('/market/benchmarks', payload, 'POST')
}

export interface PropertyTaxLookupResult {
  dataSource: string
  folio: string | null
  address: string | null
  assessedValue: number | null
  taxableValue: number | null
  millageRate: number | null
  currentTaxes: number | null
  adValoremTaxes?: number | null
  nonAdValorem?: number | null
  totalTaxes?: number | null
  jurisdiction: string
  asOf: string | null
  note: string | null
  projection: {
    assessmentRatio: number
    projectedAssessedValue: number
    projectedAdValorem?: number
    carriedNonAdValorem?: number
    projectedAnnualTaxes: number
  } | null
}

export function lookupPropertyTax(payload: {
  query: string
  county?: string | null
  purchasePrice?: number | null
  assessmentRatio?: number | null
}) {
  return postJson<PropertyTaxLookupResult>('/property-tax/lookup', payload, 'POST')
}

export interface TrendPoint {
  period: string
  value: number
}

export interface TrendSection {
  dataSource: string
  note?: string
  metroName?: string
  population?: TrendPoint[]
  medianHouseholdIncome?: TrendPoint[]
  employmentLevel?: TrendPoint[]
  unemploymentRatePct?: TrendPoint[]
  hpiIndex?: TrendPoint[]
  perCapitaPersonalIncome?: TrendPoint[]
}

export interface DemographicTrends {
  location: Record<string, unknown>
  population: TrendSection
  employment: TrendSection
  homePrices: TrendSection
  income: TrendSection
}

export function fetchDemographics(market: string, submarket = '', address = '') {
  const params = new URLSearchParams({ market, submarket, address })
  return getJson<DemographicTrends>(`/demographics?${params}`)
}

export interface DealSnapshotMeta {
  id: string
  kind: 'baseline' | 'autosave' | 'restore'
  changedPaths: string[]
  createdAt: string
  updatedAt: string
}

export function fetchDealHistory(dealId: string) {
  return getJson<DealSnapshotMeta[]>(`/deals/${dealId}/history`)
}

export function fetchDealSnapshot(dealId: string, snapshotId: string) {
  return getJson<DealSnapshotMeta & { inputs: Record<string, unknown> }>(
    `/deals/${dealId}/history/${snapshotId}`,
  )
}

export function restoreDealSnapshot(dealId: string, snapshotId: string) {
  return postJson<Deal>(`/deals/${dealId}/history/${snapshotId}/restore`, {}, 'POST')
}

export interface AssumptionPreset {
  id: string
  name: string
  description: string
  values: Record<string, unknown>
  source: 'user' | 'seed'
  createdAt: string
  updatedAt: string
}

export function fetchPresets() {
  return getJson<AssumptionPreset[]>('/presets')
}

export function fetchPresetFields() {
  return getJson<string[]>('/presets/fields')
}

export function createPreset(payload: {
  name: string
  description?: string
  values: Record<string, unknown>
}) {
  return postJson<AssumptionPreset>('/presets', payload, 'POST')
}

export function deletePreset(presetId: string) {
  return del(`/presets/${presetId}`)
}

export type CompKind = 'sale' | 'rent'

export interface Comp {
  id: string
  kind: CompKind
  name: string
  address: string
  market: string
  submarket: string
  propertyType: string
  source: string
  notes: string
  // sale
  saleDate?: string
  price?: number | null
  units?: number | null
  sf?: number | null
  capRatePct?: number | null
  pricePerUnit?: number | null
  pricePerSf?: number | null
  // rent
  asOf?: string
  unitType?: string
  avgRent?: number | null
  avgSf?: number | null
  occupancyPct?: number | null
  yearBuilt?: number | null
  createdAt: string
}

export interface CompDuplicate {
  rowIndex: number
  existingId: string
  existingName: string
  daysApart: number
}

export interface CompsImportResult {
  phase: 'preview' | 'imported'
  columns?: string[]
  suggestedMapping?: Record<string, string>
  rowCount?: number
  sampleRows?: Record<string, string>[]
  duplicates?: CompDuplicate[]
  imported: number
  warnings: string[]
}

export interface CompMapPoint {
  id: string
  name: string
  lat: number
  lon: number
}

export function fetchComps(kind: CompKind, market = '') {
  const params = market ? `?market=${encodeURIComponent(market)}` : ''
  return getJson<Comp[]>(`/comps/${kind}${params}`)
}

export function fetchCompsMap(kind: CompKind, market = '') {
  const params = market ? `?market=${encodeURIComponent(market)}` : ''
  return getJson<{ points: CompMapPoint[]; warnings: string[] }>(`/comps/${kind}/map${params}`)
}

export function createComp(kind: CompKind, payload: Record<string, unknown>) {
  return postJson<Comp>(`/comps/${kind}`, payload, 'POST')
}

export function deleteComp(kind: CompKind, compId: string) {
  return del(`/comps/${kind}/${compId}`)
}

export function importCompsCsv(payload: {
  kind: CompKind
  csvText: string
  mapping?: Record<string, string>
  defaultMarket?: string
  skipRows?: number[]
}) {
  return postJson<CompsImportResult>('/comps/import', payload, 'POST')
}

export function fetchDeals() {
  return getJson<Deal[]>('/deals')
}

export function fetchDeal(dealId: string) {
  return getJson<Deal>(`/deals/${dealId}`)
}

export function createDeal(payload: { name: string; inputs?: Record<string, unknown> }) {
  return postJson<Deal>('/deals', payload, 'POST')
}

export function updateDeal(
  dealId: string,
  payload: {
    name?: string
    inputs?: Record<string, unknown>
    status?: import('../types/deal').DealStatus
    activeTemplateId?: string | null
    activeMappingProfileId?: string | null
  },
) {
  return postJson<Deal>(`/deals/${dealId}`, payload, 'PUT')
}

export function bulkUpdateDealStatus(
  dealIds: string[],
  status: import('../types/deal').DealStatus,
) {
  return postJson<{ updated: Deal[]; missing: string[] }>(
    '/deals/bulk-status',
    { dealIds, status },
    'POST',
  )
}

export async function exportBatchDeck(
  dealIds: string[],
): Promise<{ blob: Blob; skipped: string[] }> {
  const res = await fetch(`${API_BASE}/deals/batch-deck`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dealIds }),
  })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  const skippedHeader = res.headers.get('X-Deck-Skipped')
  const skipped: string[] = skippedHeader ? JSON.parse(skippedHeader) : []
  return { blob: await res.blob(), skipped }
}

export async function deleteDeal(dealId: string): Promise<void> {
  return del(`/deals/${dealId}`)
}

export async function generateMemo(
  scenarioId: string,
  format: 'docx' | 'pdf' = 'docx',
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/memo?format=${format}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const filename = disposition.match(/filename="?([^";]+)"?/)?.[1] ?? 'ic-memo.docx'
  return { blob: await res.blob(), filename }
}

export async function deleteScenario(scenarioId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/scenarios/${scenarioId}`, { method: 'DELETE' })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
}

export function fetchMarketContext(market: string, submarket: string, assetClass: string) {
  const params = new URLSearchParams({ market, submarket, asset_class: assetClass })
  return getJson<MarketContext>(`/market-context?${params}`)
}

export function fetchDocuments() {
  return getJson<DocumentSummary[]>('/documents')
}

export async function uploadDocument(file: File): Promise<DocumentSummary> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_BASE}/documents/upload`, { method: 'POST', body: form })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  return res.json() as Promise<DocumentSummary>
}

export function updateDocumentType(documentId: string, documentType: DocumentType) {
  return postJson<DocumentSummary>(`/documents/${documentId}/type`, { documentType }, 'PUT')
}

export function deleteDocument(documentId: string) {
  return del(`/documents/${documentId}`)
}

export function runExtraction(documentIds: string[]) {
  return postJson<ExtractionResult>('/extraction', { documentIds }, 'POST')
}

export function confirmExtraction(resultId: string, confirmedValues: Record<string, unknown>) {
  return postJson<ExtractionResult>(`/extraction/${resultId}/confirm`, { confirmedValues }, 'POST')
}

export function runSensitivity(payload: {
  mode: 'native' | 'template'
  templateId?: string | null
  mappingProfileId?: string | null
  baseValues: Record<string, unknown>
  drivers: SensitivityDriver[]
  outputFieldIds: string[]
}) {
  return postJson<SensitivityResponse>('/sensitivity', payload, 'POST')
}

export interface SavedSensitivity {
  description: string
  header: string[]
  rows: string[][]
  run: {
    mode: 'native' | 'template'
    drivers: SensitivityDriver[]
    outputFieldIds: string[]
    points: unknown[]
  }
}

export function saveScenarioSensitivity(scenarioId: string, sensitivity: SavedSensitivity) {
  return postJson<Scenario>(`/scenarios/${scenarioId}/sensitivity`, { sensitivity }, 'PUT')
}

export interface DealExportBundle {
  exportKind: string
  schemaVersion: number
  exportedAt: string
  deal: { name: string; inputs: Record<string, unknown> }
  activeTemplate: { id: string; filename: string | null } | null
  activeMappingProfile: { id: string; profileName: string | null } | null
  scenarios: unknown[]
}

export function exportDeal(dealId: string) {
  return getJson<DealExportBundle>(`/deals/${dealId}/export`)
}

export interface DealImportResponse extends Deal {
  importWarnings: string[]
  importedScenarios: number
}

export function importDeal(bundle: DealExportBundle) {
  return postJson<DealImportResponse>('/deals/import', { bundle }, 'POST')
}

export interface HoldSweepRow {
  holdYear: number
  unleveredIrr: number | null
  leveredIrr: number | null
  equityMultiple: number | null
  netProceeds: number | null
}

export interface RefiVsSaleSide {
  holdYears: number
  leveredIrr: number | null
  equityMultiple: number | null
  netProceeds?: number | null
  refiLoan?: number | null
  governingConstraint?: string
  cashOutProceeds?: number | null
  refiCosts?: number | null
}

export interface HoldSweepResponse {
  sweep: { rows: HoldSweepRow[]; modeledHoldYears: number; warnings: string[] }
  refiVsSale: {
    saleAtStabilization: RefiVsSaleSide | null
    holdThroughRefi: RefiVsSaleSide | null
    warnings: string[]
  }
}

export function fetchHoldSweep(values: Record<string, unknown>) {
  return postJson<HoldSweepResponse>('/compute/hold-sweep', { values }, 'POST')
}

export interface TornadoResponse {
  metric: string
  base: number
  bars: { key: string; label: string; low: number | null; high: number | null; impact: number }[]
}

export function fetchTornado(values: Record<string, unknown>, metric: string) {
  return postJson<TornadoResponse>('/compute/tornado', { values, metric }, 'POST')
}
