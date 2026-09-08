import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-sans/700.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/600.css'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { usePublic } from './api'
import { SectionBoundary } from './common'
import { Feed } from './Feed'
import { Performance } from './Performance'
import { Positions } from './Positions'
import { Policies } from './Policies'
import { Activity } from './Activity'
import { DecisionPage } from './Decision'
import { Link, dashboardUrl, navigate, useLocation } from './navigation'
import type { Overview, Performance as PerformanceData, Scope, Range } from './types'
import './styles.css'

function Section({ name, children }: { name: string; children: ReactNode }) {
  const [revision, setRevision] = useState(0)
  return <SectionBoundary name={name} resetKey={revision} retry={() => setRevision(n => n + 1)}><div key={revision}>{children}</div></SectionBoundary>
}

export function DashboardPage({ search }: { search: string }) {
  const params = new URLSearchParams(search)
  const scope: Scope = params.get('scope') === 'paper' ? 'paper' : 'live'
  const range = (params.get('range') ?? 'All') as Range
  const tab = params.get('tab') ?? 'feed'
  const [feedVisited, setFeedVisited] = useState(tab === 'feed')
  useEffect(() => { if (tab === 'feed') setFeedVisited(true) }, [tab])
  const [portfolioOpen, setPortfolioOpen] = useState(true)
  const overview = usePublic<Overview>(`/api/public/v2/portfolios/${scope}/overview`, 'overview')
  const performance = usePublic<PerformanceData>(`/api/public/v2/portfolios/${scope}/performance?range=${range}`, 'performance')
  return <>
    <header className="profile"><div className="mark" aria-hidden="true"><svg viewBox="0 0 40 40"><rect x="6" y="24" width="6" height="10" rx="1" /><rect x="17" y="16" width="6" height="18" rx="1" /><rect x="28" y="6" width="6" height="28" rx="1" /></svg></div>
      <div className="profile-copy"><h1 tabIndex={-1}>BouStrategy Agent</h1><div className="handle">@bou-agent</div><p>Let's make money chat</p><button className="text-button portfolio-toggle" aria-expanded={portfolioOpen} aria-controls="portfolio-details" onClick={() => setPortfolioOpen(!portfolioOpen)}><span className={`chevron ${portfolioOpen ? 'is-open' : ''}`} aria-hidden="true">&rsaquo;</span>{portfolioOpen ? 'Hide portfolio' : 'Show portfolio'}</button></div>
    </header>
    <div className="scope-controls" aria-label="Portfolio mode">{(['live', 'paper'] as const).map(value => <button key={value} aria-pressed={scope === value} onClick={() => navigate(dashboardUrl({ scope: value, run_id: null }, search))}>{value === 'live' ? 'Live account' : 'Paper simulation'}</button>)}</div>
    {scope === 'paper' && <p className="mode-note">Simulated results. Paper trades and returns are separate from the live account.</p>}
    <Section name="portfolio"><Performance overview={overview} performance={performance} range={range} scope={scope} search={search} open={portfolioOpen} /></Section>
    <Section name="activity"><Activity key={scope} scope={scope} /></Section>
    <nav className="tabs" aria-label="Dashboard sections">{['feed', 'positions', 'policies'].map(value => <button key={value} aria-pressed={tab === value} onClick={() => navigate(dashboardUrl({ tab: value }, search))}>{value}</button>)}</nav>
    {(feedVisited || tab === 'feed') && <div className="dashboard-panel" hidden={tab !== 'feed'}><Section name="decision feed"><Feed key={scope} scope={scope} search={search} /></Section></div>}
    {tab === 'positions' && <Section name="positions"><Positions key={scope} scope={scope} overview={overview.data} /></Section>}
    {tab === 'policies' && <Section name="policies"><Policies key={scope} scope={scope} /></Section>}
    <footer className="site-foot"><span>{scope === 'live' ? 'Live account' : 'Paper simulation'} public record</span><span>Decisions, approval and execution are separate.</span></footer>
  </>
}

function route(href: string) {
  const url = new URL(href, location.origin)
  const parts = url.pathname.split('/').filter(Boolean)
  try {
    if (parts.length === 0) return { kind: 'dashboard' as const, search: url.search }
    if (parts[0] === 'decisions' && parts.length === 2) return { kind: 'decision' as const, publicId: decodeURIComponent(parts[1]) }
    if (parts[0] === 'decisions' && parts.length === 3) return { kind: 'decision' as const, legacy: [decodeURIComponent(parts[1]), decodeURIComponent(parts[2])] as [string, string] }
  } catch { /* Malformed percent encoding is an invalid browser URL. */ }
  return { kind: 'unknown' as const }
}

export default function App() {
  const href = useLocation()
  const current = route(href)
  const dashboard = useRef(current.kind === 'dashboard' ? href : '/?scope=' + (new URLSearchParams(location.search).get('scope') === 'paper' ? 'paper' : 'live'))
  const previousPath = useRef(location.pathname)
  const [visited, setVisited] = useState(current.kind === 'dashboard')
  const params = new URLSearchParams(current.kind === 'dashboard' ? current.search : location.search)
  const scope: Scope = params.get('scope') === 'paper' ? 'paper' : 'live'
  const invalid = (params.has('scope') && !['live', 'paper'].includes(params.get('scope')!)) || (params.has('tab') && !['feed', 'positions', 'policies'].includes(params.get('tab')!)) || (params.has('range') && !['1M', '3M', 'YTD', 'All'].includes(params.get('range')!))
  if (current.kind === 'dashboard' && !invalid) dashboard.current = href
  useEffect(() => {
    if (current.kind === 'dashboard') setVisited(true)
    if (previousPath.current !== location.pathname) {
      previousPath.current = location.pathname
      const frame = requestAnimationFrame(() => {
        document.querySelector<HTMLElement>('#main > div:not([hidden]) h1')?.focus({ preventScroll: true })
        window.scrollTo(0, history.state?.scrollY ?? 0)
      })
      return () => cancelAnimationFrame(frame)
    }
  }, [href, current.kind])
  return <><a className="skip-link" href="#main">Skip to content</a><nav className="page-nav" aria-label="Main navigation"><Link href={dashboard.current} aria-current={current.kind === 'dashboard' ? 'page' : undefined}>Agent dashboard</Link></nav><main id="main" tabIndex={-1}>
    {(visited || current.kind === 'dashboard') && <div hidden={current.kind !== 'dashboard' || invalid}><DashboardPage search={new URL(dashboard.current, location.origin).search} /></div>}
    {current.kind === 'decision' && !invalid && <div><Section key={href} name="decision trace"><DecisionPage publicId={current.publicId} legacy={current.legacy} scope={scope} back={dashboard.current} /></Section></div>}
    {(current.kind === 'unknown' || invalid) && <div className="request-state" role="alert"><h1 tabIndex={-1}>{invalid ? 'This dashboard link is invalid' : 'Page not found'}</h1><p>{invalid ? 'The portfolio, section or performance range is not recognized.' : "This page isn't part of the public dashboard."}</p><Link href="/">Open agent dashboard</Link></div>}
  </main></>
}
