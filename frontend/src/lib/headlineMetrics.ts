/** Roadmap #26: mirrors backend for_sale.applies — a development of
 *  single-family homes or townhouses, for sale, with a sale price entered. */
export function isForSaleDeal(values: Record<string, unknown> | undefined): boolean {
  if (!values) return false
  return (
    values.dealType === 'development' &&
    (values.propertyType === 'single_family' || values.propertyType === 'townhouse') &&
    values.isForSale !== false &&
    typeof values.salePricePerHome === 'number' &&
    values.salePricePerHome > 0
  )
}

/** The go/no-go read, in order. Development deals are judged on yield and
 *  spread over exit cap; acquisitions on going-in cap and year-1 cash yield;
 *  build-to-sell deals on margin, peak equity and how long the sellout takes. */
export function headlineIds(dealType: unknown, forSale = false): string[] {
  if (forSale) return ['leveredIrr', 'unleveredIrr', 'equityMultiple', 'grossMarginPct', 'peakEquity', 'selloutYears']
  return dealType === 'development'
    ? ['leveredIrr', 'unleveredIrr', 'equityMultiple', 'yieldOnCost', 'developmentSpreadBps', 'minDscr']
    : ['leveredIrr', 'unleveredIrr', 'equityMultiple', 'goingInCapRate', 'cashOnCashYear1', 'minDscr']
}
