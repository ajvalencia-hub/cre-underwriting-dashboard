import { useMemo } from 'react'
import ScalarInput from './fields/ScalarInput'
import {
  ACQUISITION_FEASIBILITY,
  computeAcquisitionQuickScreen,
  mapAcquisitionQuickScreenToDealInputs,
  solveAcquisitionPriceForTier,
  solveAcquisitionRentForTier,
  type AcquisitionQuickScreenInputs,
} from '../lib/quickScreenMath'
import { formatMoney, formatPct } from '../lib/quickScreenFormat'

interface AcquisitionQuickScreenProps {
  inputs: AcquisitionQuickScreenInputs
  onInputsChange: (inputs: AcquisitionQuickScreenInputs) => void
  onSendToDealInputs: (values: Record<string, unknown>) => void
}

const VERDICT_LABEL: Record<string, string> = {
  strong: `Strong — cash-on-cash ≥ ${ACQUISITION_FEASIBILITY.strong.cashOnCash * 100}% and DSCR ≥ ${ACQUISITION_FEASIBILITY.strong.dscr}`,
  marginal: `Marginal — cash-on-cash ≥ ${ACQUISITION_FEASIBILITY.marginal.cashOnCash * 100}% and DSCR ≥ ${ACQUISITION_FEASIBILITY.marginal.dscr}`,
  weak: 'Weak — thin cash-on-cash or coverage at these terms',
}
const VERDICT_COLOR: Record<string, string> = {
  strong: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  marginal: 'border-amber-200 bg-amber-50 text-amber-700',
  weak: 'border-red-200 bg-red-50 text-red-700',
}

const FIELDS: {
  key: keyof AcquisitionQuickScreenInputs
  label: string
  type: 'currency' | 'percent' | 'number'
  hint?: string
}[] = [
  { key: 'purchasePrice', label: 'Purchase Price', type: 'currency' },
  { key: 'closingCostsPct', label: 'Closing Costs (% of price)', type: 'percent' },
  { key: 'quantity', label: '# of Units', type: 'number' },
  { key: 'rent', label: 'Monthly Rent per Unit', type: 'currency' },
  {
    key: 'noiMarginPct', label: 'NOI Margin (% of gross rent)', type: 'percent',
    hint: 'Share of gross potential rent surviving vacancy + opex.',
  },
  { key: 'exitCapRatePct', label: 'Exit / Market Cap Rate', type: 'percent' },
  { key: 'ltvPct', label: 'LTV (0 = all-cash)', type: 'percent' },
  { key: 'interestRatePct', label: 'Interest Rate', type: 'percent' },
  { key: 'amortYears', label: 'Amortization (yrs, 0 = IO)', type: 'number' },
]

/** The acquisition-side back-of-napkin: cap rate, cash-on-cash, DSCR — the
 *  counterpart of the development yield-on-cost screen. All math lives in
 *  quickScreenMath.computeAcquisitionQuickScreen; state is lifted to App for
 *  URL sharing and sidebar estimates. */
export default function AcquisitionQuickScreen({
  inputs,
  onInputsChange,
  onSendToDealInputs,
}: AcquisitionQuickScreenProps) {
  const results = useMemo(() => computeAcquisitionQuickScreen(inputs), [inputs])

  // Solve-for hints toward the NEXT tier (closed form, both verdict legs).
  const nextTier =
    results.feasibility === 'weak'
      ? ('marginal' as const)
      : results.feasibility === 'marginal'
        ? ('strong' as const)
        : null
  const solve = useMemo(() => {
    if (!nextTier) return null
    const target = ACQUISITION_FEASIBILITY[nextTier]
    return {
      tier: nextTier,
      price: solveAcquisitionPriceForTier(inputs, target.cashOnCash, target.dscr),
      rent: solveAcquisitionRentForTier(inputs, target.cashOnCash, target.dscr),
    }
  }, [inputs, nextTier])

  function set(key: keyof AcquisitionQuickScreenInputs, value: unknown) {
    // Numbers only — a blank would propagate NaN through every result.
    if (typeof value !== 'number' || !Number.isFinite(value)) return
    onInputsChange({ ...inputs, [key]: value })
  }

  return (
    <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2">
      <div className="space-y-4 rounded-md border border-slate-200 bg-white p-4">
        {FIELDS.map((field) => (
          <div key={field.key}>
            <label className="block text-xs font-medium text-slate-600">{field.label}</label>
            <div className="mt-1 max-w-xs">
              <ScalarInput
                type={field.type}
                value={inputs[field.key]}
                onChange={(v) => set(field.key, v)}
              />
            </div>
            {field.hint && (
              <div className="mt-0.5 max-w-xs text-[11px] text-slate-400">{field.hint}</div>
            )}
          </div>
        ))}
      </div>

      <div className="space-y-4">
        <div className={`rounded-md border p-3 text-sm ${VERDICT_COLOR[results.feasibility]}`}>
          <span className="font-semibold capitalize">{results.feasibility}</span>{' '}
          <span>{VERDICT_LABEL[results.feasibility]}</span>
          {solve && (solve.price !== null || solve.rent !== null) && (
            <div className="mt-1 text-xs opacity-80">
              To reach <span className="capitalize">{solve.tier}</span>:
              {solve.price !== null && <> price ≤ {formatMoney(solve.price)}</>}
              {solve.price !== null && solve.rent !== null && ' · or'}
              {solve.rent !== null && <> rent ≥ {formatMoney(solve.rent)}/unit/mo</>}
            </div>
          )}
        </div>

        <div className="rounded-md border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold tracking-wide text-slate-500">
            GOING-IN ECONOMICS
          </div>
          <dl className="mt-2 space-y-1 text-sm">
            <Row label="Total basis (incl. closing)" value={formatMoney(results.totalBasis)} />
            <Row label="Gross potential rent" value={formatMoney(results.grossPotentialRent)} />
            <Row label="Stabilized NOI" value={formatMoney(results.stabilizedNoi)} />
            <Row label="Price per unit" value={formatMoney(results.pricePerUnit)} />
            <Row label="Going-in cap rate" value={formatPct(results.goingInCapRate)} strong />
            <Row
              label="Spread vs exit cap"
              value={`${results.capRateSpreadBps >= 0 ? '+' : ''}${Math.round(results.capRateSpreadBps)} bps`}
            />
          </dl>
        </div>

        <div className="rounded-md border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold tracking-wide text-slate-500">
            LEVERAGE (stabilized year{inputs.amortYears > 0 ? ', amortizing' : ', interest-only'})
          </div>
          <dl className="mt-2 space-y-1 text-sm">
            <Row label="Loan amount" value={formatMoney(results.loanAmount)} />
            <Row label="Equity required" value={formatMoney(results.equityRequired)} />
            <Row label="Annual debt service" value={formatMoney(results.annualDebtService)} />
            <Row label="Levered cash flow" value={formatMoney(results.leveredCashFlow)} />
            <Row
              label="Cash-on-cash"
              value={results.cashOnCashPct === null ? '—' : formatPct(results.cashOnCashPct)}
              strong
            />
            <Row
              label="DSCR"
              value={results.minDscr === null ? '— (all-cash)' : `${results.minDscr.toFixed(2)}x`}
            />
            <Row
              label="Debt yield"
              value={results.debtYield === null ? '—' : formatPct(results.debtYield)}
            />
            <Row label="Break-even ratio" value={formatPct(results.breakEvenRatio)} />
          </dl>
        </div>

        <button
          onClick={() => onSendToDealInputs(mapAcquisitionQuickScreenToDealInputs(inputs, results))}
          className="w-full rounded bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-700"
        >
          Send to Deal Inputs →
        </button>
      </div>
    </div>
  )
}

function Row({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`flex justify-between ${strong ? 'border-t border-slate-100 pt-1 font-medium' : ''}`}>
      <span className="text-slate-500">{label}</span>
      <span className={strong ? 'text-slate-900' : 'text-slate-700'}>{value}</span>
    </div>
  )
}
