// Pure helpers for the Cash Flow tab: year grouping, row definitions, and
// CSV serialization. Rendering-only concerns — every number comes from the
// engine's statement verbatim; sums are presentation aggregation.

export interface Statement {
  months: number[]
  phases: string[]
  constructionMonths: number
  stabilizationMonth: number
  exitMonth: number
  gpr: number[]
  vacancyLoss: number[]
  creditLoss: number[]
  otherIncome: number[]
  egi: number[]
  fixedOpexByCategory: Record<string, number[]>
  managementFee: number[]
  opexTotal: number[]
  noi: number[]
  occupancy: number[]
  costs: number[]
  loanFees: number[]
  equityFunded: number[]
  debtDraws: number[]
  interest: number[]
  principal: number[]
  debtService: number[]
  loanBalance: number[]
  saleProceedsNet: number[]
  saleProceedsGross: number[]
  recoveries: number[]
  leasingCapital: number[]
  unlevered: number[]
  levered: number[]
  lpDistributions: number[]
  gpDistributions: number[]
  /** Present only for mixed-use deals (H2): per-component income vectors. */
  components?: Record<
    'residential' | 'commercial',
    { gpr: number[]; vacancyLoss: number[]; creditLoss: number[]; otherIncome: number[]; egi: number[]; opex: number[]; noi: number[] }
  >
  /** Present only for lease-modeled commercial deals (H1). */
  leases?: {
    walt: number
    totalSf: number
    occupancyYear1: number
    occupancyStabilized: number
    expirationSchedule: {
      year: number
      sfExpiring: number
      pctOfSf: number
      pctOfRent: number
    }[]
    /** I8: per-lease drill-down slices (vectors are operating months 1..N,
     *  no close column). */
    perLease?: import('./leaseSlice').LeaseSlice[]
  }
  /** J1: present only when a renovation program exists. */
  renovationCapex?: number[]
  /** J6: present only with below-NOI per-unit/PSF reserves. */
  replacementReserves?: number[]
  /** J6: present only with tax & insurance escrows (−E at close, +E at exit). */
  escrowFlows?: number[]
  /** J9: per-calendar-year operating break-evens (analytic, on these vectors). */
  breakEvens?: {
    years: { year: number; occupancy: number | null; rentFactor: number | null; notes: string[] }[]
  }
  /** Roadmap #25: present only for hotels (operating months, close = 0). */
  hotel?: {
    keys: number
    roomsRevenue: number[]
    fnbRevenue: number[]
    otherRevenue: number[]
    gop: number[]
    revenueLinkedOpex: number[]
  }
  /** Roadmap #26: present only for build-to-sell deals (close = index 0). */
  forSale?: {
    homes: number
    closings: number[]
    grossSales: number[]
    sellingCosts: number[]
    netSales: number[]
    land: number[]
    siteWork: number[]
    vertical: number[]
    developerFee: number[]
    loanRepayments: number[]
  }
  /** J2: present only when loss-to-lease burn-off is active. */
  lossToLease?: { marketGpr: number[]; lossToLease: number[] }
  renovation?: {
    unitsComplete: number[]
    unitsInProgress: number[]
    unitsRemaining: number[]
    spendSchedule: number[]
    budget: number
    fundingSource: 'equity_at_close' | 'operating_cash'
  }
}

export interface StatementRow {
  key: string
  label: string
  /** flow rows sum across periods; balance rows report the period-end value. */
  kind: 'flow' | 'balance'
  /** dotted path into Statement for category rows. */
  series: (s: Statement) => number[]
  indent?: boolean
}

const CATEGORY_LABELS: Record<string, string> = {
  realEstateTaxes: 'Real estate taxes',
  insurance: 'Insurance',
  utilities: 'Utilities',
  repairsMaintenance: 'Repairs & maintenance',
  payroll: 'Payroll',
  generalAdmin: 'General & admin',
  replacementReserves: 'Replacement reserves',
  reservesUnderwritten: 'Replacement reserves (underwritten)',
  managementFeeFixed: 'Management fee (fixed $)',
  otherOpex: 'Other opex',
  hotelDepartmental: 'Departmental expenses',
  hotelUndistributed: 'Undistributed operating expenses',
  franchiseFee: 'Franchise fee',
  ffeReserve: 'FF&E reserve',
}

/** Roadmap #26: a build-to-sell deal has no operations — its statement is
 *  sales, the build budget, the loan and the equity flows. */
function forSaleRows(): StatementRow[] {
  const sale = (pick: (f: NonNullable<Statement['forSale']>) => number[]) => (s: Statement) =>
    s.forSale ? pick(s.forSale) : []
  return [
    { key: 'forSale.gross', label: 'Gross home sales', kind: 'flow', series: sale((f) => f.grossSales) },
    { key: 'forSale.selling', label: 'Less: selling costs', kind: 'flow', series: sale((f) => f.sellingCosts), indent: true },
    { key: 'forSale.net', label: 'Net sales', kind: 'flow', series: sale((f) => f.netSales) },
    { key: 'forSale.land', label: 'Land', kind: 'flow', series: sale((f) => f.land), indent: true },
    { key: 'forSale.site', label: 'Site work (hard, soft, contingency)', kind: 'flow', series: sale((f) => f.siteWork), indent: true },
    { key: 'forSale.vertical', label: 'Home construction', kind: 'flow', series: sale((f) => f.vertical), indent: true },
    { key: 'forSale.fee', label: 'Developer fee', kind: 'flow', series: sale((f) => f.developerFee), indent: true },
    { key: 'costs', label: 'Project costs', kind: 'flow', series: (s) => s.costs },
    { key: 'debtDraws', label: 'Loan draws', kind: 'flow', series: (s) => s.debtDraws },
    { key: 'interest', label: 'Interest', kind: 'flow', series: (s) => s.interest, indent: true },
    { key: 'principal', label: 'Loan repaid from closings', kind: 'flow', series: (s) => s.principal, indent: true },
    { key: 'loanBalance', label: 'Loan balance (end)', kind: 'balance', series: (s) => s.loanBalance },
    { key: 'unlevered', label: 'Unlevered cash flow', kind: 'flow', series: (s) => s.unlevered },
    { key: 'levered', label: 'Levered cash flow', kind: 'flow', series: (s) => s.levered },
    { key: 'lpDistributions', label: 'LP cash flow', kind: 'flow', series: (s) => s.lpDistributions, indent: true },
    { key: 'gpDistributions', label: 'GP cash flow', kind: 'flow', series: (s) => s.gpDistributions, indent: true },
  ]
}

export function statementRows(statement: Statement): StatementRow[] {
  if (statement.forSale) return forSaleRows()
  const rows: StatementRow[] = []
  if (statement.lossToLease) {
    // J2: the revenue build — GPR at market, less LTL, = scheduled rent.
    rows.push(
      {
        key: 'marketGpr', label: 'Gross potential rent (market)', kind: 'flow',
        series: (s) => s.lossToLease?.marketGpr ?? [],
      },
      {
        key: 'lossToLease', label: 'Less: loss to lease', kind: 'flow', indent: true,
        series: (s) => s.lossToLease?.lossToLease ?? [],
      },
    )
  }
  if (statement.hotel) {
    // Roadmap #25: the hotel revenue build (USALI summary), same vectors.
    rows.push(
      { key: 'gpr', label: 'Potential rooms revenue (100% occupied)', kind: 'flow', series: (s) => s.gpr },
      { key: 'vacancyLoss', label: 'Less: unsold room-nights', kind: 'flow', series: (s) => s.vacancyLoss, indent: true },
      { key: 'hotel.rooms', label: 'Rooms revenue', kind: 'flow', series: (s) => s.hotel?.roomsRevenue ?? [] },
      { key: 'hotel.fnb', label: 'Food & beverage revenue', kind: 'flow', series: (s) => s.hotel?.fnbRevenue ?? [], indent: true },
      { key: 'hotel.other', label: 'Other revenue', kind: 'flow', series: (s) => s.hotel?.otherRevenue ?? [], indent: true },
      { key: 'egi', label: 'Total revenue', kind: 'flow', series: (s) => s.egi },
      { key: 'hotel.gop', label: 'Gross operating profit (after departmental and undistributed)', kind: 'flow', series: (s) => s.hotel?.gop ?? [] },
    )
  } else {
    rows.push(
      {
        key: 'gpr',
        label: statement.lossToLease ? 'Scheduled rent' : 'Gross potential rent',
        kind: 'flow',
        series: (s) => s.gpr,
      },
      { key: 'vacancyLoss', label: 'Less: vacancy', kind: 'flow', series: (s) => s.vacancyLoss, indent: true },
      { key: 'creditLoss', label: 'Less: credit loss', kind: 'flow', series: (s) => s.creditLoss, indent: true },
      { key: 'otherIncome', label: 'Other income', kind: 'flow', series: (s) => s.otherIncome, indent: true },
      { key: 'egi', label: 'Effective gross income', kind: 'flow', series: (s) => s.egi },
    )
  }
  for (const category of Object.keys(statement.fixedOpexByCategory)) {
    rows.push({
      key: `opex.${category}`,
      label: CATEGORY_LABELS[category] ?? category,
      kind: 'flow',
      series: (s) => s.fixedOpexByCategory[category] ?? [],
      indent: true,
    })
  }
  rows.push(
    { key: 'managementFee', label: 'Management fee', kind: 'flow', series: (s) => s.managementFee, indent: true },
    { key: 'opexTotal', label: 'Total operating expenses', kind: 'flow', series: (s) => s.opexTotal },
    { key: 'noi', label: 'Net operating income', kind: 'flow', series: (s) => s.noi },
    { key: 'costs', label: 'Project costs', kind: 'flow', series: (s) => s.costs },
    { key: 'debtDraws', label: 'Debt draws / refi', kind: 'flow', series: (s) => s.debtDraws },
    { key: 'interest', label: 'Interest', kind: 'flow', series: (s) => s.interest, indent: true },
    { key: 'principal', label: 'Principal', kind: 'flow', series: (s) => s.principal, indent: true },
    { key: 'debtService', label: 'Debt service', kind: 'flow', series: (s) => s.debtService },
    { key: 'loanBalance', label: 'Loan balance (end)', kind: 'balance', series: (s) => s.loanBalance },
    { key: 'leasingCapital', label: 'Leasing capital (TI/LC)', kind: 'flow', series: (s) => s.leasingCapital ?? [] },
  )
  if (statement.renovationCapex) {
    // J1: present only for deals with a renovation program.
    rows.push({
      key: 'renovationCapex',
      label: 'Renovation capex',
      kind: 'flow',
      series: (s) => s.renovationCapex ?? [],
    })
  }
  if (statement.replacementReserves) {
    // J6: below-NOI reserves — a capital row like TI/LC.
    rows.push({
      key: 'replacementReserves',
      label: 'Replacement reserves (below NOI)',
      kind: 'flow',
      series: (s) => s.replacementReserves ?? [],
    })
  }
  if (statement.escrowFlows) {
    // J6: escrow timing — funded at close, released at exit.
    rows.push({
      key: 'escrowFlows',
      label: 'Tax & insurance escrows',
      kind: 'flow',
      series: (s) => s.escrowFlows ?? [],
    })
  }
  rows.push(
    { key: 'saleProceedsNet', label: 'Net sale proceeds', kind: 'flow', series: (s) => s.saleProceedsNet },
    { key: 'unlevered', label: 'Unlevered cash flow', kind: 'flow', series: (s) => s.unlevered },
    { key: 'levered', label: 'Levered cash flow', kind: 'flow', series: (s) => s.levered },
    { key: 'lpDistributions', label: 'LP cash flow', kind: 'flow', series: (s) => s.lpDistributions, indent: true },
    { key: 'gpDistributions', label: 'GP cash flow', kind: 'flow', series: (s) => s.gpDistributions, indent: true },
  )
  return rows
}

export type StatementComponent = 'blended' | 'residential' | 'commercial'

/** H2: view a mixed deal's income statement through one component. Income
 *  rows come from the component vectors; opex/NOI use the reporting
 *  allocation; capital and debt rows stay blended (they aren't split). */
export function filterComponent(statement: Statement, component: StatementComponent): Statement {
  if (component === 'blended' || !statement.components) return statement
  const comp = statement.components[component]
  if (!comp) return statement
  return {
    ...statement,
    gpr: comp.gpr,
    vacancyLoss: comp.vacancyLoss,
    creditLoss: comp.creditLoss,
    otherIncome: comp.otherIncome,
    egi: comp.egi,
    opexTotal: comp.opex,
    noi: comp.noi,
    // category detail and management fee aren't component-split — hide them
    // rather than show blended numbers under a component heading.
    fixedOpexByCategory: {},
    managementFee: comp.opex.map(() => 0),
  }
}

export interface PeriodColumn {
  label: string
  /** statement indices contributing to this column */
  indices: number[]
  /** dominant phase for the phase band */
  phase: string
  /** fiscal year number, or null for the Close column */
  year: number | null
}

/** Close (index 0) alone, then months 1..N in 12-month fiscal years. */
export function groupIntoYears(statement: Statement): PeriodColumn[] {
  const columns: PeriodColumn[] = [
    { label: 'Close', indices: [0], phase: 'close', year: null },
  ]
  const total = statement.months.length - 1
  for (let start = 1; start <= total; start += 12) {
    const indices: number[] = []
    for (let m = start; m <= Math.min(start + 11, total); m++) indices.push(m)
    const year = Math.floor((start - 1) / 12) + 1
    columns.push({
      label: `Year ${year}`,
      indices,
      phase: dominantPhase(statement, indices),
      year,
    })
  }
  return columns
}

export function monthColumns(statement: Statement, year: number): PeriodColumn[] {
  const start = (year - 1) * 12 + 1
  const total = statement.months.length - 1
  const columns: PeriodColumn[] = []
  for (let m = start; m <= Math.min(start + 11, total); m++) {
    columns.push({ label: `M${m}`, indices: [m], phase: statement.phases[m], year })
  }
  return columns
}

function dominantPhase(statement: Statement, indices: number[]): string {
  const counts = new Map<string, number>()
  for (const i of indices) {
    const phase = statement.phases[i]
    counts.set(phase, (counts.get(phase) ?? 0) + 1)
  }
  let best = ''
  let bestCount = -1
  for (const [phase, count] of counts) {
    if (count > bestCount) {
      best = phase
      bestCount = count
    }
  }
  return best
}

/** Column value for a row: sum for flows, period-end value for balances. */
export function cellValue(row: StatementRow, statement: Statement, column: PeriodColumn): number {
  const series = row.series(statement)
  if (row.kind === 'balance') {
    return series[column.indices[column.indices.length - 1]] ?? 0
  }
  return column.indices.reduce((acc, i) => acc + (series[i] ?? 0), 0)
}

export function rowTotal(row: StatementRow, statement: Statement): number | null {
  if (row.kind === 'balance') return null // a summed balance is meaningless
  const series = row.series(statement)
  return series.reduce((acc, v) => acc + v, 0)
}

function csvEscape(text: string): string {
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function statementToCsv(
  statement: Statement,
  granularity: 'annual' | 'monthly',
): string {
  const columns =
    granularity === 'annual'
      ? groupIntoYears(statement)
      : [
          { label: 'Close', indices: [0], phase: 'close', year: null } as PeriodColumn,
          ...statement.months.slice(1).map((m) => ({
            label: `Month ${m}`,
            indices: [m],
            phase: statement.phases[m],
            year: null,
          })),
        ]
  const rows = statementRows(statement)
  const lines: string[] = []
  lines.push(['Line item', ...columns.map((c) => c.label), 'Total'].map(csvEscape).join(','))
  lines.push(['Phase', ...columns.map((c) => c.phase), ''].map(csvEscape).join(','))
  for (const row of rows) {
    const total = rowTotal(row, statement)
    lines.push(
      [
        csvEscape(row.label),
        ...columns.map((c) => String(Math.round(cellValue(row, statement, c) * 100) / 100)),
        total === null ? '' : String(Math.round(total * 100) / 100),
      ].join(','),
    )
  }
  return lines.join('\n')
}
