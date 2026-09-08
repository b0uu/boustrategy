import { Chevron, Empty, Fact, ResourceNotice, SectionBoundary, AsOf } from './common'
import type { Resource } from './api'
import { amount, label, money, numeric, percent, tone, weight, when } from './format'
import { dashboardUrl, navigate } from './navigation'
import type { ChartPoint, Overview, Performance as PerformanceData, Range, Scope } from './types'

export function PortfolioChart({ points }: { points: ChartPoint[] }) {
  const valid = points.filter(point => numeric(point.equity) !== null && point.quality === 'complete')
  if (!valid.length) return <Empty>Portfolio history isn't available for this range.</Empty>
  const times = points.map(point => Date.parse(point.at))
  const first = Math.min(...times), last = Math.max(...times)
  const values = valid.map(point => numeric(point.equity)!)
  const low = Math.min(...values), high = Math.max(...values)
  const coordinate = (point: ChartPoint) => [last === first ? 300 : (Date.parse(point.at) - first) / (last - first) * 600, high === low ? 54 : 96 - (numeric(point.equity)! - low) / (high - low) * 84]
  const segments: ChartPoint[][] = []
  let segment: ChartPoint[] = []
  for (const point of points) {
    if (numeric(point.equity) === null || point.quality !== 'complete') {
      if (segment.length) segments.push(segment)
      segment = []
    } else segment.push(point)
  }
  if (segment.length) segments.push(segment)
  return <svg className="portfolio-chart" viewBox="0 0 600 108" preserveAspectRatio="none" role="img" aria-label={`Portfolio value, ${valid.length} complete observations. ${money(values[0])} to ${money(values[values.length - 1])}. Incomplete observations are gaps.`}>
    {segments.map((part, index) => part.length === 1 ? <circle key={index} cx={coordinate(part[0])[0]} cy={coordinate(part[0])[1]} r="2.5" fill="var(--indigo)" /> : <g key={index}><polygon points={`${coordinate(part[0])[0]},108 ${part.map(point => coordinate(point).join(',')).join(' ')} ${coordinate(part[part.length - 1])[0]},108`} /><polyline points={part.map(point => coordinate(point).join(',')).join(' ')} /></g>)}
  </svg>
}

export function Performance({ overview, performance, range, scope, search, open }: { overview: Resource<Overview>; performance: Resource<PerformanceData>; range: Range; scope: Scope; search: string; open: boolean }) {
  const data = overview.data
  const result = performance.data
  const allocation = data?.allocation ?? []
  const barAvailable = allocation.length > 0 && allocation.every(item => item.weight !== null && item.weight >= 0 && item.weight <= 1) && Math.abs(allocation.reduce((sum, item) => sum + (item.weight ?? 0), 0) - 1) < .001
  return <section className="performance" aria-label={`${scope === 'live' ? 'Live' : 'Paper'} portfolio`}>
    <ResourceNotice resource={overview} name="portfolio overview" />
    <div className="metrics">
      <div><strong title={money(data?.equity)}>{money(data?.equity, true)}</strong><span>{scope === 'live' ? 'Portfolio value' : 'Paper equity'}</span></div>
      <div><strong className={tone(result?.return_percent)}>{percent(result?.return_percent)}</strong><span>{range} investment return</span></div>
      <div><strong>{data ? data.decisions_today.toLocaleString() : 'Unavailable'}</strong><span>Decisions today <span className="quiet">ET</span></span></div>
    </div>
    <div className="portfolio-details" id="portfolio-details" hidden={!open}>
      <div className="chart-heading"><span>Portfolio value <span className="quiet">USD</span></span><div className="range-controls" aria-label="Performance range">{(['1M', '3M', 'YTD', 'All'] as const).map(value => <button key={value} aria-pressed={value === range} onClick={() => navigate(dashboardUrl({ range: value }, search))}>{value}</button>)}</div></div>
      <ResourceNotice resource={performance} name="performance history" />
      <SectionBoundary resetKey={result} retry={performance.refresh} name="performance">
        {result && <>
          <PortfolioChart points={result.history} />
          <div className="chart-caption"><span>{result.start_at ? when(result.start_at, true) : 'Start unavailable'}</span><span>{result.end_at ? when(result.end_at, true) : 'End unavailable'}</span></div>
          {result.range_is_partial && <p className="section-note">This record covers part of the selected range. {result.period_label}.</p>}
          {result.status !== 'available' && <p className="section-note">Investment return unavailable: {label(result.reason)}. Missing facts aren't treated as zero.</p>}
          {result.history.some(point => point.quality !== 'complete' || point.equity === null) && <p className="section-note">Gaps mark incomplete observations. They aren't connected by the chart.</p>}
          <details className="compact-disclosure"><summary><Chevron /> Performance details</summary><div className="disclosure-body">
            <dl className="detail-grid"><Fact name="Investment gain/loss">{money(result.investment_pnl)}</Fact><Fact name="External funding change">{money(result.net_external_flows)}</Fact><Fact name="Observed drawdown">{percent(result.observed_drawdown_percent, false)}</Fact><Fact name="Cash balance">{money(data?.cash)}</Fact></dl>
            <p className="section-note">Funding changes are deposits and withdrawals, not investment gains. Returns require complete valuations and cash-flow boundaries.</p>
            {result.benchmarks?.map(benchmark => <div className="check-row" key={benchmark.ticker}><span>{benchmark.ticker}{benchmark.primary ? ' · Primary benchmark' : ''}<small>{label(benchmark.convention)}</small></span><span className="mono" title={benchmark.reason ? label(benchmark.reason) : undefined}>{benchmark.status === 'available' ? percent(benchmark.return_percent) : 'Unavailable'}</span></div>)}
            <p className="section-note">Benchmarks use matching session closes. Observed drawdown doesn't measure intraday losses.</p>
            <details className="compact-disclosure"><summary><Chevron /> Accessible history table ({result.history.length})</summary><div className="table-scroll" tabIndex={0} role="region" aria-label="Portfolio history table"><table><thead><tr><th scope="col">Observation (ET)</th><th scope="col">Value</th><th scope="col">Return</th><th scope="col">Quality</th></tr></thead><tbody>{result.history.map((point, index) => <tr key={`${point.at}-${index}`}><th scope="row">{when(point.at)}</th><td>{money(point.equity)}</td><td>{percent(point.return_percent)}</td><td>{label(point.quality)}</td></tr>)}</tbody></table></div></details>
            {result.chart_sampling && <p className="section-note">{result.history.length} displayed observations from {result.chart_sampling.source_points}. {result.chart_sampling.reason ? label(result.chart_sampling.reason) : 'Timing and quality gaps are preserved.'}</p>}
            {result.methodology && <details className="compact-disclosure"><summary><Chevron /> Calculation method</summary><dl className="methodology">{Object.entries(result.methodology).map(([key, value]) => <Fact key={key} name={label(key)}>{value}</Fact>)}</dl></details>}
          </div></details>
        </>}
      </SectionBoundary>
      {data?.daily_pnl && <p className="daily-change"><span className={tone(data.daily_pnl.amount)}>{money(data.daily_pnl.amount)}</span> investment change{data.daily_pnl.baseline_at ? ` since ${when(data.daily_pnl.baseline_at)}` : ` · ${label(data.daily_pnl.reason)}`}</p>}
      {data?.last_complete_valuation && data.status !== 'available' && <p className="section-note">Last complete value: {money(data.last_complete_valuation.equity)}, {when(data.last_complete_valuation.at)}.</p>}
      <div className="allocation-group"><span className="quiet">Recorded allocation</span>
        {barAvailable && <div className="allocation-bar" role="img" aria-label={allocation.map(item => `${label(item.asset_class)} ${weight(item.weight)}`).join(', ')}>{allocation.map((item, index) => <span key={item.asset_class} className={`allocation-color-${index % 4}`} style={{ width: `${(item.weight ?? 0) * 100}%` }} />)}</div>}
        {allocation.length ? <div className="allocation-legend">{allocation.map((item, index) => <span key={item.asset_class}><i className={`allocation-color-${index % 4}`} />{label(item.asset_class)} <span className="mono" title={money(item.market_value)}>{weight(item.weight)}</span></span>)}</div> : <Empty>Allocation needs complete cash and holdings data.</Empty>}
      </div>
      {data?.cash === null && <p className="section-note">Cash is unknown. Buying power and unexplained balances aren't reported as cash.</p>}
      <AsOf at={data?.data_as_of} published={data?.published_at} />
    </div>
    {!open && data && <p className="sr-only">{amount(data.equity)} US dollars. Portfolio details collapsed.</p>}
  </section>
}
