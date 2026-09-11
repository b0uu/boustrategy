import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'
import { readPublic, usePublic } from './api'
import { ResourceNotice } from './common'
import { AgentStatus } from './Activity'
import { PortfolioChart } from './Performance'
import { amount, label, money, percent, publicUrl, tone } from './format'
import { navigate } from './navigation'
import { fixtureResponse, fixtures } from '../fixtures/routes.mjs'
import type { Decision, FeedPage, Overview, Runtime } from './types'

let data: Record<string, unknown>
const feed = () => data['live/feed'] as FeedPage
const json = (value: unknown, status = 200, headers = {}) => new Response(JSON.stringify(value), { status, headers })
function respond(url: string) {
  const result = fixtureResponse(url, data)
  return new Response(result.body, { status: result.status, headers: { 'Content-Type': result.contentType } })
}
const rows = () => document.querySelectorAll('.stream-row--decision')
async function dashboard() { render(<App />); await waitFor(() => expect(rows()).toHaveLength(25)) }
beforeEach(() => {
  data = structuredClone(fixtures)
  history.replaceState({}, '', '/')
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(respond(url))))
  vi.stubGlobal('scrollTo', vi.fn())
  vi.stubGlobal('cancelAnimationFrame', clearTimeout)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(callback, 0))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })

it('reports the live account only and never offers the paper simulation', async () => {
  await dashboard()
  expect(screen.getByRole('heading', { name: 'BouStrategy Agent' })).toBeVisible()
  expect(screen.getByTitle('$10,400.00')).toHaveTextContent('$10.4K')
  expect(screen.getByText('Portfolio value')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Paper simulation' })).not.toBeInTheDocument()
  expect(screen.queryByText(/Simulated results/)).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.every(([url]) => !String(url).includes('portfolios/paper'))).toBe(true)
  expect(screen.queryByText('Decision trace')).not.toBeInTheDocument()
})

it('dismisses agent details when the reader clicks elsewhere', async () => {
  await dashboard()
  const trigger = screen.getByLabelText('Agent and publication details')
  fireEvent.click(trigger)
  expect(trigger.closest('details')).toHaveAttribute('open')
  fireEvent.pointerDown(document.body)
  expect(trigger.closest('details')).not.toHaveAttribute('open')
})

it('shows reviews beside decisions so a no-action session is still public work', async () => {
  await dashboard()
  await waitFor(() => expect(document.querySelectorAll('.stream-row--review')).toHaveLength(1))
  fireEvent.click(screen.getByRole('button', { name: 'positions' }))
  fireEvent.click(screen.getByRole('button', { name: 'feed' }))
  expect(document.querySelectorAll('.stream-row--review')).toHaveLength(1)
})
it('defers the feed until first opened and retains its pages across tabs', async () => {
  history.replaceState({}, '', '/?tab=policies')
  render(<App />)
  await screen.findByTitle('$10,400.00')
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/v2/decisions?'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'feed' }))
  await waitFor(() => expect(rows()).toHaveLength(25))
  fireEvent.click(screen.getByRole('button', { name: /Show more/ }))
  await waitFor(() => expect(rows()).toHaveLength(50))
  fireEvent.click(screen.getByRole('button', { name: 'policies' }))
  fireEvent.click(screen.getByRole('button', { name: 'feed' }))
  expect(rows()).toHaveLength(50)
  expect(rows()[0]).toBeVisible()
})
it('retains loaded feed through trace and Back', async () => {
  await dashboard()
  fireEvent.click(screen.getByRole('button', { name: /Show more/ }))
  await waitFor(() => expect(rows()).toHaveLength(50))
  fireEvent.click(rows()[0])
  await screen.findByRole('button', { name: 'Copy link' })
  fireEvent.click(document.querySelector('a.back')!)
  await waitFor(() => expect(rows()).toHaveLength(50))
  expect(rows()[0]).toBeVisible()
})
it('searches history on Enter and restores URL queries on navigation', async () => {
  await dashboard()
  fireEvent.click(screen.getByRole('button', { name: 'Search and filter' }))
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'repeat demand' } })
  fireEvent.submit(screen.getByRole('searchbox').closest('form')!)
  await waitFor(() => expect(rows()).toHaveLength(11))
  expect(location.search).toContain('q=repeat+demand')
  act(() => navigate('/?q=nonexistent'))
  expect(await screen.findByText('No public decisions match these filters.')).toBeVisible()
  act(() => { history.replaceState({}, '', '/?q=repeat+demand'); window.dispatchEvent(new PopStateEvent('popstate')) })
  await waitFor(() => expect(rows()).toHaveLength(11))
})
it('debounces search and discards a canceled response arriving last', async () => {
  await dashboard()
  fireEvent.click(screen.getByRole('button', { name: 'Search and filter' }))
  let resolveOld!: (value: Response) => void
  let signal: AbortSignal | undefined
  vi.mocked(fetch).mockImplementation((input, init) => {
    if (String(input).includes('q=old')) { signal = init?.signal as AbortSignal; return new Promise(resolve => { resolveOld = resolve }) }
    return Promise.resolve(respond(String(input)))
  })
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'old' } })
  await waitFor(() => expect(resolveOld).toBeDefined())
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'repeat demand' } })
  fireEvent.submit(screen.getByRole('searchbox').closest('form')!)
  await waitFor(() => expect(rows()).toHaveLength(11))
  expect(signal?.aborted).toBe(true)
  await act(async () => resolveOld(json({ ...feed(), items: [feed().items[0]], total: 1, next_cursor: null })))
  expect(rows()).toHaveLength(11)
})
it('locks repeated Show more, preserves focus, retries failed page and deduplicates', async () => {
  await dashboard()
  let release!: (value: Response) => void
  let requests = 0
  vi.mocked(fetch).mockImplementation(input => {
    if (String(input).includes('cursor=')) { requests++; return new Promise(resolve => { release = resolve }) }
    return Promise.resolve(respond(String(input)))
  })
  const more = screen.getByRole('button', { name: /Show more/ }); more.focus()
  fireEvent.click(more); fireEvent.click(more)
  expect(requests).toBe(1); expect(more).toHaveFocus()
  await act(async () => release(json({}, 503)))
  expect(rows()).toHaveLength(25)
  fireEvent.click(screen.getByRole('button', { name: /Try again/ }))
  expect(requests).toBe(2)
  await act(async () => release(json({ ...feed(), items: [feed().items[24], feed().items[25]], next_cursor: null })))
  expect(rows()).toHaveLength(26)
})
it('offers updates without moving records under a reader', async () => {
  await dashboard()
  const first = rows()[0].textContent
  data['live/feed'] = { ...feed(), items: [{ ...feed().items[0], public_id: 'pub_new', public_summary: 'New public decision' }, ...feed().items], total: 56 }
  act(() => window.dispatchEvent(new Event('online')))
  const update = await screen.findByRole('button', { name: /1 new update/ })
  expect(rows()[0].textContent).toBe(first)
  fireEvent.click(update)
  expect(await screen.findByText('New public decision')).toBeVisible()
})
it('handles revision conflicts through explicit restart', async () => {
  await dashboard()
  vi.mocked(fetch).mockImplementation(input => Promise.resolve(String(input).includes('cursor=') ? json({}, 409) : respond(String(input))))
  fireEvent.click(screen.getByRole('button', { name: /Show more/ }))
  fireEvent.click(await screen.findByRole('button', { name: /Refresh this view/ }))
  await waitFor(() => expect(screen.queryByText(/Published records changed. Refresh to restart/)).not.toBeInTheDocument())
  expect(rows()).toHaveLength(25)
})
it('contains malformed nested positions without breaking the portfolio', async () => {
  await dashboard(); vi.spyOn(console, 'error').mockImplementation(() => {})
  data['live/positions'] = { ...(data['live/positions'] as object), items: [{ ticker: 'NVDA', thesis_review: { state: {} } }] }
  fireEvent.click(screen.getByRole('button', { name: 'positions' }))
  expect(await screen.findByText(/positions response couldn't be displayed/)).toBeVisible()
  expect(screen.getByTitle('$10,400.00')).toHaveTextContent('$10.4K')
})
it('keeps last good overview on transient failure and retries locally', async () => {
  await dashboard()
  vi.mocked(fetch).mockImplementation(input => Promise.resolve(String(input).endsWith('/overview') ? json({}, 503) : respond(String(input))))
  act(() => window.dispatchEvent(new Event('online')))
  expect(await screen.findByText(/Showing the last loaded data/)).toBeVisible()
  expect(screen.getByTitle('$10,400.00')).toHaveTextContent('$10.4K')
  vi.mocked(fetch).mockImplementation(input => Promise.resolve(respond(String(input))))
  fireEvent.click(screen.getByRole('button', { name: /Try again/ }))
  await waitFor(() => expect(screen.queryByText(/Showing the last loaded data/)).not.toBeInTheDocument())
})
it('gates wake and manual retries until Retry-After expires', async () => {
  vi.useFakeTimers()
  vi.mocked(fetch).mockResolvedValue(json({}, 429, { 'Retry-After': '10' }))
  function Probe() { const resource = usePublic<Overview>('/overview', 'overview', 0); return <ResourceNotice resource={resource} name="overview" /> }
  render(<Probe />); await act(async () => {})
  expect(fetch).toHaveBeenCalledTimes(1); expect(screen.getByRole('button')).toBeDisabled()
  act(() => window.dispatchEvent(new Event('online')))
  await act(async () => vi.advanceTimersByTime(9000))
  expect(fetch).toHaveBeenCalledTimes(1)
  vi.mocked(fetch).mockResolvedValue(json(data['live/overview']))
  await act(async () => vi.advanceTimersByTime(1000))
  expect(fetch).toHaveBeenCalledTimes(2)
})
it.each([404, 410])('shows a deliberate %s trace state', async status => {
  history.replaceState({}, '', '/decisions/missing'); vi.mocked(fetch).mockResolvedValue(json({}, status)); render(<App />)
  expect(await screen.findByRole('heading', { name: status === 404 ? 'Public decision not found' : 'This record has been withdrawn' })).toBeVisible()
})
it('clears revoked trace and cached feed snippets', async () => {
  await dashboard(); const item = feed().items[0]; fireEvent.click(rows()[0])
  await screen.findByRole('heading', { name: 'Decision trace' })
  data['live/feed'] = { ...feed(), items: feed().items.filter(row => row.public_id !== item.public_id), total: 54 }
  vi.mocked(fetch).mockImplementation(input => Promise.resolve(String(input).endsWith(item.public_id) ? json({}, 410) : respond(String(input))))
  act(() => window.dispatchEvent(new Event('online')))
  expect(await screen.findByText('This record has been withdrawn')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Download CSV' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('link', { name: 'Back to feed' }))
  await waitFor(() => expect(rows()).toHaveLength(25))
  expect(rows()[0].getAttribute('href')).not.toContain(item.public_id)
})
it('loads legacy URLs, offers canonical copy fallback and exports CSV', async () => {
  const item = feed().items[0]; history.replaceState({}, '', `/decisions/${item.ticker}/${encodeURIComponent(item.created_at)}`)
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:fixture') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  render(<App />); fireEvent.click(await screen.findByRole('button', { name: 'Copy link' }))
  expect(await screen.findByRole('textbox', { name: 'Copy this public link' })).toHaveValue(location.origin + `/decisions/${item.public_id}?scope=live`)
  fireEvent.click(screen.getByRole('button', { name: 'Download CSV' }))
  await waitFor(() => expect(click).toHaveBeenCalled())
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/export?format=csv'))).toBe(true)
})
it('renders long sources safely in native disclosures', async () => {
  const item = feed().items[0]; const decision = data[item.public_id] as Decision
  decision.narrative!.sources[0].url = 'javascript:alert(1)'; decision.narrative!.sources[0].title = 'Long source title '.repeat(40)
  history.replaceState({}, '', `/decisions/${item.public_id}`); render(<App />)
  await screen.findByRole('heading', { name: 'Decision trace' })
  expect(document.querySelector('a[href^="javascript:"]')).toBeNull()
  const summary = screen.getByText('Variant perception').closest('summary')!; summary.focus()
  expect(summary).toHaveFocus(); expect(summary.parentElement?.tagName).toBe('DETAILS')
})
it('renders approved markup-like text as text', async () => {
  const item = feed().items[0]
  const decision = data[item.public_id] as Decision
  decision.public_summary = '<img src=x onerror="window.fixtureInjected=true">'
  decision.narrative!.stages[0].summary = '<script>window.fixtureInjected=true</script>'
  history.replaceState({}, '', `/decisions/${item.public_id}`)

  render(<App />)

  expect(await screen.findByText(decision.public_summary)).toBeVisible()
  expect(screen.getAllByText(decision.narrative!.stages[0].summary).length).toBeGreaterThan(0)
  expect(document.querySelector('.trace img')).toBeNull()
  expect(document.querySelector('.trace script')).toBeNull()
  expect((window as typeof window & { fixtureInjected?: boolean }).fixtureInjected).toBeUndefined()
})
it('preserves unavailable money, signed zero and tiny decimal quantities', () => {
  expect(money(null)).toBe('Unavailable'); expect(money('-0.001')).toBe('$0.00')
  expect(percent('-0.001')).toBe('0.00%'); expect(tone('-0.001')).toBe('')
  expect(amount('0.000000000000000001')).toBe('0.000000000000000001')
  expect(amount('-0.000000000000000001')).toBe('-0.000000000000000001')
  expect(publicUrl('https://user:password@example.com')).toBeNull()
})
it('shows a missing one-month return as zero in the dashboard metric', async () => {
  data['live/performance'] = { ...(data['live/performance'] as object), return_percent: null }
  await dashboard()
  expect(screen.getByText('1M return').previousElementSibling).toHaveTextContent('0')
})
it.each([
  ['unfunded', 'The recorded account balance is zero, with no open positions.'],
  ['all_cash', 'No open positions. The complete recorded balance is cash.'],
  ['sold_out', 'All observed positions have been closed.'],
])('explains the %s zero-position state', async (portfolioState, message) => {
  data['live/overview'] = { ...(data['live/overview'] as Overview), portfolio_state: portfolioState, equity: portfolioState === 'unfunded' ? '0' : '10400', cash: portfolioState === 'unfunded' ? '0' : '10400' }
  data['live/positions'] = { ...(data['live/positions'] as object), items: [] }
  await dashboard()
  fireEvent.click(screen.getByRole('button', { name: 'positions' }))
  expect(await screen.findByText(message)).toBeVisible()
})
it('keeps a partially valued position visible without inventing missing values', async () => {
  const positions = data['live/positions'] as { items: Array<Record<string, unknown>>; status: string; valuation_status: string; reason: string | null }
  positions.status = 'available'
  positions.valuation_status = 'partial'
  positions.reason = 'incomplete_reporting_balance'
  positions.items[0] = { ...positions.items[0], market_value: null, latest_price: null, weight: null, price_quality: 'missing' }
  await dashboard()
  fireEvent.click(screen.getByRole('button', { name: 'positions' }))
  expect((await screen.findAllByText('NVDA')).length).toBeGreaterThan(0)
  expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0)
  expect(screen.getByText(/Missing quotes and cash aren't treated as zero/)).toBeVisible()
})
it('handles flat, single and gapped timestamp-spaced charts', () => {
  const points = [{ at: '2026-06-10T20:00:00Z', equity: '100', quality: 'complete', return_percent: '0' }, { at: '2026-06-11T20:00:00Z', equity: null, quality: 'incomplete', return_percent: null }, { at: '2026-06-15T20:00:00Z', equity: '100', quality: 'complete', return_percent: '0' }]
  const { rerender } = render(<PortfolioChart points={points} />)
  expect(document.querySelectorAll('circle')).toHaveLength(2); expect(document.querySelector('polyline')).toBeNull()
  rerender(<PortfolioChart points={[points[0]]} />)
  expect(document.querySelector('circle')).toHaveAttribute('cx', '300')
  rerender(<PortfolioChart points={[]} />); expect(screen.getByText(/history isn't available/)).toBeVisible()
})
it('lets keyboard readers inspect continuous chart observations', () => {
  const points = [{ at: '2026-06-10T20:00:00Z', equity: '100', quality: 'complete', return_percent: '0' }, { at: '2026-06-11T20:00:00Z', equity: '102', quality: 'complete', return_percent: '2' }]
  render(<PortfolioChart points={points} />)
  const chart = screen.getByRole('img')
  fireEvent.keyDown(chart, { key: 'Home' })
  expect(document.querySelector('.chart-tooltip')).toHaveTextContent('$100.00')
  fireEvent.keyDown(chart, { key: 'ArrowRight' })
  expect(document.querySelector('.chart-tooltip')).toHaveTextContent('$102.00')
  fireEvent.keyDown(chart, { key: 'Escape' })
  expect(document.querySelector('.chart-tooltip')).not.toBeInTheDocument()
})
it('interpolates a clearly labeled estimate at the exact pointer time', () => {
  const points = [{ at: '2026-06-10T20:00:00Z', equity: '100', quality: 'complete', return_percent: '0' }, { at: '2026-06-10T22:00:00Z', equity: '102', quality: 'complete', return_percent: '2' }]
  render(<PortfolioChart points={points} />)
  const chart = screen.getByRole('img')
  vi.spyOn(chart, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, width: 600, height: 108, top: 0, right: 600, bottom: 108, left: 0, toJSON: () => ({}) })
  vi.stubGlobal('PointerEvent', MouseEvent)
  fireEvent.pointerMove(chart, { clientX: 300 })
  expect(document.querySelector('.chart-tooltip')).toHaveTextContent('$101.00')
  expect(document.querySelector('.chart-tooltip')).toHaveTextContent('Estimated')
})
it('counts down using server time and waits at zero', async () => {
  vi.useFakeTimers(); const now = Date.now(); const runtime = data['live/runtime'] as Runtime
  runtime.server_now = new Date(now + 60000).toISOString()
  runtime.schedules = [{ schedule_mode: 'scheduled', enabled: true, paused: false, timezone: 'America/New_York', revision: 1, next_due_at: new Date(now + 65000).toISOString(), observer_as_of: runtime.server_now, observer_max_age_seconds: 180, grace_seconds: 1800, reason: null }]
  vi.mocked(fetch).mockImplementation(input => {
    runtime.server_now = new Date(Date.now() + 60000).toISOString()
    return Promise.resolve(respond(String(input)))
  })
  render(<AgentStatus scope="live" />); await act(async () => {})
  expect(screen.getByText('Next review in 0m 05s')).toBeVisible()
  await act(async () => vi.advanceTimersByTime(5000))
  expect(screen.getByText('Waiting for the scheduler')).toBeVisible()
  runtime.schedules[0].paused = true; act(() => window.dispatchEvent(new Event('online'))); await act(async () => {})
  expect(screen.queryByText(/Next review in/)).not.toBeInTheDocument()
})
it('labels missing runtime authority without implying manual operation', async () => {
  data['live/runtime'] = {
    ...(data['live/runtime'] as Runtime),
    status: 'unavailable',
    reason: 'runtime_not_published',
    latest_run: null,
    active_run: null,
    schedules: [],
    schedule_mode: undefined,
  }
  render(<AgentStatus scope="live" />)
  expect(await screen.findByText('Agent activity unavailable')).toBeVisible()
  expect(screen.getByText("Runtime status hasn't been published")).toBeVisible()
  expect(screen.queryByText('Manual reviews')).not.toBeInTheDocument()
})
it('shows an unknown page and an invalid section instead of dashboard defaults', () => {
  history.replaceState({}, '', '/unknown'); render(<App />)
  expect(screen.getByRole('heading', { name: 'Page not found' })).toBeVisible()
  act(() => navigate('/?tab=private'))
  expect(screen.getByRole('heading', { name: 'This dashboard link is invalid' })).toBeVisible()
})
it('rejects malformed transport metadata before rendering', async () => {
  vi.mocked(fetch).mockResolvedValue(json({ api_version: 2, server_now: 'invalid', items: [] }))
  await expect(readPublic('/feed', 'feed', new AbortController().signal)).rejects.toThrow('unexpected format')
})

it('reads policy checks as one marked table of observed against threshold', async () => {
  const item = feed().items[0]
  const decision = data[item.public_id] as Decision
  const check = decision.policy_evaluation.checks.find(row => row.result === 'passed')!
  history.replaceState({}, '', `/decisions/${item.public_id}`)

  render(<App />)
  await screen.findByRole('heading', { name: 'Decision trace' })

  const rendered = document.querySelectorAll('.policy-check')
  expect(rendered).toHaveLength(decision.policy_evaluation.checks.length)
  const row = document.querySelector(`.policy-check--passed`)!
  expect(row.querySelector('.check-mark')).toHaveTextContent('✓')
  expect(row.querySelector('.rule-code')).toHaveTextContent(check.rule_id)
  // An unevaluated rule is neither a pass nor a failure, so it never takes a verdict colour.
  const inconclusive = [...rendered].filter(node => node.className.includes('inconclusive'))
  expect(inconclusive.length).toBe(decision.policy_evaluation.checks.filter(c => !['passed', 'failed'].includes(c.result)).length)
})
it('shows each rule id and threshold without cramped description copy', async () => {
  history.replaceState({}, '', '/?tab=policies')
  render(<App />)
  const rules = (data['live/policy'] as { decision_rules: Array<{ rule_id: string; name: string; failure_explanation: string }> }).decision_rules
  await waitFor(() => expect(document.querySelectorAll('.policy-row')).toHaveLength(rules.length))
  const first = document.querySelector('.policy-row > summary')!
  expect(first.querySelector('.rule-code')).toHaveTextContent(rules[0].rule_id)
  expect(first.querySelector('.rule-meta')).toBeVisible()
  expect(first.querySelector('.rule-description')).toBeNull()
  expect(screen.getByText(rules[0].name, { exact: false })).toBeVisible()
})
it('lists every published source once in the source pack', async () => {
  const item = feed().items[0]
  const decision = data[item.public_id] as Decision
  history.replaceState({}, '', `/decisions/${item.public_id}`)

  render(<App />)
  await screen.findByRole('heading', { name: 'Source pack' })

  const pack = document.querySelectorAll('.source-pack > div')
  expect(pack).toHaveLength(decision.narrative!.sources.length)
  for (const source of decision.narrative!.sources) {
    expect([...pack].filter(row => row.textContent?.includes(source.title))).toHaveLength(1)
  }
})
it('leads with invalidation criteria instead of hiding them behind a disclosure', async () => {
  const item = feed().items[0]
  const decision = data[item.public_id] as Decision
  const criteria = decision.narrative!.conditions!.invalidation
  history.replaceState({}, '', `/decisions/${item.public_id}`)

  render(<App />)
  const heading = await screen.findByRole('heading', { name: 'Invalidation criteria' })

  expect(heading.closest('details')).toBeNull()
  for (const line of criteria) expect(screen.getByText(line)).toBeVisible()
})

it('shows every status label in sentence case, never raw lowercase', () => {
  expect(label('BUY')).toBe('Buy')
  expect(label('preclose')).toBe('Preclose')
  expect(label('broker_failed')).toBe('Order attempt failed')
  expect(label('broker_filled')).toBe('Broker fill reported')
  expect(label('some_new_code')).toBe('Some new code')
})
