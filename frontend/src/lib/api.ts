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
}

export interface ComputeResponse {
  outputs: Record<string, number | string>
  warnings: string[]
  debt: DebtBlock | null
}

export function computeNative(values: Record<string, unknown>) {
  return postJson<ComputeResponse>('/compute', { values }, 'POST')
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
    activeTemplateId?: string | null
    activeMappingProfileId?: string | null
  },
) {
  return postJson<Deal>(`/deals/${dealId}`, payload, 'PUT')
}

export async function deleteDeal(dealId: string): Promise<void> {
  return del(`/deals/${dealId}`)
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
  templateId: string
  mappingProfileId: string
  baseValues: Record<string, unknown>
  drivers: SensitivityDriver[]
  outputFieldIds: string[]
}) {
  return postJson<SensitivityResponse>('/sensitivity', payload, 'POST')
}
