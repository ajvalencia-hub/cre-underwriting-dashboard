# Chart kit

Hand-rolled, accessible SVG charts. No chart library, no new dependencies.
Import from `components/charts` (the folder's `index.ts`). Pure math lives in
`src/lib/chartScale.ts` (scales, nice ticks, quantiles) and
`src/lib/chartLayout.ts` (bar slots, stacking, rounded bar paths, hit tests,
tooltip placement, dodge). Both are unit-tested. Colors come from the
`--viz-*` tokens in `src/index.css`.

## Choose the form first

| The data is… | Use |
|---|---|
| One current value (± delta) / a few headline numbers | `StatTile` / `StatTileRow`. Not a one-bar chart. |
| A trend over time (hold years, months) | `LineChart` (add `area` for a single series) |
| Magnitudes across categories | `BarChart` (use `horizontal` for long or many names) |
| Values above/below zero (cash flow, variance) | `BarChart` with `diverging` (one series) |
| Part-to-whole across categories | `BarChart mode="stacked"` |
| One category is the point, the rest are context | `BarChart highlight="…"` (emphasis) |
| Two measures per item (cap rate vs $/SF) | `ScatterChart` (≤3 series) |
| A distribution of a few dozen values (comps, Monte Carlo) | `StripPlot` / `DotPlot` |
| More than ~7 classes that all matter | a table, not more colors |

Hard rules:
- **One y-axis.** Two measures in different units get two charts, never a dual axis.
- **Color follows the entity.** Pass `slot` (1–8) so a series keeps its color when
  others are filtered out. The kit never cycles or makes up a 9th hue. Caps: Line
  4, Bar 8, Scatter 3 (all-pairs validated). Past a cap, fold into "Other" or facet.
- **Status colors are not series colors.** `--viz-status-*` are only for good,
  warning or critical states, always shown with an icon and a label.
- **Text never uses a series color.** Labels use the text tokens (the kit
  handles this).
- **Label sparingly.** `showValues` is for a few bars (≤ ~12). The tooltip and
  the table carry the rest.
- **Numbers come from the app's formatters.** Pass `format` (tooltip and table)
  and optionally `tickFormat` (axis), e.g. `formatMoney` and `formatMoneyCompact`
  from `lib/money`. Negative money is `-$1,234`. Axis steps are 1/2/5 × 10^k, so
  a compact formatter is safe.
- **Put charts on the card surface** (`bg-white`, dark `#1e293b`). Surface gaps
  and marker rings use `--viz-surface`.

## What every chart does (don't re-implement)

- `ChartFrame`: title, subtitle, legend (only for 2+ series), a **Show table**
  toggle that renders an accessible `<table>` of the same data, and a quiet
  empty state for empty, all-NaN or too-little data.
- The SVG has `role="img"` and an `aria-label` that summarizes the data (range,
  highs and lows, medians). Override it with `ariaLabel`.
- The plot is one tab stop. Arrow keys, Home and End move through the points or
  marks. Escape clears. The tooltip shows on keyboard focus just as it does on
  hover, and keyboard moves are announced through an `aria-live` region.
- Hover: line charts use a crosshair that snaps to the nearest x and lists every
  series. Bars and dots get a per-mark tooltip. Hit areas are larger than the
  marks (the whole band, or the nearest dot within 24–32px).
- The tooltip stays inside the chart's own box (flips, then clamps), so a
  scrolling card never clips it.
- Width is responsive (a ResizeObserver plus a `viewBox`, `width="100%"`).
  Height is fixed per chart and includes the axis band.
- Marks: bars ≤24px thick with a 4px rounded data end and a square end at the
  zero baseline. Negative bars hang below zero. Adjacent and stacked fills are
  separated by a 2px surface gap. Lines are 2px. Markers are 8px with a 2px
  surface ring. Gridlines are solid 1px hairlines. Reference lines are dashed
  (dashing means a threshold).

## APIs

```ts
type Formatter = (v: number) => string
type SeriesSlot = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8
interface ReferenceLine { value: number; label: string }
```

### LineChart
| prop | type | notes |
|---|---|---|
| `title` | string | required |
| `subtitle?` | string | |
| `x` | (string\|number)[] | ordered, evenly spaced |
| `series` | `{ key, label, values: (number\|null)[], slot? }[]` | 1–4. null/NaN is a gap: the line lifts and never bridges it. A lone point gets a marker. |
| `format` | Formatter | tooltip/table |
| `tickFormat?` | Formatter | y-axis |
| `xFormat?` | (x) => string | |
| `xLabel?` | string | table header (default "Period") |
| `referenceLine?` | ReferenceLine | e.g. `{ value: 1.25, label: '1.25x DSCR' }` |
| `area?` | boolean | 10% wash, single series only (forces 0 into the domain) |
| `includeZero?` | boolean | |
| `height?` | number | default 220 |
| `emptyMessage?`, `ariaLabel?`, `className?` | | |

Empty state when there are fewer than 2 x values or fewer than 2 finite values.

### BarChart
| prop | type | notes |
|---|---|---|
| `title`, `subtitle?` | | |
| `categories` | string[] | |
| `series` | `{ key, label, values, slot? }[]` | ≤8; null = no bar |
| `format`, `tickFormat?` | Formatter | |
| `orientation?` | `'vertical'` \| `'horizontal'` | default vertical |
| `mode?` | `'grouped'` \| `'stacked'` | stacking keeps positives and negatives separate |
| `showValues?` | boolean | tip labels (not for stacked). A label is dropped if it doesn't fit, and its value is still in the tooltip and table. |
| `diverging?` | boolean | one series: negative bars use `--viz-div-neg`, positive use `--viz-div-pos` |
| `highlight?` | string | one series: this category gets the slot color, the rest are de-emphasized |
| `referenceLine?` | ReferenceLine | |
| `categoryLabel?` | string | table header |
| `height?` | number | vertical default 240; horizontal default rows × 32 + 32 |

Empty state when there are no categories or no finite values.

### ScatterChart
`series: { key, label, points: { x, y, label? }[], slot? }[]` (≤3), `xLabel`,
`yLabel`, `xFormat`, `yFormat`, `xTickFormat?`, `yTickFormat?`,
`referenceX?` / `referenceY?` (quadrant lines), `includeZeroX?`,
`includeZeroY?`, `height?` (default 280). Points with a non-finite x or y are
dropped. Empty state when no points remain.

### StripPlot (alias DotPlot)
`rows: { key, label, values: (number | { value, label? } | null)[], slot? }[]`,
`format`, `tickFormat?`, `showMedian?` (default true: a 2px ink tick),
`referenceLine?` (subject deal or hurdle, shown on every row), `valueLabel?`,
`rowHeight?` (default 48). Dots are dodged so they don't overlap. Empty state
when no values are finite.

### StatTile / StatTileRow
`StatTile { label, value: string (pre-formatted), delta?: { text, direction:
'up'|'down'|'flat', sentiment?: 'good'|'bad'|'neutral' }, hint?, hero? }`.
Set `sentiment` for the deal: vacancy going **up** is `bad`. The delta shows an
arrow icon plus text, and its color is never the only signal. Use `hero` (48px)
once per view. `StatTileRow { tiles, className? }` is an auto-fit grid.

### Building blocks
`ChartFrame` (a render prop that receives the measured width), `DataTable`,
`Legend` (`{ key, label, slot?|color?, shape: 'line'|'rect'|'dot' }[]`),
`Tooltip`, `seriesColor(slot)`, `slotFor(i, slot?)`, `VIZ` (token vars).

## Tokens (`src/index.css`, `:root` + `.dark`)

`--viz-surface`, `--viz-series-1..8`, `--viz-deemphasis`,
`--viz-text-primary|secondary|muted`, `--viz-grid`, `--viz-axis`,
`--viz-seq-100..700` (every 50; 100 = least, and the scale flips in dark so low
values recede into the surface; for ordinal use start at 250),
`--viz-div-neg|mid|pos`, `--viz-status-good|warning|serious|critical`,
`--viz-delta-good|bad` (text-safe). Utility classes: `.fill-viz-primary|secondary|muted`,
`.stroke-viz-grid|axis`, `.text-viz-primary|secondary|muted`, `.viz-tabular`,
`.viz-tooltip`. Never hard-code hex in a chart. If you add a palette, run the
dataviz skill's `validate_palette.js` against `#ffffff` (light) and `#1e293b`
(dark).
