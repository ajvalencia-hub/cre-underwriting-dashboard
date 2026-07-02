import { useState } from 'react'
import ScalarInput from '../components/fields/ScalarInput'
import {
  computeQuickScreen,
  QUICK_SCREEN_DEFAULTS,
  type QuickScreenInputs,
  type SizeMode,
} from '../lib/quickScreenMath'

interface QuickScreenProps {
  onSendToDealInputs: (values: Record<string, unknown>) => void
}

function pct(v: number): string {
  return `${(v * 100).toFixed(2)}%`
}

function money(v: number): string {
  return `$${Math.round(v).toLocaleString()}`
}

const FEASIBILITY_LABEL: Record<string, string> = {
  strong: 'Strong — yield-on-cost clears exit cap by 200+ bps',
  marginal: 'Marginal — yield-on-cost clears exit cap by 100–200 bps',
  weak: 'Weak — yield-on-cost is within 100 bps of (or below) exit cap',
}
const FEASIBILITY_COLOR: Record<string, string> = {
  strong: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  marginal: 'border-amber-200 bg-amber-50 text-amber-700',
  weak: 'border-red-200 bg-red-50 text-red-700',
}

export default function QuickScreen({ onSendToDealInputs }: QuickScreenProps) {
  const [inputs, setInputs] = useState<QuickScreenInputs>(QUICK_SCREEN_DEFAULTS)
  const results = computeQuickScreen(inputs)

  function set<K extends keyof QuickScreenInputs>(key: K, value: QuickScreenInputs[K]) {
    setInputs((prev) => ({ ...prev, [key]: value }))
  }

  function setNum(key: keyof QuickScreenInputs, value: unknown) {
    const num = Number(value)
    setInputs((prev) => ({ ...prev, [key]: Number.isFinite(num) ? num : 0 }))
  }

  function handleSendToDealInputs() {
    onSendToDealInputs({
      dealType: 'development',
      landCost: inputs.landCost,
      hardCosts: results.hardCosts,
      contingencyPct: inputs.contingencyPct,
      exitCapRatePct: inputs.exitCapRatePct,
      ltvOrLtc: inputs.ltcPct,
      grossPotentialRent: results.grossPotentialRent,
    })
  }

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold">Back-of-Napkin Screen</h1>
      <p className="mt-1 text-slate-500">
        A handful of inputs to see whether a development deal is worth underwriting in full — no template
        or mapping required.
      </p>

      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="space-y-4 rounded-md border border-slate-200 bg-white p-4">
          <div>
            <label className="block text-xs font-medium text-slate-600">Sized by</label>
            <div className="mt-1 flex gap-3 text-sm">
              {(['units', 'sf'] as SizeMode[]).map((mode) => (
                <label key={mode} className="flex items-center gap-1">
                  <input
                    type="radio"
                    checked={inputs.sizeMode === mode}
                    onChange={() => set('sizeMode', mode)}
                  />
                  {mode === 'units' ? 'Units' : 'Square Feet'}
                </label>
              ))}
            </div>
          </div>

          <FieldRow label={inputs.sizeMode === 'units' ? '# of Units' : 'Total Building SF'}>
            <ScalarInput type="number" value={inputs.quantity} onChange={(v) => setNum('quantity', v)} />
          </FieldRow>

          <FieldRow label="Land Cost">
            <ScalarInput type="currency" value={inputs.landCost} onChange={(v) => setNum('landCost', v)} />
          </FieldRow>

          <FieldRow label={inputs.sizeMode === 'units' ? 'Hard Cost per Unit' : 'Hard Cost per SF'}>
            <ScalarInput
              type="currency"
              value={inputs.hardCostPerUnit}
              onChange={(v) => setNum('hardCostPerUnit', v)}
            />
          </FieldRow>

          <FieldRow label="Soft Costs (% of hard cost)">
            <ScalarInput
              type="percent"
              value={inputs.softCostPct}
              onChange={(v) => setNum('softCostPct', v)}
            />
          </FieldRow>

          <FieldRow label="Contingency (% of hard + soft)">
            <ScalarInput
              type="percent"
              value={inputs.contingencyPct}
              onChange={(v) => setNum('contingencyPct', v)}
            />
          </FieldRow>

          <FieldRow label={inputs.sizeMode === 'units' ? 'Monthly Rent per Unit' : 'Annual Rent per SF'}>
            <ScalarInput type="currency" value={inputs.rent} onChange={(v) => setNum('rent', v)} />
          </FieldRow>

          <FieldRow label="Stabilized NOI Margin (% of gross rent)">
            <ScalarInput
              type="percent"
              value={inputs.noiMarginPct}
              onChange={(v) => setNum('noiMarginPct', v)}
            />
          </FieldRow>

          <FieldRow label="Exit Cap Rate">
            <ScalarInput
              type="percent"
              value={inputs.exitCapRatePct}
              onChange={(v) => setNum('exitCapRatePct', v)}
            />
          </FieldRow>

          <FieldRow label="Loan-to-Cost (0 = all-equity)">
            <ScalarInput type="percent" value={inputs.ltcPct} onChange={(v) => setNum('ltcPct', v)} />
          </FieldRow>

          <FieldRow label="Construction Loan Rate (interest-only approx.)">
            <ScalarInput
              type="percent"
              value={inputs.constructionInterestRatePct}
              onChange={(v) => setNum('constructionInterestRatePct', v)}
            />
          </FieldRow>
        </div>

        <div className="space-y-4">
          <div className={`rounded-md border p-3 text-sm ${FEASIBILITY_COLOR[results.feasibility]}`}>
            <div className="font-semibold capitalize">{results.feasibility}</div>
            <div className="mt-0.5 text-xs">{FEASIBILITY_LABEL[results.feasibility]}</div>
          </div>

          <div className="rounded-md border border-slate-200 bg-white p-4">
            <div className="text-xs font-semibold tracking-wide text-slate-500">DEVELOPMENT COST</div>
            <dl className="mt-2 space-y-1 text-sm">
              <Row label="Hard Costs" value={money(results.hardCosts)} />
              <Row label="Soft Costs" value={money(results.softCosts)} />
              <Row label="Contingency" value={money(results.contingency)} />
              <Row label="Land Cost" value={money(inputs.landCost)} />
              <Row label="Total Development Cost" value={money(results.totalDevelopmentCost)} strong />
            </dl>
          </div>

          <div className="rounded-md border border-slate-200 bg-white p-4">
            <div className="text-xs font-semibold tracking-wide text-slate-500">STABILIZED VALUE</div>
            <dl className="mt-2 space-y-1 text-sm">
              <Row label="Gross Potential Rent" value={money(results.grossPotentialRent)} />
              <Row label="Stabilized NOI" value={money(results.stabilizedNoi)} />
              <Row label="Stabilized Value (NOI / exit cap)" value={money(results.stabilizedValue)} strong />
            </dl>
          </div>

          <div className="rounded-md border border-slate-200 bg-white p-4">
            <div className="text-xs font-semibold tracking-wide text-slate-500">FEASIBILITY</div>
            <dl className="mt-2 space-y-1 text-sm">
              <Row label="Profit" value={money(results.profit)} />
              <Row label="Profit Margin" value={pct(results.profitMarginPct)} />
              <Row label="Yield on Cost" value={pct(results.yieldOnCost)} />
              <Row label="Spread over Exit Cap" value={`${results.capRateSpreadBps.toFixed(0)} bps`} strong />
            </dl>
          </div>

          {inputs.ltcPct > 0 && (
            <div className="rounded-md border border-slate-200 bg-white p-4">
              <div className="text-xs font-semibold tracking-wide text-slate-500">
                SIMPLE LEVERAGE (stabilized year, interest-only approximation)
              </div>
              <dl className="mt-2 space-y-1 text-sm">
                <Row label="Loan Amount" value={money(results.loanAmount)} />
                <Row label="Equity Required" value={money(results.equityRequired)} />
                <Row label="Levered Cash Flow" value={money(results.leveredCashFlow)} />
                <Row
                  label="Cash-on-Cash"
                  value={results.cashOnCashPct === null ? '—' : pct(results.cashOnCashPct)}
                  strong
                />
              </dl>
            </div>
          )}

          <button
            onClick={handleSendToDealInputs}
            className="w-full rounded bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-700"
          >
            Send to Deal Inputs →
          </button>
        </div>
      </div>
    </div>
  )
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600">{label}</label>
      <div className="mt-1 max-w-xs">{children}</div>
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
