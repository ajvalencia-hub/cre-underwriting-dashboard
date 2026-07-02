import FormattedNumberInput from '../components/fields/FormattedNumberInput'
import QuickScreenSensitivityGrid from '../components/QuickScreenSensitivityGrid'
import {
  FEASIBILITY_TIER_THRESHOLDS_BPS,
  QUICK_SCREEN_FIELD_CONFIG,
  QUICK_SCREEN_SF_PER_UNIT_ASSUMPTION,
  deriveOpexRatioFromMargin,
  solveForMarginalThreshold,
  type QuickScreenInputs,
  type QuickScreenResults,
  type SizeMode,
} from '../lib/quickScreenMath'
import { formatMoney, formatMoneyCompact, formatPct } from '../lib/quickScreenFormat'

interface QuickScreenProps {
  inputs: QuickScreenInputs
  onInputsChange: (inputs: QuickScreenInputs) => void
  results: QuickScreenResults
  onSendToDealInputs: () => void
  onSaveAsScenario: () => void
}

const FEASIBILITY_LABEL: Record<string, string> = {
  strong: `Strong — yield-on-cost clears exit cap by ${FEASIBILITY_TIER_THRESHOLDS_BPS.strong}+ bps`,
  marginal: `Marginal — clears exit cap by ${FEASIBILITY_TIER_THRESHOLDS_BPS.marginal}–${FEASIBILITY_TIER_THRESHOLDS_BPS.strong} bps`,
  weak: `Weak — within ${FEASIBILITY_TIER_THRESHOLDS_BPS.marginal} bps of exit cap (or below)`,
}
const FEASIBILITY_COLOR: Record<string, string> = {
  strong: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  marginal: 'border-amber-200 bg-amber-50 text-amber-700',
  weak: 'border-red-200 bg-red-50 text-red-700',
}

export default function QuickScreen({
  inputs,
  onInputsChange,
  results,
  onSendToDealInputs,
  onSaveAsScenario,
}: QuickScreenProps) {
  function set<K extends keyof QuickScreenInputs>(key: K, value: QuickScreenInputs[K]) {
    onInputsChange({ ...inputs, [key]: value })
  }

  function field(key: keyof QuickScreenInputs) {
    return QUICK_SCREEN_FIELD_CONFIG[key]
  }

  function toggleDetailedNoi() {
    if (!inputs.useDetailedNoi) {
      const opexRatioPct = deriveOpexRatioFromMargin(inputs.noiMarginPct, inputs.vacancyPct)
      onInputsChange({ ...inputs, useDetailedNoi: true, opexRatioPct })
    } else {
      onInputsChange({ ...inputs, useDetailedNoi: false, noiMarginPct: results.effectiveNoiMarginPct })
    }
  }

  const sfPerUnitHint =
    inputs.sizeMode === 'units'
      ? `≈ ${formatMoney(inputs.hardCostPerUnit / QUICK_SCREEN_SF_PER_UNIT_ASSUMPTION)}/SF hard cost, ${formatMoney(
          (inputs.rent * 12) / QUICK_SCREEN_SF_PER_UNIT_ASSUMPTION,
        )}/SF/yr rent — assumes ${QUICK_SCREEN_SF_PER_UNIT_ASSUMPTION} SF/unit`
      : `≈ ${formatMoney(
          inputs.hardCostPerUnit * QUICK_SCREEN_SF_PER_UNIT_ASSUMPTION,
        )}/unit hard cost, ${formatMoney(
          (inputs.rent * QUICK_SCREEN_SF_PER_UNIT_ASSUMPTION) / 12,
        )}/mo rent — assumes ${QUICK_SCREEN_SF_PER_UNIT_ASSUMPTION} SF/unit`

  const solveFor = results.feasibility === 'weak' ? solveForMarginalThreshold(inputs) : null
  const unitLabel = inputs.sizeMode === 'units' ? '/unit' : '/SF'
  const rentUnitLabel = inputs.sizeMode === 'units' ? '/mo/unit' : '/SF/yr'

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
            <FormattedNumberInput
              format="number"
              value={inputs.quantity}
              onChange={(v) => set('quantity', v)}
              {...field('quantity')}
            />
          </FieldRow>

          <FieldRow label="Land Cost">
            <FormattedNumberInput
              format="currency"
              value={inputs.landCost}
              onChange={(v) => set('landCost', v)}
              {...field('landCost')}
            />
          </FieldRow>

          <FieldRow
            label={inputs.sizeMode === 'units' ? 'Hard Cost per Unit' : 'Hard Cost per SF'}
            hint={sfPerUnitHint}
          >
            <FormattedNumberInput
              format="currency"
              value={inputs.hardCostPerUnit}
              onChange={(v) => set('hardCostPerUnit', v)}
              {...field('hardCostPerUnit')}
            />
          </FieldRow>

          <FieldRow label="Soft Costs (% of hard cost)">
            <FormattedNumberInput
              format="percent"
              value={inputs.softCostPct}
              onChange={(v) => set('softCostPct', v)}
              {...field('softCostPct')}
            />
          </FieldRow>

          <FieldRow label="Contingency (% of hard + soft)">
            <FormattedNumberInput
              format="percent"
              value={inputs.contingencyPct}
              onChange={(v) => set('contingencyPct', v)}
              {...field('contingencyPct')}
            />
          </FieldRow>

          <FieldRow label={inputs.sizeMode === 'units' ? 'Monthly Rent per Unit' : 'Annual Rent per SF'}>
            <FormattedNumberInput
              format="currency"
              value={inputs.rent}
              onChange={(v) => set('rent', v)}
              {...field('rent')}
            />
          </FieldRow>

          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium text-slate-600">
                Stabilized NOI Margin (% of gross rent)
              </label>
              <button
                onClick={toggleDetailedNoi}
                className="text-[11px] text-slate-400 underline hover:text-slate-600"
              >
                {inputs.useDetailedNoi ? 'Use simple margin' : 'Split vacancy / opex'}
              </button>
            </div>
            {!inputs.useDetailedNoi ? (
              <div className="mt-1 max-w-xs">
                <FormattedNumberInput
                  format="percent"
                  value={inputs.noiMarginPct}
                  onChange={(v) => set('noiMarginPct', v)}
                  {...field('noiMarginPct')}
                />
              </div>
            ) : (
              <div className="mt-1 grid max-w-xs grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] text-slate-500">Vacancy %</label>
                  <FormattedNumberInput
                    format="percent"
                    value={inputs.vacancyPct}
                    onChange={(v) => set('vacancyPct', v)}
                    {...field('vacancyPct')}
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-500">Opex (% of EGI)</label>
                  <FormattedNumberInput
                    format="percent"
                    value={inputs.opexRatioPct}
                    onChange={(v) => set('opexRatioPct', v)}
                    {...field('opexRatioPct')}
                  />
                </div>
                <div className="col-span-2 text-[11px] text-slate-400">
                  Implied NOI margin: {formatPct(results.effectiveNoiMarginPct)}
                </div>
              </div>
            )}
          </div>

          <FieldRow label="Exit Cap Rate">
            <FormattedNumberInput
              format="percent"
              value={inputs.exitCapRatePct}
              onChange={(v) => set('exitCapRatePct', v)}
              {...field('exitCapRatePct')}
            />
          </FieldRow>

          <FieldRow label="Loan-to-Cost (0 = all-equity)">
            <FormattedNumberInput
              format="percent"
              value={inputs.ltcPct}
              onChange={(v) => set('ltcPct', v)}
              {...field('ltcPct')}
            />
          </FieldRow>

          <FieldRow label="Construction Loan Rate (interest-only approx.)">
            <FormattedNumberInput
              format="percent"
              value={inputs.constructionInterestRatePct}
              onChange={(v) => set('constructionInterestRatePct', v)}
              {...field('constructionInterestRatePct')}
            />
          </FieldRow>
        </div>

        <div className="space-y-4">
          <div className={`rounded-md border p-3 text-sm ${FEASIBILITY_COLOR[results.feasibility]}`}>
            <div className="font-semibold capitalize">{results.feasibility}</div>
            <div className="mt-0.5 text-xs">{FEASIBILITY_LABEL[results.feasibility]}</div>
            {solveFor && (
              <ul className="mt-2 space-y-0.5 border-t border-current/20 pt-2 text-xs">
                <li>What it would take to reach Marginal ({FEASIBILITY_TIER_THRESHOLDS_BPS.marginal}+ bps):</li>
                {solveFor.requiredRent !== null && (
                  <li>&bull; Rent {formatMoney(solveFor.requiredRent)}{rentUnitLabel}</li>
                )}
                {solveFor.requiredHardCostPerUnit !== null && (
                  <li>
                    &bull; Hard costs &le; {formatMoneyCompact(solveFor.requiredHardCostPerUnit)}
                    {unitLabel}
                  </li>
                )}
                {solveFor.requiredExitCapRatePct !== null && (
                  <li>&bull; Exit cap &le; {formatPct(solveFor.requiredExitCapRatePct)}</li>
                )}
              </ul>
            )}
          </div>

          <div className="rounded-md border border-slate-200 bg-white p-4">
            <div className="text-xs font-semibold tracking-wide text-slate-500">DEVELOPMENT COST</div>
            <dl className="mt-2 space-y-1 text-sm">
              <Row label="Hard Costs" value={formatMoney(results.hardCosts)} />
              <Row label="Soft Costs" value={formatMoney(results.softCosts)} />
              <Row label="Contingency" value={formatMoney(results.contingency)} />
              <Row label="Land Cost" value={formatMoney(inputs.landCost)} />
              <Row label="Total Development Cost" value={formatMoney(results.totalDevelopmentCost)} strong />
            </dl>
          </div>

          <div className="rounded-md border border-slate-200 bg-white p-4">
            <div className="text-xs font-semibold tracking-wide text-slate-500">STABILIZED VALUE</div>
            <dl className="mt-2 space-y-1 text-sm">
              <Row label="Gross Potential Rent" value={formatMoney(results.grossPotentialRent)} />
              <Row
                label="Operating Expenses"
                value={`${formatMoney(results.operatingExpenses)} (${formatMoney(results.opexPerUnit)}${unitLabel})`}
              />
              <Row
                label="Stabilized NOI"
                value={`${formatMoney(results.stabilizedNoi)} (${formatMoney(results.noiPerUnit)}${unitLabel})`}
              />
              <Row label="Stabilized Value (NOI / exit cap)" value={formatMoney(results.stabilizedValue)} strong />
            </dl>
          </div>

          <div className="rounded-md border border-slate-200 bg-white p-4">
            <div className="text-xs font-semibold tracking-wide text-slate-500">FEASIBILITY</div>
            <dl className="mt-2 space-y-1 text-sm">
              <Row label="Profit" value={formatMoney(results.profit)} />
              <Row label="Profit Margin" value={formatPct(results.profitMarginPct)} />
              <Row label="Yield on Cost" value={formatPct(results.yieldOnCost)} />
              <Row label="Spread over Exit Cap" value={`${results.capRateSpreadBps.toFixed(0)} bps`} strong />
            </dl>
          </div>

          {inputs.ltcPct > 0 && (
            <div className="rounded-md border border-slate-200 bg-white p-4">
              <div className="text-xs font-semibold tracking-wide text-slate-500">
                SIMPLE LEVERAGE (stabilized year, interest-only approximation)
              </div>
              <dl className="mt-2 space-y-1 text-sm">
                <Row label="Loan Amount" value={formatMoney(results.loanAmount)} />
                <Row label="Equity Required" value={formatMoney(results.equityRequired)} />
                <Row label="Levered Cash Flow" value={formatMoney(results.leveredCashFlow)} />
                <Row
                  label="Cash-on-Cash"
                  value={results.cashOnCashPct === null ? '—' : formatPct(results.cashOnCashPct)}
                  strong
                />
              </dl>
            </div>
          )}

          <QuickScreenSensitivityGrid inputs={inputs} />

          <div className="flex gap-2">
            <button
              onClick={onSendToDealInputs}
              className="flex-1 rounded bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-700"
            >
              Send to Deal Inputs →
            </button>
            <button
              onClick={onSaveAsScenario}
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              Save as Scenario →
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function FieldRow({
  label,
  children,
  hint,
}: {
  label: string
  children: React.ReactNode
  hint?: string
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600">{label}</label>
      <div className="mt-1 max-w-xs">{children}</div>
      {hint && <div className="mt-0.5 max-w-xs text-[11px] text-slate-400">{hint}</div>}
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
