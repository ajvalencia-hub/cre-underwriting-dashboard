import { describe, expect, it } from 'vitest'
import { commandScore, searchCommands, type PaletteCommand } from './commandSearch'

const cmd = (id: string, group: PaletteCommand['group'], title: string, extra: Partial<PaletteCommand> = {}) => ({
  id,
  group,
  title,
  run: () => {},
  ...extra,
})

const COMMANDS: PaletteCommand[] = [
  cmd('compute', 'actions', 'Compute', { keywords: 'run calculate' }),
  cmd('tab-cashflow', 'tabs', 'Cash Flow'),
  cmd('field-exitCapRatePct', 'fields', 'Exit Cap Rate', { subtitle: 'Exit Assumptions', keywords: 'exitCapRatePct' }),
  cmd('field-capRate', 'fields', 'Going-in Cap Rate', { subtitle: 'Acquisition Details' }),
  cmd('field-ltv', 'fields', 'LTV or LTC', { subtitle: 'Financing', keywords: 'ltvOrLtc leverage' }),
]

describe('commandScore', () => {
  it('ranks prefix over word start over substring over letters in order', () => {
    const c = cmd('x', 'fields', 'Exit Cap Rate')
    expect(commandScore('exit', c)).toBeGreaterThan(commandScore('cap', c))
    expect(commandScore('cap', c)).toBeGreaterThan(commandScore('xit', c))
    expect(commandScore('xit', c)).toBeGreaterThan(commandScore('ecr', c))
    expect(commandScore('ecr', c)).toBeGreaterThan(0)
    expect(commandScore('zzz', c)).toBe(0)
  })

  it('matches keywords and subtitles below the title', () => {
    expect(commandScore('leverage', COMMANDS[4])).toBeGreaterThan(0)
    expect(commandScore('financing', COMMANDS[4])).toBeGreaterThan(0)
    expect(commandScore('ltv', COMMANDS[4])).toBeGreaterThan(commandScore('leverage', COMMANDS[4]))
  })
})

describe('searchCommands', () => {
  it('lists actions and tabs, not fields, for an empty query', () => {
    expect(searchCommands(COMMANDS, '').map((c) => c.id)).toEqual(['compute', 'tab-cashflow'])
  })

  it('puts the best match first and caps each group', () => {
    const ids = searchCommands(COMMANDS, 'cap', { fields: 1 }).map((c) => c.id)
    expect(ids).toEqual(['field-exitCapRatePct'])
  })

  it('finds an action by keyword', () => {
    expect(searchCommands(COMMANDS, 'calc').map((c) => c.id)).toEqual(['compute'])
  })
})
