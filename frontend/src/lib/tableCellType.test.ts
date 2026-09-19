import { describe, expect, it } from 'vitest'
import { cellType, columnLabel } from './tableCellType'

describe('mixed-unit table cells', () => {
  it('opex amount is a percent only on a % of EGI basis', () => {
    expect(cellType('opexLineItems', 'amount', { basis: 'pct_of_egi' }, 'number')).toBe('percent')
    expect(cellType('opexLineItems', 'amount', { basis: 'per_unit' }, 'number')).toBe('currency')
    expect(cellType('opexLineItems', 'amount', {}, 'number')).toBe('currency')
  })

  it('lease escalation follows its type', () => {
    expect(cellType('commercialLeases', 'escalationValue', { escalationType: 'fixed_pct' }, 'number')).toBe('percent')
    expect(cellType('commercialLeases', 'escalationValue', { escalationType: 'fixed_step' }, 'number')).toBe('currency')
    expect(cellType('commercialLeases', 'escalationValue', { escalationType: 'none' }, 'number')).toBe('number')
  })

  it('leaves other columns alone and drops the "fraction" wording', () => {
    expect(cellType('unitMix', 'rent', {}, 'currency')).toBe('currency')
    expect(columnLabel('opexLineItems', 'amount', 'Amount ($ or fraction for % of EGI)')).toBe('Amount')
    expect(columnLabel('unitMix', 'rent', 'Rent')).toBe('Rent')
  })
})
