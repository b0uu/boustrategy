import { useEffect, useRef, useState } from 'react'
import { Empty, ResourceNotice, SectionBoundary } from './common'
import type { Resource } from './api'
import { amount, label, money, numeric, percent, sessionDay, tone, weight, when } from './format'
import { dashboardUrl, navigate } from './navigation'
import type { ChartPoint, Overview, Performance as PerformanceData, Range, Scope } from './types'

const RANGES = ['1M', '3M', 'YTD', 'All'] as const
const BENCHMARK_NAMES: Record<string, string> = { SPY: 'S&P 500', QQQ: 'QQQ' }
// A reader's preference, not shared state: percent unless they chose dollars on this browser.
const RETURN_UNIT = 'boustrategy-return-unit'
type ReturnUnit = 'percent' | 'dollars'

function savedUnit(): ReturnUnit {
  try {
    return localStorage.getItem(RETURN_UNIT) === 'dollars' ? 'dollars' : 'percent'
  } catch {
    return 'percent' // Site data is blocked; the reader gets the default each visit.
  }
}
const WIDTH = 600
const HEIGHT = 108
const INSET = 6

export function PortfolioChart({ points }: { points: ChartPoint[] }) {
  const frame = useRef<SVGSVGElement | null>(null)
  const [active, setActive] = useState<number | null>(null)
  // Draw at the element's own width so one unit is one pixel. A fixed canvas stretched to fit
  // squeezes the shape horizontally on a phone. A measurement of 0 (jsdom, display:none) keeps
  // the default rather than collapsing the chart.
  const [width, setWidth] = useState(WIDTH)
  useEffect(() => {
    const node = frame.current
    if (!node || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(entries => {
      const measured = Math.round(entries[0].contentRect.width)
      if (measured > 0) setWidth(measured)
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  const valid = points.filter(point => numeric(point.equity) !== null && point.quality === 'complete')
  if (!valid.length) return <Empty>Portfolio history isn't available for this range.</Empty>
  // The history holds one valuation per session, so each point gets an equal step: spaced by clock
  // time, nights and weekends would stretch the line between readings that were never taken.
  const step = points.length > 1 ? (width - INSET * 2) / (points.length - 1) : 0
  const position = new Map(points.map((point, index) => [point, points.length > 1 ? INSET + index * step : width / 2]))
  const x = (point: ChartPoint) => position.get(point)!
  const values = valid.map(point => numeric(point.equity)!)
  const low = Math.min(...values), high = Math.max(...values)
  const single = valid.length === 1
  const yValue = (value: number) => (high === low ? 54 : 96 - (value - low) / (high - low) * 84)
  const y = (point: ChartPoint) => yValue(numeric(point.equity)!)
  const segments: ChartPoint[][] = []
  let segment: ChartPoint[] = []
  for (const point of points) {
    if (numeric(point.equity) === null || point.quality !== 'complete') {
      if (segment.length) segments.push(segment)
      segment = []
    } else segment.push(point)
  }
  if (segment.length) segments.push(segment)
  // Inspection snaps to the nearest recorded valuation; nothing between two readings is shown.
  const selected = active === null ? null : valid.reduce((nearest, point) => Math.abs(x(point) - active) < Math.abs(x(nearest) - active) ? point : nearest)
  const selectedLabel = selected && (selected.phase === 'session_close' && selected.session_date ? `${sessionDay(selected.session_date)} close` : when(selected.at))
  const track = (clientX: number) => {
    const rect = frame.current?.getBoundingClientRect()
    if (!rect || !rect.width) return
    setActive(Math.min(width, Math.max(0, (clientX - rect.left) / rect.width * width)))
  }
  const move = (direction: number) => setActive(current => {
    const index = current === null ? (direction < 0 ? valid.length : -1) : valid.findIndex(point => x(point) === current)
    return x(valid[Math.min(valid.length - 1, Math.max(0, index + direction))])
  })
  return <figure className="chart-figure">
    <svg ref={frame} className="portfolio-chart" viewBox={`0 0 ${width} ${HEIGHT}`} preserveAspectRatio="none" role="img"
      aria-label={`Portfolio value, ${valid.length} complete observation${valid.length === 1 ? '' : 's'}. ${money(values[0])} to ${money(values[values.length - 1])}. Incomplete observations are gaps.`}
      tabIndex={0}
      onKeyDown={event => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); move(event.key === 'ArrowLeft' ? -1 : 1) }
        if (event.key === 'Home' || event.key === 'End') { event.preventDefault(); setActive(x(event.key === 'Home' ? valid[0] : valid[valid.length - 1])) }
        if (event.key === 'Escape') setActive(null)
      }}
      onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); track(event.clientX) }}
      onPointerMove={event => track(event.clientX)} onPointerUp={event => event.currentTarget.releasePointerCapture(event.pointerId)} onPointerLeave={() => setActive(null)}>
      {/* A flat reference line keeps a single observation legible as a value rather than a stray dot. */}
      {single && <line className="chart-baseline" x1="0" x2={width} y1={y(valid[0])} y2={y(valid[0])} />}
      {segments.map((part, index) => part.length === 1
        ? <circle key={index} className="chart-point" cx={x(part[0])} cy={y(part[0])} r="3" />
        : <g key={index}>{high !== low && <polygon points={`${x(part[0])},${HEIGHT} ${part.map(point => `${x(point)},${y(point)}`).join(' ')} ${x(part[part.length - 1])},${HEIGHT}`} />}<polyline points={part.map(point => `${x(point)},${y(point)}`).join(' ')} /></g>)}
      {selected && <g><line className="chart-cursor" x1={x(selected)} x2={x(selected)} y1="0" y2={HEIGHT} /><circle className="chart-point is-active" cx={x(selected)} cy={y(selected)} r="3.5" /></g>}
    </svg>
    {selected && <div className={`chart-tooltip${x(selected) < 72 ? ' is-start' : x(selected) > width - 72 ? ' is-end' : ''}`} style={{ left: `${x(selected) / width * 100}%` }}>
      <span><strong className="mono">{money(selected.equity)}</strong>{numeric(selected.return_percent) != null && <span className={`mono ${tone(selected.return_percent)}`}>{percent(selected.return_percent)}</span>}</span>
      <time dateTime={selected.at}>{selectedLabel}</time>
    </div>}
    {/* A flat range would print the value already shown in the metrics, so label only a real span. */}
    {high !== low && <div className="chart-scale" aria-hidden="true"><span>{money(high, true)}</span><span>{money(low, true)}</span></div>}
    <figcaption className="chart-readout" aria-live="polite">
      {/* Idle state names the record rather than repeating the value already in the metrics. */}
      {selected
        ? <><span className="mono">{money(selected.equity)}</span><span className="quiet">{selectedLabel}</span></>
        : <span className="quiet">{single ? 'One recorded valuation' : `${valid.length} recorded valuations, one per session · point, touch or use arrow keys to inspect`}</span>}
    </figcaption>
  </figure>
}

export function Performance({ overview, performance, range, scope, search, open }: { overview: Resource<Overview>; performance: Resource<PerformanceData>; range: Range; scope: Scope; search: string; open: boolean; onToggle: () => void }) {
  const data = overview.data
  const result = performance.data
  const allocation = data?.allocation ?? []
  const barAvailable = allocation.length > 0 && allocation.every(item => item.weight !== null && item.weight >= 0 && item.weight <= 1) && Math.abs(allocation.reduce((sum, item) => sum + (item.weight ?? 0), 0) - 1) < .001
  const single = result?.reason === 'single_observation'
  const [unit, setUnit] = useState<ReturnUnit>(savedUnit)
  useEffect(() => {
    try {
      localStorage.setItem(RETURN_UNIT, unit)
    } catch { /* nothing to remember the choice with */ }
  }, [unit])
  const shown = unit === 'percent' ? result?.return_percent : result?.investment_pnl
  const comparison = data?.benchmark_comparison
  const compared = comparison?.status === 'available' ? comparison.benchmarks.filter(item => item.status === 'available') : []
  const agentReturn = numeric(comparison?.return_percent)
  const compare = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (compare.current?.open && !compare.current.contains(event.target as Node)) compare.current.removeAttribute('open')
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [])
  return <section className={`performance${performance.stale || overview.stale ? ' is-updating' : ''}`} aria-label="Live portfolio">
    <ResourceNotice resource={overview} name="portfolio overview" />
    <div className="metrics">
      <div><strong title={money(data?.equity)}>{money(data?.equity, true)}</strong><span>Portfolio value</span></div>
      {/* A missing return is shown as missing: a zero would claim the account broke even. */}
      <div className="return-metric"><strong className={tone(shown)} title={shown == null && result?.reason ? label(result.reason) : undefined}>{shown == null ? '—' : unit === 'percent' ? percent(shown) : `${(numeric(shown) ?? 0) >= .005 ? '+' : ''}${money(shown)}`}</strong><span className="metric-label">Return{single ? ' · since first record' : ''}<span className="unit-toggle" role="group" aria-label="Show return as"><button type="button" aria-label="Percent" aria-pressed={unit === 'percent'} onClick={() => setUnit('percent')}>%</button><button type="button" aria-label="Dollars" aria-pressed={unit === 'dollars'} onClick={() => setUnit('dollars')}>$</button></span>{comparison && agentReturn !== null && compared.length > 0 && <details className="benchmark-compare" ref={compare}><summary aria-label="Compare the return with the S&P 500 and QQQ">Compare</summary><div className="benchmark-panel">
        <p>Since the first trade, {sessionDay(comparison.start_session_date)}</p>
        <dl>
          <div className="is-agent"><dt>BouStrategy</dt><dd className={`mono ${tone(agentReturn)}`}>{percent(agentReturn)}</dd></div>
          {compared.map(item => <div key={item.ticker}><dt>{BENCHMARK_NAMES[item.ticker] ?? item.ticker}</dt><dd className={`mono ${tone(item.return_percent)}`}>{percent(item.return_percent)}</dd></div>)}
        </dl>
        <p>As of {when(comparison.end_at)}</p>
      </div></details>}</span></div>
      <div><strong>{data ? data.decisions_today.toLocaleString() : 'Unavailable'}</strong><span>{data?.decisions_today === 1 ? 'Decision today' : 'Decisions today'}</span></div>
    </div>
    <div className="portfolio-details" id="portfolio-details" hidden={!open}>
      <ResourceNotice resource={performance} name="performance history" />
      <SectionBoundary resetKey={result} retry={performance.refresh} name="performance">
        {result && <>
          <div className="chart-title"><span>Portfolio value, <span className="range-label">{range === '1M' ? '30 days' : range}</span></span>
            <span className="chart-title-tools"><span className="range-controls" aria-label="Performance range">{RANGES.map(value => <button key={value} aria-pressed={value === range} onClick={() => navigate(dashboardUrl({ range: value }, search))}>{value}</button>)}</span>{data?.daily_pnl?.amount != null && <span className={`change ${tone(data.daily_pnl.amount)}`}>{money(data.daily_pnl.amount)} today</span>}</span>
          </div>
          <PortfolioChart points={result.history} />
          <div className="chart-caption"><span>{result.start_at ? when(result.start_at, true) : 'Start unavailable'}</span><span>{result.end_at ? when(result.end_at, true) : 'End unavailable'}</span></div>
          {result.status !== 'available' && <p className="section-note performance-caveat">Return unavailable: {label(result.reason)}. Missing facts aren't treated as zero.</p>}
        </>}
      </SectionBoundary>
      {data?.daily_pnl && data.daily_pnl.amount == null && <p className="daily-change performance-caveat">Investment change unavailable · {label(data.daily_pnl.reason)}</p>}
      <div className="allocation-group"><span className="quiet">Recorded allocation</span>
        {barAvailable && <div className="allocation-bar" role="img" aria-label={allocation.map(item => `${label(item.asset_class)} ${weight(item.weight)}`).join(', ')}>{allocation.map((item, index) => <span key={item.asset_class} className={`allocation-color-${index % 4}`} style={{ width: `${(item.weight ?? 0) * 100}%` }} />)}</div>}
        {allocation.length ? <div className="allocation-legend">{allocation.map((item, index) => <span key={item.asset_class}><i className={`allocation-color-${index % 4}`} />{label(item.asset_class)} <span className="mono" title={money(item.market_value)}>{weight(item.weight)}</span></span>)}</div> : <Empty>Allocation needs complete cash and holdings data.</Empty>}
      </div>
    </div>
    {!open && data && <p className="sr-only">{amount(data.equity)} US dollars. Portfolio details collapsed. Scope {scope}.</p>}
  </section>
}
