import { describe, expect, it } from 'vitest'
import { fieldInputId } from './fieldIds'

describe('fieldInputId', () => {
  it('prefixes and slugs the field id', () => {
    expect(fieldInputId('field', 'purchasePrice')).toBe('field-purchasePrice')
    expect(fieldInputId('qs', 'Monthly Rent per Unit')).toBe('qs-Monthly-Rent-per-Unit')
    expect(fieldInputId('x', '  ')).toBe('x-field')
  })
})
