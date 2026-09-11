import { useRef, useState } from 'react'
import { Empty, ResourceNotice, SectionBoundary } from './common'
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
  let selected: { at: string; equity: number; returnPercent: number | null; recorded: boolean; x: number } | null = null
  if (active !== null) {
    for (const part of segments) {
      if (part.length === 1 && Math.abs(active - x(part[0])) < 1) {
        selected = { at: part[0].at, equity: numeric(part[0].equity)!, returnPercent: numeric(part[0].return_percent), recorded: true, x: x(part[0]) }
        break
      }
      if (part.length < 2 || active < x(part[0]) || active > x(part[part.length - 1])) continue
      let right = 1
      while (right < part.length - 1 && x(part[right]) < active) right += 1
      const before = part[right - 1], after = part[right]
      const span = x(after) - x(before)
      const ratio = span ? (active - x(before)) / span : 0
      const beforeReturn = numeric(before.return_percent), afterReturn = numeric(after.return_percent)
      selected = {
        at: new Date(Date.parse(before.at) + (Date.parse(after.at) - Date.parse(before.at)) * ratio).toISOString(),
        equity: numeric(before.equity)! + (numeric(after.equity)! - numeric(before.equity)!) * ratio,
        returnPercent: beforeReturn === null || afterReturn === null ? null : beforeReturn + (afterReturn - beforeReturn) * ratio,
        recorded: ratio < .0001 || ratio > .9999,
        x: active,
      }
      break
    }
  }
  const track = (clientX: number) => {
    const rect = frame.current?.getBoundingClientRect()
    if (!rect || !rect.width) return
    setActive(Math.min(WIDTH, Math.max(0, (clientX - rect.left) / rect.width * WIDTH)))
  }
  const move = (direction: number) => setActive(current => {
    if (current === null) return x(valid[direction < 0 ? valid.length - 1 : 0])
    let nearest = 0
    for (let index = 1; index < valid.length; index += 1) if (Math.abs(x(valid[index]) - current) < Math.abs(x(valid[nearest]) - current)) nearest = index
    return x(valid[Math.min(valid.length - 1, Math.max(0, nearest + direction))])
  })
  return <figure className="chart-figure">
    <svg ref={frame} className="portfolio-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img"
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
      {single && <line className="chart-baseline" x1="0" x2={WIDTH} y1={y(valid[0])} y2={y(valid[0])} />}
      {segments.map((part, index) => part.length === 1
        ? <circle key={index} className="chart-point" cx={x(part[0])} cy={y(part[0])} r="3" />
        : <g key={index}>{high !== low && <polygon points={`${x(part[0])},${HEIGHT} ${part.map(point => `${x(point)},${y(point)}`).join(' ')} ${x(part[part.length - 1])},${HEIGHT}`} />}<polyline points={part.map(point => `${x(point)},${y(point)}`).join(' ')} /></g>)}
      {selected && <g><line className="chart-cursor" x1={selected.x} x2={selected.x} y1="0" y2={HEIGHT} /><circle className="chart-point is-active" cx={selected.x} cy={yValue(selected.equity)} r="3.5" /></g>}
    </svg>
    {selected && <div className={`chart-tooltip${selected.x < 72 ? ' is-start' : selected.x > WIDTH - 72 ? ' is-end' : ''}`} style={{ left: `${selected.x / WIDTH * 100}%` }}>
      <span><strong className="mono">{money(selected.equity)}</strong>{selected.returnPercent != null && <span className={`mono ${tone(selected.returnPercent)}`}>{percent(selected.returnPercent)}</span>}</span>
      <time dateTime={selected.at}>{when(selected.at)} · {selected.recorded ? 'Recorded' : 'Estimated'}</time>
    </div>}
    {/* A flat range would print the value already shown in the metrics, so label only a real span. */}
    {high !== low && <div className="chart-scale" aria-hidden="true"><span>{money(high, true)}</span><span>{money(low, true)}</span></div>}
    <figcaption className="chart-readout" aria-live="polite">
      {/* Idle state names the record rather than repeating the value already in the metrics. */}
      {selected
        ? <><span className="mono">{money(selected.equity)}</span><span className="quiet">{when(selected.at)}. {selected.recorded ? 'Recorded valuation.' : 'Estimated between recorded valuations.'}</span></>
        : <span className="quiet">{single ? 'One recorded valuation' : `${valid.length} recorded valuations · point, touch or use arrow keys to inspect`}</span>}
    </figcaption>
  </figure>
}

export function Performance({ overview, performance, range, scope, search, open }: { overview: Resource<Overview>; performance: Resource<PerformanceData>; range: Range; scope: Scope; search: string; open: boolean; onToggle: () => void }) {
  const data = overview.data
  const result = performance.data
  const allocation = data?.allocation ?? []
  const barAvailable = allocation.length > 0 && allocation.every(item => item.weight !== null && item.weight >= 0 && item.weight <= 1) && Math.abs(allocation.reduce((sum, item) => sum + (item.weight ?? 0), 0) - 1) < .001
  const single = result?.reason === 'single_observation'
  return <section className={`performance${performance.stale || overview.stale ? ' is-updating' : ''}`} aria-label="Live portfolio">
    <ResourceNotice resource={overview} name="portfolio overview" />
    <div className="metrics">
      <div><strong title={money(data?.equity)}>{money(data?.equity, true)}</strong><span>Portfolio value</span></div>
      <div><strong className={tone(result?.return_percent)}>{result?.return_percent == null ? '0' : percent(result.return_percent)}</strong><span>{range} return{single ? ' · since first record' : ''}</span></div>
      <div><strong>{data ? data.reviews_today.toLocaleString() : 'Unavailable'}</strong><span>Reviews today <span className="quiet">{data ? `${data.decisions_today} decision${data.decisions_today === 1 ? '' : 's'}` : 'ET'}</span></span></div>
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
