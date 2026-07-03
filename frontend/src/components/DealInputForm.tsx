import { Fragment, useEffect, useState } from 'react'
import FieldRow from './fields/FieldRow'
import MarketContextPanel from './MarketContextPanel'
import { fetchMarketRates, type MarketRates } from '../lib/api'
import { isVisible } from '../lib/visibility'
import type { InputSchema } from '../types/schema'

interface DealInputFormProps {
  schema: InputSchema
  values: Record<string, unknown>
  onFieldChange: (fieldId: string, value: unknown) => void
}

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

  return (
    <div className="max-w-3xl space-y-4 pb-16">
      <MarketContextPanel
        market={typeof values.market === 'string' ? values.market : ''}
        submarket={typeof values.submarket === 'string' ? values.submarket : ''}
        assetClass={typeof values.propertyType === 'string' ? values.propertyType : ''}
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
                  />
                  {field.id === 'interestRate' && <RatesHint />}
                </Fragment>
              ))}
          </div>
        </details>
      ))}
    </div>
  )
}
