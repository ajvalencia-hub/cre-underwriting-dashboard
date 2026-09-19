// Compile-time contract between the backend's declared responses (generated
// into api.gen.ts by `npm run gen:api`) and the frontend's own types
// (roadmap #22). Each line asserts that what the API returns fits the type
// the UI reads it as; if either side drifts, `tsc` fails here — locally and
// in CI (which also checks api.gen.ts is up to date).
import type { components } from './api.gen'
import type {
  AssumptionPreset,
  BackupListing,
  Comp,
  CompMapPoint,
  CompsImportResult,
  ComputeResponse,
  DealAttachment,
  DealMetrics,
  DealNote,
  DealSnapshotMeta,
  ExternalToolsStatus,
  GoalSeekResult,
  HoldSweepResponse,
  IntegrationStatus,
  MarketRates,
  MonteCarloJobStatus,
  PortfolioRollup,
  RecalcAgreement,
  SearchGroup,
  TornadoResponse,
} from '../lib/api'
import type { MappingPreviewRow } from './mappingPreview'
import type { Deal, DealSummaryRow } from './deal'
import type { DocumentSummary } from './document'
import type { ExtractionResult } from './extraction'
import type { AutoMatchResult, MappingEntry, MappingProfile } from './mapping'
import type { Scenario } from './scenario'
import type { SensitivityResponse } from './sensitivity'
import type { GridCell, SheetGrid, TemplateSummary } from './template'

type Schemas = components['schemas']
/** Resolves to `true` only when the API's type is usable as the UI's type. */
type Fits<Api, Ui> = [Api] extends [Ui] ? true : false
type Check<T extends true> = T

export type ApiContract = [
  Check<Fits<Schemas['DealOut'], Deal>>,
  Check<Fits<Schemas['TemplateSummary'], TemplateSummary>>,
  Check<Fits<Schemas['SheetGrid'], SheetGrid>>,
  Check<Fits<Schemas['GridCell'], GridCell>>,
  Check<Fits<Schemas['DocumentSummary'], DocumentSummary>>,
  Check<Fits<Schemas['MappingEntry'], MappingEntry>>,
  Check<Fits<Schemas['MappingProfileOut'], MappingProfile>>,
  Check<Fits<Schemas['AutoMatchResult'], AutoMatchResult>>,
  Check<Fits<Schemas['ScenarioOut'], Scenario>>,
  Check<Fits<Schemas['ExtractionResultOut'], ExtractionResult>>,
  Check<Fits<Schemas['SensitivityResponse'], SensitivityResponse>>,
  Check<Fits<Schemas['AttachmentOut'], DealAttachment>>,
  Check<Fits<Schemas['NoteOut'], DealNote>>,
  Check<Fits<Schemas['SnapshotMetaOut'], DealSnapshotMeta>>,
  Check<Fits<Schemas['PresetOut'], AssumptionPreset>>,
  Check<Fits<Schemas['BackupListingOut'], BackupListing>>,
  Check<Fits<Schemas['DealMetricsOk'] | Schemas['DealMetricsIncomplete'], DealMetrics>>,
  Check<Fits<Schemas['ComputeResponseOut'], ComputeResponse>>,
  Check<Fits<Schemas['IntegrationStatusOut'], IntegrationStatus>>,
  Check<Fits<Schemas['ExternalToolsOut'], ExternalToolsStatus>>,
  Check<Fits<Schemas['PortfolioOut'], PortfolioRollup>>,
  Check<Fits<Schemas['SearchGroupOut'], SearchGroup>>,
  Check<Fits<Schemas['HoldSweepResponseOut'], HoldSweepResponse>>,
  Check<Fits<Schemas['TornadoOut'], TornadoResponse>>,
  Check<Fits<Schemas['GoalSeekOut'], GoalSeekResult>>,
  Check<Fits<Schemas['MappingPreviewRowOut'], MappingPreviewRow>>,
  Check<Fits<Schemas['RecalcAgreementOut'], RecalcAgreement>>,
  Check<Fits<Schemas['CompOut'], Comp>>,
  Check<Fits<Schemas['CompsImportOut'], CompsImportResult>>,
  Check<Fits<Schemas['CompMapPointOut'], CompMapPoint>>,
  Check<Fits<Schemas['MonteCarloJobOut'], MonteCarloJobStatus>>,
  Check<Fits<Schemas['MarketRatesOut'], MarketRates>>,
  Check<Fits<Schemas['DealSummaryOut'], DealSummaryRow>>,
  Check<Fits<Schemas['BulkTagsOut'], { updated: Deal[]; missing: string[] }>>,
  Check<Fits<Schemas['TornadoBarOut'], TornadoResponse['bars'][number]>>,
]
