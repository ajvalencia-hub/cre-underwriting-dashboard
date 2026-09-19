import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { BarChart, LineChart, ScatterChart, StatTile, StatTileRow, StripPlot } from './index'

// Server-render smoke tests (vitest runs in node): every chart renders its
// frame, an accessible SVG summary, the table toggle, and a quiet empty state
// for empty / NaN-only / single-point data — and never prints "NaN".

const pct = (v: number) => `${(v * 100).toFixed(1)}%`
const money = (v: number) => `${v < 0 ? '-' : ''}$${Math.abs(Math.round(v)).toLocaleString()}`

function expectClean(html: string) {
  expect(html).not.toMatch(/NaN|Infinity|undefined/)
}

describe('LineChart', () => {
  it('renders series, an aria summary, legend and reference line', () => {
    const html = renderToStaticMarkup(
      <LineChart
        title="IRR by hold year"
        x={[1, 2, 3, 4, 5]}
        xFormat={(y) => `Y${y}`}
        series={[
          { key: 'lev', label: 'Levered IRR', values: [0.08, 0.11, 0.14, null, 0.15] },
          { key: 'unlev', label: 'Unlevered IRR', values: [0.06, 0.07, 0.08, 0.085, 0.09] },
        ]}
        format={pct}
        referenceLine={{ value: 0.12, label: '12% hurdle' }}
      />,
    )
    expectClean(html)
    expect(html).toContain('role="img"')
    expect(html).toMatch(/aria-label="IRR by hold year\. Line chart, Y1 to Y5\. Levered IRR: 8\.0% to 15\.0%/)
    expect(html).toContain('12% hurdle')
    expect(html).toContain('Show table')
    expect(html).toContain('var(--viz-series-2)')
    expect(html).toContain('stroke-dasharray="4 3"')
  })
  it('shows the empty state for no / NaN-only / single-point data', () => {
    for (const values of [[], [NaN, NaN], [0.1]]) {
      const html = renderToStaticMarkup(
        <LineChart title="T" x={values.map((_, i) => i)} series={[{ key: 'a', label: 'A', values }]} format={pct} />,
      )
      expect(html).toContain('Not enough points')
      expect(html).not.toContain('<svg')
    }
  })
  it('draws the area wash only for a single series', () => {
    const html = renderToStaticMarkup(
      <LineChart title="NOI" x={[1, 2, 3]} series={[{ key: 'noi', label: 'NOI', values: [1, 2, 3] }]} format={money} area />,
    )
    expect(html).toContain('fill-opacity="0.1"')
    expect(html).not.toContain('<ul') // single series: no legend
  })
})

describe('BarChart', () => {
  const categories = ['Y0', 'Y1', 'Y2', 'Y3']
  it('renders negatives below the zero baseline with rounded data ends', () => {
    const html = renderToStaticMarkup(
      <BarChart title="Cash flow" categories={categories} series={[{ key: 'cf', label: 'CF', values: [-1000, 200, 250, 1400] }]} format={money} diverging showValues />,
    )
    expectClean(html)
    expect(html).toContain('var(--viz-div-neg)')
    expect(html).toContain('var(--viz-div-pos)')
    expect(html).toMatch(/A4,4 0 0 1/)
    expect(html).toContain('-$1,000')
  })
  it('stacks and groups multiple series with a legend', () => {
    for (const mode of ['grouped', 'stacked'] as const) {
      const html = renderToStaticMarkup(
        <BarChart
          title="Sources"
          categories={categories}
          mode={mode}
          orientation={mode === 'stacked' ? 'horizontal' : 'vertical'}
          series={[
            { key: 'a', label: 'Debt', values: [5, 6, null, 8] },
            { key: 'b', label: 'Equity', values: [2, -1, 3, NaN] },
          ]}
          format={money}
        />,
      )
      expectClean(html)
      expect(html).toContain('Debt')
      expect(html).toContain('var(--viz-series-2)')
    }
  })
  it('shows the empty state for no categories or all-null values', () => {
    expect(renderToStaticMarkup(<BarChart title="T" categories={[]} series={[]} format={money} />)).toContain('No values')
    expect(
      renderToStaticMarkup(<BarChart title="T" categories={['a']} series={[{ key: 'a', label: 'A', values: [NaN] }]} format={money} />),
    ).toContain('No values')
  })
  it('renders a single bar without NaN', () => {
    const html = renderToStaticMarkup(<BarChart title="T" categories={['a']} series={[{ key: 'a', label: 'A', values: [3] }]} format={money} />)
    expectClean(html)
    expect(html).toContain('<path')
  })
})

describe('ScatterChart', () => {
  it('renders ringed markers, reference lines and caps at 3 series', () => {
    const html = renderToStaticMarkup(
      <ScatterChart
        title="Cap rate vs price/SF"
        xLabel="Price / SF"
        yLabel="Cap rate"
        xFormat={money}
        yFormat={pct}
        referenceY={{ value: 0.06, label: 'Subject 6.0%' }}
        series={[
          { key: 'a', label: 'A', points: [{ x: 200, y: 0.055, label: 'Comp 1' }, { x: 260, y: 0.061 }] },
          { key: 'b', label: 'B', points: [{ x: NaN, y: 0.05 }, { x: 300, y: 0.07 }] },
          { key: 'c', label: 'C', points: [{ x: 310, y: 0.065 }] },
          { key: 'd', label: 'D', points: [{ x: 320, y: 0.066 }] },
        ]}
      />,
    )
    expectClean(html)
    expect(html).toContain('Subject 6.0%')
    expect(html).toContain('stroke:var(--viz-surface)')
    expect(html).not.toContain('var(--viz-series-4)')
    expect(html).toMatch(/Scatter plot of 4 points in 3 series/)
  })
  it('renders a single point and an empty state', () => {
    const one = renderToStaticMarkup(
      <ScatterChart title="T" xLabel="x" yLabel="y" xFormat={String} yFormat={String} series={[{ key: 'a', label: 'A', points: [{ x: 1, y: 1 }] }]} />,
    )
    expectClean(one)
    expect(one).toContain('<circle')
    const none = renderToStaticMarkup(
      <ScatterChart title="T" xLabel="x" yLabel="y" xFormat={String} yFormat={String} series={[{ key: 'a', label: 'A', points: [] }]} />,
    )
    expect(none).toContain('No points')
  })
})

describe('StripPlot', () => {
  it('renders dots with medians and a subject marker', () => {
    const html = renderToStaticMarkup(
      <StripPlot
        title="Comp cap rates"
        rows={[
          { key: 'mf', label: 'Multifamily', values: [0.05, 0.052, 0.052, { value: 0.06, label: 'Comp 4' }, null] },
          { key: 'ind', label: 'Industrial', values: [0.045, 0.047, NaN] },
        ]}
        format={pct}
        referenceLine={{ value: 0.055, label: 'Subject' }}
      />,
    )
    expectClean(html)
    expect(html).toMatch(/Multifamily: 4 values, 5\.0% to 6\.0%, median 5\.2%/)
    expect(html).toContain('Subject')
    expect(html).toContain('Median')
  })
  it('shows the empty state when nothing is finite', () => {
    const html = renderToStaticMarkup(<StripPlot title="T" rows={[{ key: 'a', label: 'A', values: [NaN, null] }]} format={pct} />)
    expect(html).toContain('No values')
  })
})

describe('StatTile', () => {
  it('pairs delta color with an icon and text', () => {
    const html = renderToStaticMarkup(
      <StatTileRow
        tiles={[
          { label: 'Levered IRR', value: '14.8%', delta: { text: '+1.2 pts vs base', direction: 'up', sentiment: 'good' } },
          { label: 'LTV', value: '65%', delta: { text: '+5 pts', direction: 'up', sentiment: 'bad' } },
        ]}
      />,
    )
    expect(html).toContain('var(--viz-delta-good)')
    expect(html).toContain('var(--viz-delta-bad)')
    expect(html).toContain('▲')
    expect(html).toContain('>up<')
  })
  it('renders a hero figure', () => {
    expect(renderToStaticMarkup(<StatTile label="Equity multiple" value="2.1x" hero />)).toContain('text-5xl')
  })
})
