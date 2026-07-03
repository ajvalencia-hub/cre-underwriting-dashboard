import { useState } from 'react'
import ScalarInput from '../components/fields/ScalarInput'
import QuickScreenSensitivityGrid from '../components/QuickScreenSensitivityGrid'
import { saveScenario } from '../lib/api'
import {
  FEASIBILITY_THRESHOLDS,
  QUICK_SCREEN_FIELD_CONFIG,
  QUICK_SCREEN_SF_PER_UNIT_ASSUMPTION,
  deriveOpexRatioFromMargin,
  solveExitCapForSpread,
  solveHardCostForSpread,
  solveRentForSpread,
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
  dealId: string | null
}

const FEASIBILITY_LABEL: Record<string, string> = {
  strong: `Strong — yield-on-cost clears exit cap by ${FEASIBILITY_THRESHOLDS.strong}+ bps`,
  marginal: `Marginal — clears exit cap by ${FEASIBILITY_THRESHOLDS.marginal}–${FEASIBILITY_THRESHOLDS.strong} bps`,
  weak: `Weak — within ${FEASIBILITY_THRESHOLDS.marginal} bps of exit cap (or below)`,
}
const FEASIBILITY_COLOR: Record<string, string> = {
  strong: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  marginal: 'border-amber-200 bg-amber-50 text-amber-700',
  weak: 'border-red-200 bg-red-50 text-red-700',
}

export default function QuickScreen({ inputs, onInputsChange, results, onSendToDealInputs, dealId }: QuickScreenProps) {
  const [scenarioName, setScenarioName] = useState('Quick Screen')
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)

  // QuickScreenInputs must stay fully numeric for computeQuickScreen to work —
  // unlike DealInputForm's optional fields, a blank field here would propagate
  // NaN through every downstream calculation. So unlike ScalarInput's general
  // contract (which allows clearing to undefined), silently ignore a non-finite
  // commit and keep showing the last-valid computed results.
  function set<K extends keyof QuickScreenInputs>(key: K, value: unknown) {
    if (key === 'sizeMode') {
      onInputsChange({ ...inputs, sizeMode: value as SizeMode })
      return
    }
    if (typeof value !== 'number' || !Number.isFinite(value)) return
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

  async function handleSaveAsScenario() {
    setSaving(true)
    setSaveMessage(null)
    try {
      await saveScenario({
        scenarioName: scenarioName.trim() || 'Quick Screen',
        kind: 'quickscreen',
        dealId,
        templateId: null,
        mappingProfileId: null,
        inputs: inputs as unknown as Record<string, unknown>,
      })
      setSaveMessage('Saved — see it under "5. Scenarios".')
    } catch (err) {
      setSaveMessage(err instanceof Error ? err.message : 'Could not save scenario')
    } finally {
      setSaving(false)
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

  const showSolveFor = results.feasibility === 'weak' || results.feasibility === 'marginal'
  const solvedRent = showSolveFor ? solveRentForSpread(inputs, FEASIBILITY_THRESHOLDS.marginal) : null
  const solvedHardCost = showSolveFor ? solveHardCostForSpread(inputs, FEASIBILITY_THRESHOLDS.marginal) : null
  const solvedExitCap = showSolveFor ? solveExitCapForSpread(inputs, FEASIBILITY_THRESHOLDS.marginal) : null
  const solveForParts = [
    solvedRent !== null ? `rent ≥ ${formatMoney(solvedRent)}${inputs.sizeMode === 'units' ? '/mo' : '/SF/yr'}` : null,
    solvedHardCost !== null ? `hard cost ≤ ${formatMoneyCompact(solvedHardCost)}/${inputs.sizeMode === 'units' ? 'unit' : 'SF'}` : null,
    solvedExitCap !== null ? `exit cap ≤ ${formatPct(solvedExitCap)}` : null,
  ].filter((p): p is string => p !== null)
  const unitLabel = inputs.sizeMode === 'units' ? '/unit' : '/SF'

  function applySensitivityCell(rentDeltaPct: number, exitCapDeltaBps: number) {
    onInputsChange({
      ...inputs,
      rent: inputs.rent * (1 + rentDeltaPct),
      exitCapRatePct: inputs.exitCapRatePct + exitCapDeltaBps / 10000,
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
            <ScalarInput
              type="number"
              value={inputs.quantity}
              onChange={(v) => set('quantity', v)}
              {...field('quantity')}
            />
          </FieldRow>

          <FieldRow label="Land Cost">
            <ScalarInput
              type="currency"
              value={inputs.landCost}
              onChange={(v) => set('landCost', v)}
              {...field('landCost')}
            />
          </FieldRow>

          <FieldRow
            label={inputs.sizeMode === 'units' ? 'Hard Cost per Unit' : 'Hard Cost per SF'}
            hint={sfPerUnitHint}
          >
            <ScalarInput
              type="currency"
              value={inputs.hardCostPerUnit}
              onChange={(v) => set('hardCostPerUnit', v)}
              {...field('hardCostPerUnit')}
            />
          </FieldRow>

          <FieldRow label="Soft Costs (% of hard cost)">
            <ScalarInput
              type="percent"
              value={inputs.softCostPct}
              onChange={(v) => set('softCostPct', v)}
              {...field('softCostPct')}
            />
          </FieldRow>

          <FieldRow label="Contingency (% of hard + soft)">
            <ScalarInput
              type="percent"
              value={inputs.contingencyPct}
              onChange={(v) => set('contingencyPct', v)}
              {...field('contingencyPct')}
            />
          </FieldRow>

          <FieldRow label={inputs.sizeMode === 'units' ? 'Monthly Rent per Unit' : 'Annual Rent per SF'}>
            <ScalarInput type="currency" value={inputs.rent} onChange={(v) => set('rent', v)} {...field('rent')} />
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
                <ScalarInput
                  type="percent"
                  value={inputs.noiMarginPct}
                  onChange={(v) => set('noiMarginPct', v)}
                  {...field('noiMarginPct')}
                />
              </div>
            ) : (
              <div className="mt-1 grid max-w-xs grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] text-slate-500">Vacancy %</label>
                  <ScalarInput
                    type="percent"
                    value={inputs.vacancyPct}
                    onChange={(v) => set('vacancyPct', v)}
                    {...field('vacancyPct')}
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-500">Opex (% of EGI)</label>
                  <ScalarInput
                    type="percent"
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
            <ScalarInput
              type="percent"
              value={inputs.exitCapRatePct}
              onChange={(v) => set('exitCapRatePct', v)}
              {...field('exitCapRatePct')}
            />
          </FieldRow>

          <FieldRow label="Loan-to-Cost (0 = all-equity)">
            <ScalarInput
              type="percent"
              value={inputs.ltcPct}
              onChange={(v) => set('ltcPct', v)}
              {...field('ltcPct')}
            />
          </FieldRow>

          <FieldRow label="Construction Loan Rate (interest-only approx.)">
            <ScalarInput
              type="percent"
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
            {solveForParts.length > 0 && (
              <div className="mt-2 border-t border-current/20 pt-2 text-xs">
                To reach Marginal ({FEASIBILITY_THRESHOLDS.marginal} bps): {solveForParts.join(' · or ')}
              </div>
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

          <QuickScreenSensitivityGrid inputs={inputs} onApplyCell={applySensitivityCell} />

          <button
            onClick={onSendToDealInputs}
            className="w-full rounded bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-700"
          >
            Send to Deal Inputs →
          </button>

          <div className="rounded-md border border-slate-200 bg-white p-4">
            <div className="text-xs font-semibold tracking-wide text-slate-500">SAVE AS SCENARIO</div>
            <div className="mt-2 flex gap-2">
              <input
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
                className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="Scenario name"
              />
              <button
                onClick={handleSaveAsScenario}
                disabled={saving || !scenarioName.trim()}
                className="rounded bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
            {saveMessage && <div className="mt-1.5 text-xs text-slate-500">{saveMessage}</div>}
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
