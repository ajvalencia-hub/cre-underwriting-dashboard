// Two table columns hold either dollars or a fraction depending on another
// column in the same row. Typing "3" meaning 3% stored 300% with nothing to
// flag it. The UI now renders those cells by what the row says they are —
// a normal percent field (typed 3, stored 0.03, as before) or a currency
// field — so the stored values and their meaning are unchanged.

import type { FieldType } from '../types/schema'

interface CellRule {
  label: string
  typeFor: (row: Record<string, unknown>) => FieldType
}

const RULES: Record<string, Record<string, CellRule>> = {
  opexLineItems: {
    amount: {
      label: 'Amount',
      typeFor: (row) => (row.basis === 'pct_of_egi' ? 'percent' : 'currency'),
    },
  },
  commercialLeases: {
    escalationValue: {
      label: 'Esc. value',
      typeFor: (row) =>
        row.escalationType === 'fixed_pct' ? 'percent' : row.escalationType === 'fixed_step' ? 'currency' : 'number',
    },
  },
}

export function cellType(tableId: string, columnId: string, row: Record<string, unknown>, declared: FieldType): FieldType {
  return RULES[tableId]?.[columnId]?.typeFor(row) ?? declared
}

export function columnLabel(tableId: string, columnId: string, declared: string): string {
  return RULES[tableId]?.[columnId]?.label ?? declared
}
