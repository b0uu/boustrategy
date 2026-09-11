import { useRef, useState } from 'react'
import { Chevron, Empty, Fact, ResourceNotice, SectionBoundary, AsOf } from './common'
import type { Resource } from './api'
import { amount, label, money, numeric, percent, tone, weight, when } from './format'
import { dashboardUrl, navigate } from './navigation'
import type { ChartPoint, Overview, Performance as PerformanceData, Range, Scope } from './types'

const RANGES = ['1M', '3M', 'YTD', 'All'] as const
const WIDTH = 600
const HEIGHT = 108

export function PortfolioChart({ points }: { points: ChartPoint[] }) {
  const frame = useRef<SVGSVGElement | null>(null)
  const [active, setActive] = useState<number | null>(null)
  const valid = points.filter(point => numeric(point.equity) !== null && point.quality === 'complete')
  if (!valid.length) return <Empty>Portfolio history isn't available for this range.</Empty>
  const times = points.map(point => Date.parse(point.at))
  const first = Math.min(...times), last = Math.max(...times)
  const values = valid.map(point => numeric(point.equity)!)
  const low = Math.min(...values), high = Math.max(...values)
  const single = valid.length === 1
  const x = (point: ChartPoint) => (last === first ? WIDTH / 2 : (Date.parse(point.at) - first) / (last - first) * WIDTH)
  const y = (point: ChartPoint) => (high === low ? 54 : 96 - (numeric(point.equity)! - low) / (high - low) * 84)
  const segments: ChartPoint[][] = []
  let segment: ChartPoint[] = []
  for (const point of points) {
    if (numeric(point.equity) === null || point.quality !== 'complete') {
      if (segment.length) segments.push(segment)
      segment = []
    } else segment.push(point)
  }
  if (segment.length) segments.push(segment)
  const hovered = active === null ? null : valid[active]
  const track = (clientX: number) => {
    const rect = frame.current?.getBoundingClientRect()
    if (!rect || !rect.width) return
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
    let nearest = 0
    for (let index = 1; index < valid.length; index += 1) {
      if (Math.abs(x(valid[index]) / WIDTH - ratio) < Math.abs(x(valid[nearest]) / WIDTH - ratio)) nearest = index
    }
    setActive(nearest)
  }
  return <figure className="chart-figure">
    <svg ref={frame} className="portfolio-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img"
      aria-label={`Portfolio value, ${valid.length} complete observation${valid.length === 1 ? '' : 's'}. ${money(values[0])} to ${money(values[values.length - 1])}. Incomplete observations are gaps.`}
      onPointerMove={event => track(event.clientX)} onPointerLeave={() => setActive(null)}>
      {/* A flat reference line keeps a single observation legible as a value rather than a stray dot. */}
      {single && <line className="chart-baseline" x1="0" x2={WIDTH} y1={y(valid[0])} y2={y(valid[0])} />}
      {segments.map((part, index) => part.length === 1
        ? <circle key={index} className="chart-point" cx={x(part[0])} cy={y(part[0])} r="3" />
        : <g key={index}><polygon points={`${x(part[0])},${HEIGHT} ${part.map(point => `${x(point)},${y(point)}`).join(' ')} ${x(part[part.length - 1])},${HEIGHT}`} /><polyline points={part.map(point => `${x(point)},${y(point)}`).join(' ')} /></g>)}
      {hovered && <g><line className="chart-cursor" x1={x(hovered)} x2={x(hovered)} y1="0" y2={HEIGHT} /><circle className="chart-point is-active" cx={x(hovered)} cy={y(hovered)} r="3.5" /></g>}
    </svg>
    {/* A flat range would print the value already shown in the metrics, so label only a real span. */}
    {high !== low && <div className="chart-scale" aria-hidden="true"><span>{money(high, true)}</span><span>{money(low, true)}</span></div>}
    <figcaption className="chart-readout" aria-live="polite">
      {/* Idle state names the record rather than repeating the value already in the metrics. */}
      {hovered
        ? <><span className="mono">{money(hovered.equity)}</span><span className="quiet">{when(hovered.at)}</span></>
        : <span className="quiet">{single ? 'One recorded valuation' : `${valid.length} recorded valuations · hover for values`}</span>}
    </figcaption>
  </figure>
}

export function Performance({ overview, performance, range, scope, search, open, onToggle }: { overview: Resource<Overview>; performance: Resource<PerformanceData>; range: Range; scope: Scope; search: string; open: boolean; onToggle: () => void }) {
  const data = overview.data
  const result = performance.data
  const allocation = data?.allocation ?? []
  const barAvailable = allocation.length > 0 && allocation.every(item => item.weight !== null && item.weight >= 0 && item.weight <= 1) && Math.abs(allocation.reduce((sum, item) => sum + (item.weight ?? 0), 0) - 1) < .001
  const single = result?.reason === 'single_observation'
  // The reference design leads with how much of the account is at work. Cash is recorded,
  // so the deployed share is the remainder rather than a separate published number.
  const cashWeight = allocation.find(item => item.asset_class === 'cash')?.weight ?? null
  const deployed = barAvailable && cashWeight !== null ? 1 - cashWeight : null
  return <section className={`performance${performance.stale || overview.stale ? ' is-updating' : ''}`} aria-label="Live portfolio">
    <ResourceNotice resource={overview} name="portfolio overview" />
    <div className="metrics">
      <div><strong title={money(data?.equity)}>{money(data?.equity, true)}</strong><span>Portfolio value</span></div>
      <div><strong className={tone(result?.return_percent)}>{percent(result?.return_percent)}</strong><span>{range} return{single ? ' · since first record' : ''}</span></div>
      <div><strong>{data ? data.reviews_today.toLocaleString() : 'Unavailable'}</strong><span>Reviews today <span className="quiet">{data ? `${data.decisions_today} decision${data.decisions_today === 1 ? '' : 's'}` : 'ET'}</span></span></div>
    </div>
    <div className="chart-heading">
      <button className="text-button portfolio-toggle" aria-expanded={open} aria-controls="portfolio-details" onClick={onToggle}><span className={`chevron ${open ? 'is-open' : ''}`} aria-hidden="true">&rsaquo;</span>{open ? 'Hide portfolio' : 'Show portfolio'}</button>
      <div className="range-controls" aria-label="Performance range">{RANGES.map(value => <button key={value} aria-pressed={value === range} onClick={() => navigate(dashboardUrl({ range: value }, search))}>{value}</button>)}</div>
    </div>
    <div className="portfolio-details" id="portfolio-details" hidden={!open}>
      <ResourceNotice resource={performance} name="performance history" />
      <SectionBoundary resetKey={result} retry={performance.refresh} name="performance">
        {result && <>
          <div className="chart-title"><span>Value history <span className="quiet">{range}</span></span>
            {data?.daily_pnl?.amount != null && <span className={`change ${tone(data.daily_pnl.amount)}`}>{money(data.daily_pnl.amount)} today</span>}
          </div>
          <PortfolioChart points={result.history} />
          <div className="chart-caption"><span>{result.start_at ? when(result.start_at, true) : 'Start unavailable'}</span><span>{result.end_at ? when(result.end_at, true) : 'End unavailable'}</span></div>
          {result.status !== 'available' && <p className="section-note">Return unavailable: {label(result.reason)}. Missing facts aren't treated as zero.</p>}
        </>}
      </SectionBoundary>
      {data?.daily_pnl && data.daily_pnl.amount == null && <p className="daily-change">Investment change unavailable · {label(data.daily_pnl.reason)}</p>}
      {deployed !== null && <div className="bar-group">
        <div className="bar-heading"><span>Deployed</span><span className="mono">{weight(deployed)}</span></div>
        <div className="bar" role="img" aria-label={`Deployed ${weight(deployed)} of recorded portfolio value`}><span style={{ width: `${deployed * 100}%` }} /></div>
      </div>}
      <div className="allocation-group"><span className="quiet">Recorded allocation</span>
        {barAvailable && <div className="allocation-bar" role="img" aria-label={allocation.map(item => `${label(item.asset_class)} ${weight(item.weight)}`).join(', ')}>{allocation.map((item, index) => <span key={item.asset_class} className={`allocation-color-${index % 4}`} style={{ width: `${(item.weight ?? 0) * 100}%` }} />)}</div>}
        {allocation.length ? <div className="allocation-legend">{allocation.map((item, index) => <span key={item.asset_class}><i className={`allocation-color-${index % 4}`} />{label(item.asset_class)} <span className="mono" title={money(item.market_value)}>{weight(item.weight)}</span></span>)}</div> : <Empty>Allocation needs complete cash and holdings data.</Empty>}
      </div>
      {result && <details className="compact-disclosure"><summary><Chevron /> Performance details</summary><div className="disclosure-body">
        <dl className="detail-grid"><Fact name="Investment gain/loss">{money(result.investment_pnl)}</Fact><Fact name="External funding change">{money(result.net_external_flows)}</Fact><Fact name="Observed drawdown">{percent(result.observed_drawdown_percent, false)}</Fact><Fact name="Cash balance">{money(data?.cash)}</Fact></dl>
        {single && <p className="section-note">One complete valuation is recorded, so nothing has changed across it yet. A second session close makes this a measured return.</p>}
        {result.range_is_partial && <p className="section-note">This record covers part of the selected range. {result.period_label}.</p>}
        {result.history.some(point => point.quality !== 'complete' || point.equity === null) && <p className="section-note">Gaps mark incomplete observations. They aren't connected by the chart.</p>}
        {data?.cash === null && <p className="section-note">Cash is unknown. Buying power and unexplained balances aren't reported as cash.</p>}
        {data?.last_complete_valuation && data.status !== 'available' && <p className="section-note">Last complete value: {money(data.last_complete_valuation.equity)}, {when(data.last_complete_valuation.at)}.</p>}
        <p className="section-note">Funding changes are deposits and withdrawals, not investment gains. Returns require complete valuations and cash-flow boundaries.</p>
        {result.benchmarks?.map(benchmark => <div className="check-row" key={benchmark.ticker}><span>{benchmark.ticker}{benchmark.primary ? ' · Primary benchmark' : ''}<small>{label(benchmark.convention)}</small></span><span className="mono" title={benchmark.reason ? label(benchmark.reason) : undefined}>{benchmark.status === 'available' ? percent(benchmark.return_percent) : 'Unavailable'}</span></div>)}
        <p className="section-note">Benchmarks use matching session closes. Observed drawdown doesn't measure intraday losses.</p>
        <details className="compact-disclosure"><summary><Chevron /> Accessible history table ({result.history.length})</summary><div className="table-scroll" tabIndex={0} role="region" aria-label="Portfolio history table"><table><thead><tr><th scope="col">Observation (ET)</th><th scope="col">Value</th><th scope="col">Return</th><th scope="col">Quality</th></tr></thead><tbody>{result.history.map((point, index) => <tr key={`${point.at}-${index}`}><th scope="row">{when(point.at)}</th><td>{money(point.equity)}</td><td>{percent(point.return_percent)}</td><td>{label(point.quality)}</td></tr>)}</tbody></table></div></details>
        {result.chart_sampling && <p className="section-note">{result.history.length} displayed observations from {result.chart_sampling.source_points}. {result.chart_sampling.reason ? label(result.chart_sampling.reason) : 'Timing and quality gaps are preserved.'}</p>}
        {result.methodology && <details className="compact-disclosure"><summary><Chevron /> Calculation method</summary><dl className="methodology">{Object.entries(result.methodology).map(([key, value]) => <Fact key={key} name={label(key)}>{value}</Fact>)}</dl></details>}
      </div></details>}
      <AsOf at={data?.data_as_of} published={data?.published_at} />
    </div>
    {!open && data && <p className="sr-only">{amount(data.equity)} US dollars. Portfolio details collapsed. Scope {scope}.</p>}
  </section>
}
