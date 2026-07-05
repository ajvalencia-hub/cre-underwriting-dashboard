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
  managementFeeFixed: 'Management fee (fixed $)',
  otherOpex: 'Other opex',
}

export function statementRows(statement: Statement): StatementRow[] {
  const rows: StatementRow[] = [
    { key: 'gpr', label: 'Gross potential rent', kind: 'flow', series: (s) => s.gpr },
    { key: 'vacancyLoss', label: 'Less: vacancy', kind: 'flow', series: (s) => s.vacancyLoss, indent: true },
    { key: 'creditLoss', label: 'Less: credit loss', kind: 'flow', series: (s) => s.creditLoss, indent: true },
    { key: 'otherIncome', label: 'Other income', kind: 'flow', series: (s) => s.otherIncome, indent: true },
    { key: 'egi', label: 'Effective gross income', kind: 'flow', series: (s) => s.egi },
  ]
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
