import { Fragment, useEffect, useMemo, useState } from 'react'
import FieldRow, { type FieldIndicator } from './fields/FieldRow'
import MarketContextPanel from './MarketContextPanel'
import PropertyTaxLookup from './PropertyTaxLookup'
import { fetchBenchmarks, fetchMarketRates, type BenchmarkResult, type MarketRates } from '../lib/api'
import { deriveBenchmarkSubject } from '../lib/benchmarkSubject'
import { isVisible } from '../lib/visibility'
import type { InputSchema } from '../types/schema'

interface DealInputFormProps {
  schema: InputSchema
  values: Record<string, unknown>
  onFieldChange: (fieldId: string, value: unknown) => void
}

const BENCHMARK_DEBOUNCE_MS = 1200

/** Current index rates rendered as context next to the financing rate input.
 *  Display only — never auto-fills anything. Renders nothing when FRED is
 *  unavailable (no key, offline). */
function RatesHint() {
  const [rates, setRates] = useState<MarketRates | null>(null)
  useEffect(() => {
    fetchMarketRates()
      .then(setRates)
      .catch(() => setRates(null))
  }, [])
  if (!rates || rates.dataSource !== 'fred') return null
  const parts = (
    [
      ['SOFR', rates.rates.sofr],
      ['5-yr UST', rates.rates.treasury5yrPct],
      ['10-yr UST', rates.rates.treasury10yrPct],
      ['30-yr mortgage', rates.rates.mortgage30yrPct],
    ] as const
  )
    .filter(([, v]) => typeof v === 'number')
    .map(([label, v]) => `${label} ${((v as number) * 100).toFixed(2)}%`)
  if (parts.length === 0) return null
  return (
    <div className="py-1.5 text-[11px] text-slate-400">
      Current index rates: {parts.join(' · ')} — context only, not applied.
    </div>
  )
}

export default function DealInputForm({ schema, values, onFieldChange }: DealInputFormProps) {
  const visibleSections = schema.sections.filter((s) => isVisible(s.visibleWhen, values))

  const [benchmarks, setBenchmarks] = useState<BenchmarkResult | null>(null)
  const [benchmarksLoading, setBenchmarksLoading] = useState(false)

  const address = typeof values.address === 'string' ? values.address : ''
  const market = typeof values.market === 'string' ? values.market : ''
  const submarket = typeof values.submarket === 'string' ? values.submarket : ''
  const assetClass = typeof values.propertyType === 'string' ? values.propertyType : ''
  const subject = useMemo(() => deriveBenchmarkSubject(values), [values])
  const subjectKey = JSON.stringify(subject)

  // Modeled annual RE taxes for the assessor-lookup caution note: detail tax
  // lines (annual_total only — other bases need engine context) or the flat
  // field. Display comparison only, never math.
  const modeledTaxes = useMemo(() => {
    const lines = Array.isArray(values.opexLineItems)
      ? (values.opexLineItems as Record<string, unknown>[])
      : []
    const detailTaxes = lines
      .filter(
        (l) =>
          l &&
          l.category === 'taxes' &&
          typeof l.amount === 'number' &&
          (l.basis === undefined || l.basis === null || l.basis === 'annual_total'),
      )
      .reduce((sum, l) => sum + (l.amount as number), 0)
    if (detailTaxes > 0) return detailTaxes
    return typeof values.realEstateTaxes === 'number' && values.realEstateTaxes > 0
      ? values.realEstateTaxes
      : null
  }, [values.opexLineItems, values.realEstateTaxes])

  useEffect(() => {
    if (!address.trim() && !market.trim()) {
      setBenchmarks(null)
      return
    }
    const handle = setTimeout(() => {
      setBenchmarksLoading(true)
      fetchBenchmarks({ address, market, submarket, assetClass, subject: { ...subject } })
        .then(setBenchmarks)
        .catch(() => setBenchmarks(null)) // offline/failed — panel just hides
        .finally(() => setBenchmarksLoading(false))
    }, BENCHMARK_DEBOUNCE_MS)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [address, market, submarket, assetClass, subjectKey])

  // Worst flag per input field, for the hover indicators next to the labels.
  const fieldIndicators = useMemo(() => {
    const map: Record<string, FieldIndicator> = {}
    for (const flag of benchmarks?.flags ?? []) {
      if (flag.verdict === 'ok') continue
      for (const fieldId of flag.relatedFieldIds) {
        const existing = map[fieldId]
        if (!existing || (existing.verdict === 'caution' && flag.verdict === 'warning')) {
          map[fieldId] = { verdict: flag.verdict, explanation: flag.explanation }
        }
      }
    }
    return map
  }, [benchmarks])

  return (
    <div className="max-w-3xl space-y-4 pb-16">
      <MarketContextPanel
        market={market}
        submarket={submarket}
        assetClass={assetClass}
        benchmarks={benchmarks}
        benchmarksLoading={benchmarksLoading}
      />

      {visibleSections.map((section) => (
        <details
          key={section.id}
          id={`section-${section.id}`}
          open
          className="rounded border border-slate-200 bg-white"
        >
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-semibold text-slate-700">
            {section.label}
          </summary>
          <div className="divide-y divide-slate-50 px-3 pb-2">
            {section.fields
              .filter((f) => isVisible(f.visibleWhen, values))
              .map((field) => (
                <Fragment key={field.id}>
                  <FieldRow
                    field={field}
                    value={values[field.id]}
                    onChange={(v) => onFieldChange(field.id, v)}
                    indicator={fieldIndicators[field.id]}
                  />
                  {field.id === 'interestRate' && <RatesHint />}
                  {field.id === 'useReassessedTaxes' && (
                    <PropertyTaxLookup
                      address={address}
                      purchasePrice={
                        typeof values.purchasePrice === 'number' ? values.purchasePrice : null
                      }
                      assessmentRatio={
                        typeof values.assessmentRatio === 'number' ? values.assessmentRatio : null
                      }
                      modeledTaxes={modeledTaxes}
                      onApplyMillage={(rate) => onFieldChange('millageRatePct', rate)}
                    />
                  )}
                </Fragment>
              ))}
          </div>
        </details>
      ))}
    </div>
  )
}
