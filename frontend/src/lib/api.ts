import type { Statement } from './cashflowStatement'
import type { InputSchema } from '../types/schema'
import type { SheetGrid, TemplateSummary } from '../types/template'
import type { AutoMatchResult, MappingProfile, MappingsById } from '../types/mapping'
import type { Deal, DealStatus, DealSummaryRow } from '../types/deal'
import type { Scenario } from '../types/scenario'
import type { MarketContext } from '../types/marketContext'
import type { DocumentSummary, DocumentType } from '../types/document'
import type { ExtractionResult } from '../types/extraction'
import type { SensitivityDriver, SensitivityResponse } from '../types/sensitivity'
import type { MappingPreviewRow } from '../types/mappingPreview'
import type {
  AgentApproveResult,
  AgentPlay,
  AgentProviderInfo,
  AgentRejectResult,
  AgentThreadRef,
  AgentThreadState,
  AgentTurnResult,
} from '../types/agent'
import { isDesktop } from './platform'
import { createSaveConcurrency } from './dealPersistence'
import type { components } from '../types/api.gen'

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

/** Fired on any 401 (browser mode only) so App shows the token gate
 *  (components/AuthGate.tsx). Listen with
 *  `window.addEventListener(UNAUTHORIZED_EVENT, …)`. Never fired in the
 *  desktop app: the launcher's per-launch token already protects the API. */
export const UNAUTHORIZED_EVENT = 'cre:unauthorized'

function notifyUnauthorized(): void {
  if (isDesktop()) return
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
  }
}

/** Build the ApiError for a failed response — the single choke point every
 *  helper (and fetchServerFile) goes through, so a 401 anywhere raises the
 *  token gate. `notify: false` for the login form, where a 401 just means
 *  "wrong token". */
export async function apiError(res: Response, options: { notify?: boolean } = {}): Promise<ApiError> {
  if (res.status === 401 && options.notify !== false) notifyUnauthorized()
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

// ---- Optimistic concurrency on deals (Run 6 wave 2, browser mode only) ----

/** One ETag per deal, recorded from EVERY single-deal response (GET, PUT,
 *  create, archive/unarchive, clone, restore, import, from-extraction) so an
 *  If-Match always reflects the last copy this tab has seen. App owns the
 *  conflict decisions (Reload / Overwrite); this layer only records. */
export const dealConcurrency = createSaveConcurrency<Deal>()

/** If-Match is sent only in browser mode: the desktop app is one window,
 *  and its owner declined cross-window protection there. */
export function concurrencyEnabled(): boolean {
  return !isDesktop()
}

/** 412 from `PUT /api/deals/{id}` with a stale If-Match. The server's
 *  current copy rides in the body so the UI can offer Reload without
 *  another round trip. */
export class ConflictError extends ApiError {
  readonly current: Deal
  readonly etag: string | null

  constructor(message: string, current: Deal, etag: string | null, requestId: string | null = null) {
    super(message, 412, [], requestId)
    this.name = 'ConflictError'
    this.current = current
    this.etag = etag
  }
}

export function isConflictError(err: unknown): err is ConflictError {
  return err instanceof ConflictError
}

/** Parse a single-deal body AND record its ETag (an absent header clears
 *  the stored one, so a server without ETags never gets an If-Match). */
async function dealJson<T extends Deal>(res: Response): Promise<T> {
  const deal = (await res.json()) as T
  dealConcurrency.recordEtag(deal.id, res.headers.get('ETag'))
  return deal
}

async function getDeal<T extends Deal = Deal>(path: string): Promise<T> {
  const res = await apiFetch(`${API_BASE}${path}`)
  if (!res.ok) throw await apiError(res)
  return dealJson<T>(res)
}

async function sendDeal<T extends Deal = Deal>(
  path: string,
  body: unknown,
  method: 'POST' | 'PUT',
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  const res = await apiFetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...extraHeaders },
    body: JSON.stringify(body),
  })
  if (res.status === 412) {
    const requestId = res.headers.get('X-Request-ID')
    let detail = 'This deal was changed in another tab or window.'
    let current: Deal | null = null
    try {
      const payload = (await res.clone().json()) as { detail?: unknown; current?: Deal }
      if (typeof payload.detail === 'string') detail = payload.detail
      if (payload.current && typeof payload.current === 'object') current = payload.current
    } catch {
      // body wasn't JSON — fall through to a plain ApiError
    }
    if (current) throw new ConflictError(detail, current, res.headers.get('ETag'), requestId)
    throw await apiError(res)
  }
  if (!res.ok) throw await apiError(res)
  return dealJson<T>(res)
}

// ---- Token session (CRE_API_TOKEN; browser/Docker mode) ----

export type AuthStatus = components['schemas']['AuthStatusOut']

export function fetchAuthStatus() {
  return getJson<AuthStatus>('/auth/status')
}

/** A wrong token rejects with ApiError(401) WITHOUT re-raising the gate —
 *  it's an inline form error. */
export async function login(token: string): Promise<AuthStatus> {
  const res = await apiFetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) throw await apiError(res, { notify: false })
  return res.json() as Promise<AuthStatus>
}

/** Clears the session cookie. Callers then dispatch UNAUTHORIZED_EVENT (or
 *  reload) to show the gate. */
export function logout() {
  return postJson<AuthStatus>('/auth/logout', {}, 'POST')
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

export interface RecalcAgreementRow {
  fieldId: string
  excelValue: string | number | boolean | null
  libreOfficeValue: string | number | boolean | null
  agrees: boolean
}

export interface RecalcAgreement {
  status: 'agrees' | 'differs' | 'noOutputsMapped' | 'noSavedValues'
  rows: RecalcAgreementRow[]
}

/** Recalculate the unmodified template in LibreOffice and compare each
 *  mapped output with the value Excel saved in the file. */
export function checkRecalcAgreement(templateId: string, mappings: MappingsById) {
  return postJson<RecalcAgreement>(`/templates/${templateId}/recalc-check`, { mappings })
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
  /** Present only when a cash-flow series has several IRRs. Additive: the
   *  reported IRR in `outputs` is unchanged; this lists the other roots. */
  irrDiagnostics?: IrrDiagnostics
}

export interface IrrSeriesDiagnostics {
  signChanges: number
  /** Annual IRRs within the plausible band (fractions, e.g. 0.12). */
  roots: number[]
  /** The IRR the outputs report for this series. */
  reported: number | null
}

export interface IrrDiagnostics {
  irrMultipleRoots: true
  unlevered?: IrrSeriesDiagnostics
  levered?: IrrSeriesDiagnostics
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
  status: 'running' | 'done' | 'failed' | 'cancelled'
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

/** Ask the server to stop a run (`DELETE /compute/monte-carlo/{id}`).
 *  Never throws: resolves false when the job is already gone, the server is
 *  unreachable or refused — the panel stops polling either way. */
export async function cancelMonteCarlo(jobId: string): Promise<boolean> {
  try {
    const res = await apiFetch(`${API_BASE}/compute/monte-carlo/${jobId}`, { method: 'DELETE' })
    if (res.status === 401) notifyUnauthorized()
    return res.ok
  } catch {
    return false
  }
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
  /** 'agent' = applied from an approved Underwriting Agent proposal. */
  kind: 'baseline' | 'autosave' | 'restore' | 'agent'
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
  return sendDeal(`/deals/${dealId}/history/${snapshotId}/restore`, {}, 'POST')
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

export interface FetchDealsOptions {
  /** Include archived deals (hidden by default). */
  includeArchived?: boolean
  /** Only deals carrying this tag (case-insensitive, server-side). */
  tag?: string
}

function dealListQuery(options: FetchDealsOptions & { fields?: 'summary' | 'full' }): string {
  const params = new URLSearchParams()
  if (options.includeArchived) params.set('includeArchived', 'true')
  if (options.tag?.trim()) params.set('tag', options.tag.trim())
  if (options.fields === 'summary') params.set('fields', 'summary')
  const qs = params.toString()
  return `/deals${qs ? `?${qs}` : ''}`
}

/** The deal list, newest first. `fields: 'summary'` returns the slim
 *  pipeline shape (no inputs blob) — see fetchDealSummaries. */
export function fetchDeals(options?: FetchDealsOptions & { fields?: 'full' }): Promise<Deal[]>
export function fetchDeals(options: FetchDealsOptions & { fields: 'summary' }): Promise<DealSummaryRow[]>
export function fetchDeals(
  options: FetchDealsOptions & { fields?: 'summary' | 'full' } = {},
): Promise<Deal[] | DealSummaryRow[]> {
  return getJson<Deal[] | DealSummaryRow[]>(dealListQuery(options))
}

/** `GET /deals?fields=summary`: headline facts only (no inputs). */
export function fetchDealSummaries(options: FetchDealsOptions = {}) {
  return fetchDeals({ ...options, fields: 'summary' })
}

export function fetchDeal(dealId: string) {
  return getDeal(`/deals/${dealId}`)
}

export function createDeal(payload: { name: string; inputs?: Record<string, unknown> }) {
  return sendDeal('/deals', payload, 'POST')
}

// ---- Archive / unarchive / clone ----

/** Soft-delete: hidden from the default list; `unarchiveDeal` brings it back. */
export function archiveDeal(dealId: string) {
  return sendDeal(`/deals/${dealId}/archive`, {}, 'POST')
}

export function unarchiveDeal(dealId: string) {
  return sendDeal(`/deals/${dealId}/unarchive`, {}, 'POST')
}

/** Copy a deal (inputs, stage, tags, template selection, scenarios — never
 *  its IC record). `name` defaults server-side to "<name> (copy)". */
export function cloneDeal(dealId: string, name?: string) {
  return sendDeal(`/deals/${dealId}/clone`, name ? { name } : {}, 'POST')
}

export interface DealUpdatePayload {
  name?: string
  inputs?: Record<string, unknown>
  status?: DealStatus
  activeTemplateId?: string | null
  activeMappingProfileId?: string | null
  /** Replaces the tag list (normalized server-side; see lib/tags.ts). Tags
   *  aren't deal inputs, so they're writable while IC-locked. */
  tags?: string[]
}

export interface UpdateDealOptions {
  /** Send `If-Match` (use `dealConcurrency.ifMatchFor(id)`). Ignored in the
   *  desktop app. A stale value rejects with ConflictError (412, carrying
   *  the server's `current` deal). Absent = unconditional (last write wins). */
  ifMatch?: string
}

export function updateDeal(dealId: string, payload: DealUpdatePayload, options: UpdateDealOptions = {}) {
  const headers: Record<string, string> =
    options.ifMatch && concurrencyEnabled() ? { 'If-Match': options.ifMatch } : {}
  return sendDeal(`/deals/${dealId}`, payload, 'PUT', headers)
}

export function bulkUpdateDealStatus(dealIds: string[], status: DealStatus) {
  return postJson<{ updated: Deal[]; missing: string[] }>(
    '/deals/bulk-status',
    { dealIds, status },
    'POST',
  )
}

/** Add and/or remove tags across many deals in one write (422 if a result
 *  would break the caps — then nothing changes). Unknown ids come back in
 *  `missing`. */
export function bulkUpdateDealTags(dealIds: string[], add: string[], remove: string[] = []) {
  return postJson<{ updated: Deal[]; missing: string[] }>('/deals/bulk-tags', { dealIds, add, remove }, 'POST')
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

export type BackupKind = 'daily' | 'weekly' | 'pre_restore' | 'pre_migration'

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
  /** Taken before an app update migrated the database. */
  pre_migration: BackupSnapshot[]
  lastAutomatic: AutomaticBackupStatus | null
}

export function fetchBackups() {
  return getJson<BackupListing>('/admin/backups')
}

export function runBackupNow() {
  return postJson<{ created: string; kind: string }>('/admin/backups/run', {}, 'POST')
}

/** A snapshot's SQLite file. Render it through components/ServerFileLink
 *  (never a plain <a>: in the desktop app that navigates the window). */
export function backupDownloadUrl(kind: BackupKind, name: string) {
  return `${API_BASE}/admin/backups/${encodeURIComponent(kind)}/${encodeURIComponent(name)}/download`
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

/** Key numbers per deal, computed from its saved inputs (roadmap #18). */
export type DealMetrics =
  | {
      status: 'ok'
      totalCost: number | null
      equity: number | null
      leveredIrr: number | null
      equityMultiple: number | null
      yieldOnCost: number | null
      goingInCapRate: number | null
    }
  | { status: 'incomplete'; missing: string[] }

export function fetchDealMetrics() {
  return getJson<Record<string, DealMetrics>>('/deals/metrics')
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

/** Remove one of the deal's OWN attachments (source 'attachment'; an
 *  extraction document 404s). Not a deal input — no IC-lock check. */
export function deleteAttachment(dealId: string, documentId: string) {
  return del(`/deals/${dealId}/attachments/${documentId}`)
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
  return sendDeal('/deals/from-extraction', payload, 'POST')
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
  return sendDeal<DealImportResponse>('/deals/import', { bundle }, 'POST')
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
  bars: {
    key: string
    label: string
    low: number | null
    high: number | null
    impact: number
    /** True when the driver can't move the metric on this deal (e.g. a
     *  rent-growth bar on a for-sale deal); `reason` says why. */
    inert?: boolean
    reason?: string | null
  }[]
}

export function fetchTornado(values: Record<string, unknown>, metric: string) {
  return postJson<TornadoResponse>('/compute/tornado', { values, metric }, 'POST')
}

// ---- Roadmap #28: investment-committee sign-off ----
// Types come straight from the generated API schema (no hand copy to drift).
export type IcSummary = components['schemas']['IcSummaryOut']
export type IcEvent = components['schemas']['IcEventOut']
export type IcState = IcSummary['state']
export type IcStepKind = IcEvent['kind']

export function fetchIc(dealId: string) {
  return getJson<IcSummary>(`/deals/${dealId}/ic`)
}

export function addIcStep(
  dealId: string,
  step: { kind: IcStepKind; actor: string; comment: string; requiredApprovals?: number },
) {
  return postJson<IcSummary>(`/deals/${dealId}/ic/events`, step)
}

export function fetchIcStates() {
  return getJson<Record<string, IcState>>('/ic/states')
}

// ---- Underwriting Agent (one thread per deal). Proposals are applied by the
// server on approve (IC lock + validation there), never client-side. Types
// alias the generated schemas (types/agent.ts). ----

export function fetchAgentThread(dealId: string) {
  return getJson<AgentThreadState>(`/agent/threads/${dealId}`)
}

/** Send a message, or run a canned play (`playId` wins over `content`). */
export function postAgentMessage(dealId: string, content: string, playId?: string) {
  return postJson<AgentTurnResult>(`/agent/threads/${dealId}/messages`, playId ? { playId } : { content }, 'POST')
}

export function fetchAgentPlays() {
  return getJson<AgentPlay[]>('/agent/plays')
}

export function fetchAgentProviders() {
  return getJson<AgentProviderInfo[]>('/agent/providers')
}

export function setAgentThreadProvider(dealId: string, provider: string) {
  return postJson<AgentThreadRef>(`/agent/threads/${dealId}/provider`, { provider }, 'PUT')
}

/** Applies the proposal's changes server-side (history kind "agent").
 *  409 = IC-locked (the proposal stays pending), 422 = invalid values
 *  (ApiError.missing lists them). The returned `deal` is the new server
 *  copy — the caller adopts it via its apply-deal path. */
export async function approveAgentProposal(proposalId: string, overrideChanges?: Record<string, unknown>) {
  const result = await postJson<AgentApproveResult>(
    `/agent/proposals/${proposalId}/approve`,
    { overrideChanges: overrideChanges ?? null },
    'POST',
  )
  // The approve route sends no ETag header; drop the now-stale one so the
  // next autosave doesn't 412 against our own approval (its PUT response
  // records a fresh ETag).
  dealConcurrency.recordEtag(result.deal.id, null)
  return result
}

export function rejectAgentProposal(proposalId: string, note = '') {
  return postJson<AgentRejectResult>(`/agent/proposals/${proposalId}/reject`, { note }, 'POST')
}
