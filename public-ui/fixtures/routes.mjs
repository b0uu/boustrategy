// Test-only routing. No production module imports these fixtures.
import fixtures from './public-v2.json' with { type: 'json' }

export function fixtureResponse(href, data = fixtures) {
  const url = new URL(href, 'http://localhost')
  const parts = url.pathname.split('/').filter(Boolean)
  let value
  if (parts[3] === 'portfolios') {
    value = parts[5] === 'activity' && parts[6] ? data[parts[6]] : data[`${parts[4]}/${parts[5]}`]
    if (parts[5] === 'performance' && value) value = { ...value, range: url.searchParams.get('range') ?? 'All' }
  } else if (parts[3] === 'decisions' && parts[4]) {
    value = data[parts[4]]
    if (parts[5] === 'export' && value && url.searchParams.get('format') === 'csv') return { status: 200, body: 'ticker,decision,public_summary\r\nNVDA,BUY,"Public fixture export"\r\n', contentType: 'text/csv' }
  } else if (parts[3] === 'legacy-decisions') {
    value = Object.values(data).find(item => item.public_id && item.ticker === decodeURIComponent(parts[4]) && Date.parse(item.created_at) === Date.parse(decodeURIComponent(parts[5])))
  } else if (parts[3] === 'decisions') {
    const source = data[`${url.searchParams.get('portfolio_id') ?? 'live'}/feed`]
    let items = source.items
    const q = (url.searchParams.get('q') ?? '').toLowerCase()
    if (q) items = items.filter(item => `${item.ticker} ${item.company_name ?? ''} ${item.public_summary}`.toLowerCase().includes(q))
    for (const [param, field] of [['action', 'decision'], ['policy', 'policy_outcome'], ['lifecycle', 'lifecycle'], ['run_id', 'public_run_id']]) {
      if (url.searchParams.has(param)) items = items.filter(item => item[field] === url.searchParams.get(param))
    }
    if (url.searchParams.has('since')) items = items.filter(item => Date.parse(item.created_at) >= Date.parse(url.searchParams.get('since')))
    if (url.searchParams.has('until')) items = items.filter(item => Date.parse(item.created_at) < Date.parse(url.searchParams.get('until')))
    const start = Number(url.searchParams.get('cursor') ?? 0)
    const limit = Number(url.searchParams.get('limit') ?? 25)
    value = { ...source, total: items.length, items: items.slice(start, start + limit), next_cursor: start + limit < items.length ? String(start + limit) : null }
  }
  return value ? { status: 200, body: JSON.stringify(value), contentType: 'application/json' } : { status: 404, body: JSON.stringify({ detail: 'decision_not_found' }), contentType: 'application/json' }
}

export async function installFixtures(page, data = fixtures) {
  await page.route('**/api/public/v2/**', async route => {
    await route.fulfill(fixtureResponse(route.request().url(), data))
  })
}

export { fixtures }
