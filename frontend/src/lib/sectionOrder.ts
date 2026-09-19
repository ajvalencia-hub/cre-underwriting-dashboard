// Display order of the deal-input sections. The schema's order starts with
// 28 financing fields and puts price / cost basis ninth; analysts enter a
// deal the other way round — what it is and what it costs, what it earns,
// what it costs to run, how it exits, then how it's financed. Presentation
// only: input_schema.json (which drives mapping, memo and export) is
// untouched, and any section not listed keeps its schema position at the end.

const DISPLAY_ORDER = [
  'deal_basics',
  'acquisition_specific',
  'development_specific',
  'operating_income',
  'multifamily_unit_mix',
  'sf_townhouse',
  'retail_rent_roll',
  'commercial_rent_roll',
  'industrial_details',
  'hotel_details',
  'office_details',
  'custom_other',
  'operating_expenses',
  'renovation_program',
  'growth_assumptions',
  'exit_assumptions',
  'financing',
  'equity_structure',
]

export function orderSections<T extends { id: string }>(sections: T[]): T[] {
  const rank = (id: string) => {
    const i = DISPLAY_ORDER.indexOf(id)
    return i === -1 ? DISPLAY_ORDER.length : i
  }
  return sections
    .map((section, index) => ({ section, index }))
    .sort((a, b) => rank(a.section.id) - rank(b.section.id) || a.index - b.index)
    .map(({ section }) => section)
}
