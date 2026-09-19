import { describe, expect, it } from 'vitest'
import { formatMoney, formatMoneyCompact, withDollar } from './money'

describe('money formatting puts the sign first', () => {
  it('formats whole dollars', () => {
    expect(formatMoney(2_116_364)).toBe('$2,116,364')
    expect(formatMoney(-2_116_364.4)).toBe('-$2,116,364')
    expect(formatMoney(-0.4)).toBe('$0') // rounds to zero: no "-$0"
  })

  it('keeps cents when asked', () => {
    expect(formatMoney(-1234.5, { round: false })).toBe('-$1,234.5')
  })

  it('compacts', () => {
    expect(formatMoneyCompact(-1_250_000)).toBe('-$1.3M')
    expect(formatMoneyCompact(-350_400)).toBe('-$350k')
    expect(formatMoneyCompact(900)).toBe('$900')
  })

  it('prefixes pre-formatted text', () => {
    expect(withDollar('-1,234.50')).toBe('-$1,234.50')
    expect(withDollar('1,234.50')).toBe('$1,234.50')
  })
})
