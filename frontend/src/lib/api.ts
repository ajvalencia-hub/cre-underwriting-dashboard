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
import type { MappingPreviewRow } from '../types/mappingPreview'
import { isDesktop } from './platform'

const API_BASE = '/api'

/** An API failure with what the UI needs to explain it: a readable
 *  message, the HTTP status (0 = couldn't reach the server), the engine's
 *  list of missing inputs when it refused to compute, and the request id
 *  that matches the server log line. */
export class ApiError extends Error {
  readonly status: number
  readonly missing: string[]
  readonly requestId: string | null

  constructor(message: string, status: number, missing: string[] = [], requestId: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.missing = missing
    this.requestId = requestId
  }
}

interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

/** FastAPI's 422 body is {detail: [{loc, msg, type}]} — turn it into words. */
export function describeValidationDetail(detail: ValidationIssue[]): string {
  const parts = detail.slice(0, 4).map((issue) => {
    const where = (issue.loc ?? []).filter((p) => p !== 'body' && p !== 'query').join(' → ')
    return where ? `${where}: ${issue.msg ?? 'invalid'}` : (issue.msg ?? 'invalid')
  })
  const more = detail.length > 4 ? ` (and ${detail.length - 4} more)` : ''
  return `Some values weren't accepted — ${parts.join('; ')}${more}`
}

export async function apiError(res: Response): Promise<ApiError> {
  const requestId = res.headers.get('X-Request-ID')
  let message = res.status >= 500
    ? `The server hit an unexpected error (${res.status}). Your inputs are unchanged — try again, and if it persists, report request ${requestId ?? 'id unavailable'}.`
    : `${res.status} ${res.statusText}`
  let missing: string[] = []
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') message = body.detail
    else if (Array.isArray(body?.detail)) message = describeValidationDetail(body.detail as ValidationIssue[])
    if (Array.isArray(body?.missing)) missing = body.missing.filter((m: unknown): m is string => typeof m === 'string')
  } catch {
    // response wasn't JSON
  }
  return new ApiError(message, res.status, missing, requestId)
}

/** fetch() that turns "couldn't connect" into an explanation. */
async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(
      isDesktop()
        ? "The app's calculation engine isn't responding. Quit and reopen CRE Underwriting — your saved deals are safe."
        : "Can't reach the API server. Check that the backend is running (uvicorn on port 8000), then try again.",
      0,
    )
  }
}

/** Prefer the RFC 5987 filename* (the backend sends the real, possibly
 *  non-ASCII name there) over the ASCII-safe filename= fallback. */
export function filenameFromDisposition(disposition: string | null, fallback: string): string {
  if (!disposition) return fallback
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (star) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      // malformed encoding — fall back to the plain filename
    }
  }
  return disposition.match(/filename="?([^";]+)"?/)?.[1] ?? fallback
}

/** GET a server-generated file (deck, CSV, share page, attachment). */
export async function fetchServerFile(url: string, fallbackName: string): Promise<{ blob: Blob; filename: string }> {
  const res = await apiFetch(url)
  if (!res.ok) throw await apiError(res)
  return { blob: await res.blob(), filename: filenameFromDisposition(res.headers.get('Content-Disposition'), fallbackName) }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await apiFetch(`${API_BASE}${path}`)
  if (!res.ok) {
    throw await apiError(res)
  }
  return res.json() as Promise<T>
}

async function postJson<T>(path: string, body: unknown, method: 'POST' | 'PUT' = 'POST'): Promise<T> {
  const res = await apiFetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw await apiError(res)
  }
  return res.json() as Promise<T>
}

async function del(path: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}${path}`, { method: 'DELETE' })
  if (!res.ok) {
    throw await apiError(res)
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
  const res = await apiFetch(`${API_BASE}/templates/upload`, { method: 'POST', body: form })
  if (!res.ok) {
    throw await apiError(res)
  }
  return res.json() as Promise<TemplateSummary>
}

export function fetchSheetGrid(templateId: string, sheetName: string, maxRows = 60, maxCols = 30, startRow = 1) {
  const params = new URLSearchParams({
    max_rows: String(maxRows),
    max_cols: String(maxCols),
    start_row: String(startRow),
  })
  return getJson<SheetGrid>(
    `/templates/${templateId}/sheets/${encodeURIComponent(sheetName)}/grid?${params}`,
  )
}

export async function previewMapping(
  templateId: string,
  mappings: MappingsById,
  values: Record<string, unknown>,
): Promise<MappingPreviewRow[]> {
  const { fields } = await postJson<{ fields: MappingPreviewRow[] }>('/mappings/preview', { templateId, mappings, values })
  return fields
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
  const res = await apiFetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    throw await apiError(res)
  }
  const warningsHeader = res.headers.get('X-Generation-Warnings')
  const warnings: string[] = warningsHeader ? JSON.parse(warningsHeader) : []
  const writtenCount = Number(res.headers.get('X-Generation-Written-Count') ?? '0')
  const outputsHeader = res.headers.get('X-Generation-Outputs')
  const outputs: Record<string, unknown> = outputsHeader ? JSON.parse(outputsHeader) : {}
  const filename = filenameFromDisposition(res.headers.get('Content-Disposition'), 'generated.xlsx')
  const blob = await res.blob()
  return { blob, filename, warnings, writtenCount, outputs }
}

export async function exportNativeModel(
  values: Record<string, unknown>,
): Promise<{ blob: Blob; warnings: string[] }> {
  const res = await apiFetch(`${API_BASE}/generate/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  })
  if (!res.ok) {
    throw await apiError(res)
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

export interface DebtRateInfo {
  mode: 'floating'
  index: string
  spreadBps: number
  initialRatePct: number
  monthlyRatePct: number[]
  floorPct?: number
  cap?: {
    strikePct: number
    strikeAllInPct: number
    termMonths: number
    premium: number
    dscrAtStrike: number | null
  }
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
  /** J5: present only for floating-rate loans. */
  rate?: DebtRateInfo
}

export interface GpEconomics {
  acquisitionFee: number
  developerFee: number
  assetMgmtFees: number
  feesTotal: number
  promote: number
  gpDistributionsNet: number
  proRataNet: number
  totalCompensation: number
}

export interface ComputeResponse {
  outputs: Record<string, number | string>
  warnings: string[]
  debt: DebtBlock | null
  irrConvention: 'periodic_monthly' | 'xirr'
  waterfallStyle: 'european' | 'american'
  statement?: Statement
  /** J3: present only for deals with GP fee streams. */
  gpEconomics?: GpEconomics
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

export interface GoalSeekResult {
  solvedValue: number | null
  achievedMetric?: number
  iterations?: number
  otherCrossings?: number[]
  reason?: 'no_crossing' | 'metric_unavailable'
  detail?: string
  scanned?: { value: number; metric: number | null }[]
  scannedRange: [number, number]
  targetInput: string
  outputMetric: string
  targetValue: number
  tolerance: number
}

export function runGoalSeek(payload: {
  values: Record<string, unknown>
  targetInput: string
  outputMetric: string
  targetValue: number
  bounds?: [number, number]
}) {
  return postJson<GoalSeekResult>('/compute/goal-seek', payload, 'POST')
}

export function fetchGoalSeekInputs() {
  return getJson<{ id: string; label: string; type: string }[]>('/compute/goal-seek/inputs')
}

// ---- J8: Monte Carlo ----

export interface McDriver {
  inputPath: string
  distribution: 'normal' | 'triangular' | 'uniform'
  params: Record<string, number>
}

export interface McStats {
  p5: number
  p25: number
  p50: number
  p75: number
  p95: number
  mean: number
  min: number
  max: number
}

export interface MonteCarloResult {
  n: number
  seed: number
  successfulRuns: number
  failedRuns: number
  drivers: McDriver[]
  correlations: { a: string; b: string; rho: number }[]
  hurdleIrr: number
  leveredIrr: McStats
  equityMultiple: McStats
  peakNegativeCashFlow: McStats
  probIrrNegative: number
  probIrrBelowHurdle: number
  histogram: Record<string, { lo: number; hi: number; count: number }[]>
}

export interface MonteCarloJobStatus {
  status: 'running' | 'done' | 'failed'
  completed: number
  n: number
  result?: MonteCarloResult
  error?: string
}

export function startMonteCarlo(payload: {
  values: Record<string, unknown>
  drivers: McDriver[]
  correlations?: { a: string; b: string; rho: number }[]
  n: number
  seed?: number
  hurdleIrr?: number
}) {
  return postJson<{ jobId: string; n: number }>('/compute/monte-carlo', payload, 'POST')
}

export function pollMonteCarlo(jobId: string) {
  return getJson<MonteCarloJobStatus>(`/compute/monte-carlo/${jobId}`)
}

export function saveScenarioMonteCarlo(scenarioId: string, monteCarlo: MonteCarloResult) {
  return postJson<Scenario>(`/scenarios/${scenarioId}/monte-carlo`, { monteCarlo }, 'PUT')
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
  const res = await apiFetch(`${API_BASE}/deals/batch-deck`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dealIds }),
  })
  if (!res.ok) {
    throw await apiError(res)
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
  const res = await apiFetch(`${API_BASE}/scenarios/${scenarioId}/memo?format=${format}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) {
    throw await apiError(res)
  }
  const filename = filenameFromDisposition(res.headers.get('Content-Disposition'), 'ic-memo.docx')
  return { blob: await res.blob(), filename }
}

export async function deleteScenario(scenarioId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/scenarios/${scenarioId}`, { method: 'DELETE' })
  if (!res.ok) {
    throw await apiError(res)
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
  const res = await apiFetch(`${API_BASE}/documents/upload`, { method: 'POST', body: form })
  if (!res.ok) {
    throw await apiError(res)
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

export function getExtraction(resultId: string) {
  return getJson<ExtractionResult>(`/extraction/${resultId}`)
}

// ---- Settings: backups (J16 endpoints) + integration status ----

export interface BackupSnapshot {
  name: string
  createdAt: string | null
  uploadCount: number
  hasDb: boolean
}

export type BackupKind = 'daily' | 'weekly' | 'pre_restore'

/** Outcome of the last automatic (launch / daily) backup attempt. */
export interface AutomaticBackupStatus {
  at: string
  ok: boolean
  /** Snapshot name, or "skipped (recent daily exists)". */
  result: string | null
  error: string | null
}

export interface BackupListing {
  daily: BackupSnapshot[]
  weekly: BackupSnapshot[]
  /** Taken automatically before each restore, so a restore can be undone. */
  pre_restore: BackupSnapshot[]
  lastAutomatic: AutomaticBackupStatus | null
}

export function fetchBackups() {
  return getJson<BackupListing>('/admin/backups')
}

export function runBackupNow() {
  return postJson<{ created: string; kind: string }>('/admin/backups/run', {}, 'POST')
}

export function restoreBackup(kind: BackupKind, name: string) {
  return postJson<{ restored: string; uploads: unknown[]; note: string; preRestoreSnapshot: string | null }>(
    '/admin/backups/restore',
    { kind, name },
    'POST',
  )
}

export interface IntegrationStatus {
  envVar: string
  label: string
  configured: boolean
  purpose: string
}

export function fetchIntegrations() {
  return getJson<IntegrationStatus[]>('/admin/integrations')
}

export interface ExternalToolsStatus {
  libreoffice: { available: boolean; path: string | null; enables: string[] }
  ocr: { available: boolean; enables: string[] }
}

export function fetchExternalTools() {
  return getJson<ExternalToolsStatus>('/admin/tools')
}

// ---- J15: portfolio roll-up ----

export interface PortfolioRollup {
  dealCount: number
  excludedCount: number
  totals: { equity: number; totalCost: number; units: number; sf: number }
  byStatus: { status: string; count: number; equity: number; totalCost: number; units: number; sf: number }[]
  byDealType: { dealType: string; count: number; equity: number; totalCost: number; units: number; sf: number }[]
  exposureByMarket: { market: string; equity: number }[]
  exposureByAssetClass: { assetClass: string; equity: number }[]
  blendedLeveredIrr: number | null
  blendedEquityMultiple: number | null
  concentration: { market: string; equity: number; sharePct: number }[]
  deals: {
    id: string; name: string; status: string; dealType: string; market: string; assetClass: string
    equity: number; leveredIrr: number | null; equityMultiple: number | null
  }[]
  excluded: { id: string; name: string; reason: string }[]
}

export function fetchPortfolio() {
  return getJson<PortfolioRollup>('/portfolio')
}

// ---- J13: global search ----

export interface SearchItem {
  id: string
  title: string
  subtitle: string
  dealId?: string
  /** Which dealflow the item belongs to (deal-scoped groups only). */
  dealType?: 'acquisition' | 'development' | null
}

export interface SearchGroup {
  kind: 'deals' | 'tenants' | 'comps' | 'notes'
  items: SearchItem[]
}

export function globalSearch(q: string) {
  return getJson<{ query: string; groups: SearchGroup[] }>(
    `/search?q=${encodeURIComponent(q)}`,
  )
}

// ---- J12: deal file cabinet + notes ----

export interface DealAttachment {
  id: string
  filename: string
  fileHash: string
  fileExt: string
  sizeBytes: number | null
  source: 'attachment' | 'extraction'
  documentType: string
  createdAt: string
}

export interface DealNote {
  id: string
  body: string
  createdAt: string
  updatedAt: string
}

export function fetchAttachments(dealId: string) {
  return getJson<DealAttachment[]>(`/deals/${dealId}/attachments`)
}

export async function uploadAttachment(dealId: string, file: File): Promise<DealAttachment> {
  const form = new FormData()
  form.append('file', file)
  const res = await apiFetch(`${API_BASE}/deals/${dealId}/attachments`, { method: 'POST', body: form })
  if (!res.ok) throw await apiError(res)
  return res.json() as Promise<DealAttachment>
}

export function attachmentDownloadUrl(dealId: string, documentId: string, inline = false) {
  return `${API_BASE}/deals/${dealId}/attachments/${documentId}/download${inline ? '?inline=true' : ''}`
}

export function fetchAttachmentPreview(dealId: string, documentId: string) {
  return getJson<{ kind: 'text' | 'none'; text?: string; note?: string }>(
    `/deals/${dealId}/attachments/${documentId}/preview`,
  )
}

export function fetchNotes(dealId: string) {
  return getJson<DealNote[]>(`/deals/${dealId}/notes`)
}

export function createNote(dealId: string, body: string) {
  return postJson<DealNote>(`/deals/${dealId}/notes`, { body }, 'POST')
}

export function updateNote(dealId: string, noteId: string, body: string) {
  return postJson<DealNote>(`/deals/${dealId}/notes/${noteId}`, { body }, 'PUT')
}

export function deleteNote(dealId: string, noteId: string) {
  return del(`/deals/${dealId}/notes/${noteId}`)
}

/** J10: the wizard's finalize step — creates (or finalizes a draft) deal
 *  from a reviewed extraction, writing provenance rows server-side. */
export function createDealFromExtraction(payload: {
  name: string
  extractionResultId: string
  confirmedValues: Record<string, unknown>
  acknowledgeFailures?: boolean
  dealId?: string
}) {
  return postJson<Deal>('/deals/from-extraction', payload, 'POST')
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
