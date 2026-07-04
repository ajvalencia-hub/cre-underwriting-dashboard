import { describe, expect, it } from 'vitest'
import {
  cellValue,
  groupIntoYears,
  monthColumns,
  rowTotal,
  statementRows,
  statementToCsv,
  type Statement,
} from './cashflowStatement'

/** 26-month statement: close + 25 months (2 full years + 1 month). */
function makeStatement(): Statement {
  const n = 26
  const zeros = () => new Array<number>(n).fill(0)
  const noi = zeros()
  for (let m = 1; m < n; m++) noi[m] = 100 + m // distinct values per month
  const phases = ['close', ...Array<string>(5).fill('construction'), ...Array<string>(20).fill('stabilized')]
  return {
    months: Array.from({ length: n }, (_, i) => i),
    phases,
    constructionMonths: 5,
    stabilizationMonth: 6,
    exitMonth: 25,
    gpr: noi.map((v) => v * 2),
    vacancyLoss: zeros(),
    creditLoss: zeros(),
    otherIncome: zeros(),
    egi: noi.map((v) => v * 2),
    fixedOpexByCategory: { realEstateTaxes: noi.map((v) => v * 0.5) },
    managementFee: noi.map((v) => v * 0.5),
    opexTotal: noi,
    noi,
    occupancy: zeros(),
    costs: zeros(),
    loanFees: zeros(),
    equityFunded: zeros(),
    debtDraws: zeros(),
    interest: zeros(),
    principal: zeros(),
    debtService: zeros(),
    loanBalance: Array.from({ length: n }, (_, i) => 1000 - i), // declining balance
    saleProceedsNet: zeros(),
    saleProceedsGross: zeros(),
    recoveries: zeros(),
    leasingCapital: zeros(),
    unlevered: noi,
    levered: noi,
    lpDistributions: noi.map((v) => v * 0.9),
    gpDistributions: noi.map((v) => v * 0.1),
  }
}

describe('groupIntoYears', () => {
  it('puts close alone, then 12-month fiscal years with a partial tail', () => {
    const groups = groupIntoYears(makeStatement())
    expect(groups.map((g) => g.label)).toEqual(['Close', 'Year 1', 'Year 2', 'Year 3'])
    expect(groups[0].indices).toEqual([0])
    expect(groups[1].indices).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
    expect(groups[3].indices).toEqual([25]) // partial final year
  })

  it('labels the dominant phase per year', () => {
    const groups = groupIntoYears(makeStatement())
    expect(groups[0].phase).toBe('close')
    expect(groups[1].phase).toBe('stabilized') // 5 construction vs 7 stabilized months in year 1
  })
})

describe('cellValue / rowTotal', () => {
  const statement = makeStatement()
  const noiRow = statementRows(statement).find((r) => r.key === 'noi')!
  const balanceRow = statementRows(statement).find((r) => r.key === 'loanBalance')!

  it('annual cell equals the sum of its months for flow rows', () => {
    const year1 = groupIntoYears(statement)[1]
    const expected = statement.noi.slice(1, 13).reduce((a, b) => a + b, 0)
    expect(cellValue(noiRow, statement, year1)).toBeCloseTo(expected, 9)
    // and the expanded month columns sum to the same year cell
    const monthSum = monthColumns(statement, 1)
      .map((c) => cellValue(noiRow, statement, c))
      .reduce((a, b) => a + b, 0)
    expect(monthSum).toBeCloseTo(expected, 9)
  })

  it('balance rows report period-end, not a sum, and have no total', () => {
    const year1 = groupIntoYears(statement)[1]
    expect(cellValue(balanceRow, statement, year1)).toBe(statement.loanBalance[12])
    expect(rowTotal(balanceRow, statement)).toBeNull()
  })

  it('flow row totals equal the full-series sum', () => {
    expect(rowTotal(noiRow, statement)).toBeCloseTo(
      statement.noi.reduce((a, b) => a + b, 0),
      9,
    )
  })
})

describe('statementToCsv', () => {
  it('emits a header, phase band, and one line per row', () => {
    const statement = makeStatement()
    const csv = statementToCsv(statement, 'annual')
    const lines = csv.split('\n')
    expect(lines[0].startsWith('Line item,Close,Year 1,Year 2,Year 3,Total')).toBe(true)
    expect(lines[1].startsWith('Phase,')).toBe(true)
    expect(lines.length).toBe(2 + statementRows(statement).length)
  })

  it('monthly granularity has one column per month plus close and total', () => {
    const statement = makeStatement()
    const header = statementToCsv(statement, 'monthly').split('\n')[0]
    expect(header.split(',').length).toBe(1 + 1 + 25 + 1) // label + close + 25 months + total
  })
})
