/** The go/no-go read, in order. Development deals are judged on yield and
 *  spread over exit cap; acquisitions on going-in cap and year-1 cash yield. */
export function headlineIds(dealType: unknown): string[] {
  return dealType === 'development'
    ? ['leveredIrr', 'unleveredIrr', 'equityMultiple', 'yieldOnCost', 'developmentSpreadBps', 'minDscr']
    : ['leveredIrr', 'unleveredIrr', 'equityMultiple', 'goingInCapRate', 'cashOnCashYear1', 'minDscr']
}
