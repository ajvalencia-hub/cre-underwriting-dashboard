import { describe, expect, it, vi } from 'vitest'
import { buildPaletteCommands } from './paletteCommands'
import type { InputSchema } from '../types/schema'

const schema = {
  sections: [
    {
      id: 'acq',
      label: 'Acquisition Details',
      visibleWhen: { all: [{ field: 'dealType', equals: 'acquisition' }] },
      fields: [{ id: 'purchasePrice', label: 'Purchase Price', type: 'currency', required: false }],
    },
    {
      id: 'dev',
      label: 'Development Details',
      visibleWhen: { all: [{ field: 'dealType', equals: 'development' }] },
      fields: [{ id: 'landCost', label: 'Land Cost', type: 'currency', required: false }],
    },
  ],
  outputs: [],
} as unknown as InputSchema

const actions = {
  compute: vi.fn(),
  newDeal: vi.fn(),
  newDealFromDocuments: vi.fn(),
  exportDeal: vi.fn(),
  openDates: vi.fn(),
}

describe('buildPaletteCommands', () => {
  it("offers only the fields visible for the deal's type", () => {
    const ids = buildPaletteCommands(schema, { dealType: 'development' }, vi.fn(), vi.fn(), actions)
      .filter((c) => c.group === 'fields')
      .map((c) => c.id)
    expect(ids).toEqual(['field-landCost'])
  })

  it('wires tabs, fields and actions to their handlers', () => {
    const goToTab = vi.fn()
    const goToField = vi.fn()
    const commands = buildPaletteCommands(schema, { dealType: 'acquisition' }, goToTab, goToField, actions)
    const run = (id: string) => commands.find((c) => c.id === id)!.run()
    run('tab-cashflow')
    run('field-purchasePrice')
    run('action-new-development')
    expect(goToTab).toHaveBeenCalledWith('cashflow')
    expect(goToField).toHaveBeenCalledWith('purchasePrice')
    expect(actions.newDeal).toHaveBeenCalledWith('development')
  })
})
