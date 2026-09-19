// STUB (Phase 0, F1) — F3 replaces the body with the Run 6 deal comparison
// (lib/compareMath.ts). Keep the props interface; App.tsx already mounts it:
//
//   <PanelBoundary name="Compare">
//     <ComparePage schema={schema} deals={deals} active={tab === 'compare'} onOpenDeal={…} />
//   </PanelBoundary>
//
// Props:
// - schema:     the input schema (labels, output metrics, visibility rules).
// - deals:      App's working deal list (non-archived; full DealOut rows
//               WITH inputs — no need to refetch for a first paint).
// - active:     true while the Compare tab is showing (tab divs stay
//               mounted; fetch/compute lazily when it first becomes true).
// - onOpenDeal: switch to a deal and show its Deal Inputs (App saves the
//               current deal first; resolves after the switch).
//
// Compare is in MULTI_DEAL_TABS (no one-deal summary panel beside it). CSV
// export must go through saveOutput(textBlob(...)) (desktop-safe), errors
// through toastError('What failed', err), money through formatOutputValue.
import type { InputSchema } from '../types/schema'
import type { Deal } from '../types/deal'

export interface ComparePageProps {
  schema: InputSchema
  deals: Deal[]
  active: boolean
  onOpenDeal: (dealId: string) => Promise<void>
}

export default function ComparePage({ deals }: ComparePageProps) {
  return (
    <div className="max-w-3xl rounded-md border border-slate-200 bg-white p-4 text-sm text-slate-600">
      <h2 className="text-sm font-semibold text-slate-800">Compare deals</h2>
      <p className="mt-1 text-xs text-slate-500">
        Side-by-side comparison of {deals.length} deal{deals.length === 1 ? '' : 's'} is coming soon.
      </p>
    </div>
  )
}
