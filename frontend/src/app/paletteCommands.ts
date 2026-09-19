import { NAV_GROUPS, type Tab } from './navigation'
import type { PaletteCommand } from '../lib/commandSearch'
import type { DealType } from '../lib/dealStages'
import { visibleFields } from '../lib/schemaFields'
import type { InputSchema } from '../types/schema'

export interface PaletteActions {
  compute: () => void
  newDeal: (type: DealType) => void
  newDealFromDocuments: () => void
  exportDeal: () => void
  openDates: () => void
}

/** Everything ⌘K can do without a server round trip (roadmap #30): the
 *  common actions, every tab, and each Deal Inputs field visible for this
 *  deal (hidden ones — a purchase price on a development — are left out). */
export function buildPaletteCommands(
  schema: InputSchema,
  values: Record<string, unknown>,
  goToTab: (tab: Tab) => void,
  goToField: (fieldId: string) => void,
  actions: PaletteActions,
): PaletteCommand[] {
  const commands: PaletteCommand[] = [
    { id: 'action-compute', group: 'actions', title: 'Compute', subtitle: 'Run the pro forma on the inputs on screen', keywords: 'run calculate recompute', shortcut: '⌘↩', run: actions.compute },
    { id: 'action-new-acquisition', group: 'actions', title: 'New acquisition deal', keywords: 'create add', run: () => actions.newDeal('acquisition') },
    { id: 'action-new-development', group: 'actions', title: 'New development deal', keywords: 'create add ground-up', run: () => actions.newDeal('development') },
    { id: 'action-new-from-documents', group: 'actions', title: 'New deal from documents', subtitle: 'Offering memorandum, rent roll, T-12', keywords: 'om wizard extract create', run: actions.newDealFromDocuments },
    { id: 'action-export', group: 'actions', title: 'Export deal', subtitle: 'Save this deal and its scenarios as a file', keywords: 'download bundle json', run: actions.exportDeal },
    { id: 'action-dates', group: 'actions', title: 'Edit critical dates', keywords: 'closing deadline calendar', run: actions.openDates },
  ]
  for (const group of NAV_GROUPS) {
    for (const [tab, label] of group.items) {
      commands.push({ id: `tab-${tab}`, group: 'tabs', title: label, subtitle: group.label || undefined, keywords: tab, run: () => goToTab(tab) })
    }
  }
  for (const field of visibleFields(schema, values)) {
    commands.push({
      id: `field-${field.id}`,
      group: 'fields',
      title: field.label,
      subtitle: field.sectionLabel,
      keywords: field.id,
      run: () => goToField(field.id),
    })
  }
  return commands
}
