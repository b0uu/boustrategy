import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-sans/700.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/600.css'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Info } from '@phosphor-icons/react'
import { usePublic } from './api'
import { Chevron, SectionBoundary } from './common'
import { Feed } from './Feed'
import { Performance } from './Performance'
import { Positions } from './Positions'
import { Policies } from './Policies'
import { AgentStatus } from './Activity'
import { DecisionPage } from './Decision'
import { Link, dashboardUrl, navigate, useLocation } from './navigation'
import { ThemeToggle } from './theme'
import type { Overview, Performance as PerformanceData, Scope, Range } from './types'
import { when } from './format'
import avatar from './assets/agent-avatar.png'
import './styles.css'

// The public dashboard reports one live account. The paper simulation is still published
// and still reachable through the API; it is simply not a thing the reader is offered.
const SCOPE: Scope = 'live'
const TABS = ['feed', 'positions', 'policies'] as const
const ISSUES_URL = 'https://github.com/b0uu/boustrategy/issues'

function Section({ name, children }: { name: string; children: ReactNode }) {
  const [revision, setRevision] = useState(0)
  return <SectionBoundary name={name} resetKey={revision} retry={() => setRevision(n => n + 1)}><div key={revision}>{children}</div></SectionBoundary>
}

export function DashboardPage({ search }: { search: string }) {
  const params = new URLSearchParams(search)
  const range = (params.get('range') ?? '1M') as Range
  const tab = params.get('tab') ?? 'feed'
  const [feedVisited, setFeedVisited] = useState(tab === 'feed')
  useEffect(() => { if (tab === 'feed') setFeedVisited(true) }, [tab])
  const [portfolioOpen, setPortfolioOpen] = useState(true)
  const profileMeta = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    const closeProfileMeta = (event: PointerEvent) => {
      if (profileMeta.current?.open && !profileMeta.current.contains(event.target as Node)) profileMeta.current.removeAttribute('open')
    }
    document.addEventListener('pointerdown', closeProfileMeta)
    return () => document.removeEventListener('pointerdown', closeProfileMeta)
  }, [])
  const overview = usePublic<Overview>(`/api/public/v2/portfolios/${SCOPE}/overview`, 'overview')
  const performance = usePublic<PerformanceData>(`/api/public/v2/portfolios/${SCOPE}/performance?range=${range}`, 'performance')
  return <>
    <header className="profile"><div className="mark" aria-hidden="true"><img src={avatar} alt="" width={64} height={64} /></div>
      <div className="profile-copy"><h1 tabIndex={-1}>BouStrategy Agent</h1><div className="handle">@bou-agent</div><p>Let's make money chat</p>
        <button className="text-button portfolio-toggle" aria-expanded={portfolioOpen} aria-controls="portfolio-details" onClick={() => setPortfolioOpen(!portfolioOpen)}><Chevron />{portfolioOpen ? 'Hide portfolio' : 'Show portfolio'}</button>
      </div>
      <details className="profile-meta" ref={profileMeta}><summary aria-label="Agent and publication details"><Info size={17} weight="regular" /></summary><div><AgentStatus scope={SCOPE} />{overview.data?.data_as_of && <span>Portfolio as of {when(overview.data.data_as_of)}{overview.data.published_at ? ` · Published ${when(overview.data.published_at)}` : ''}</span>}<span><a href={ISSUES_URL} target="_blank" rel="noopener noreferrer">Report an issue ↗</a></span></div></details>
    </header>
    <Section name="portfolio"><Performance overview={overview} performance={performance} range={range} scope={SCOPE} search={search} open={portfolioOpen} onToggle={() => setPortfolioOpen(!portfolioOpen)} /></Section>
    <nav className="tabs" aria-label="Dashboard sections">{TABS.map(value => <button key={value} aria-pressed={tab === value} onClick={() => navigate(dashboardUrl({ tab: value }, search))}>{value}</button>)}</nav>
    {(feedVisited || tab === 'feed') && <div className="dashboard-panel" hidden={tab !== 'feed'}><Section name="decision feed"><Feed scope={SCOPE} search={search} /></Section></div>}
    {tab === 'positions' && <div className="dashboard-panel"><Section name="positions"><Positions scope={SCOPE} overview={overview.data} /></Section></div>}
    {tab === 'policies' && <div className="dashboard-panel"><Section name="policies"><Policies scope={SCOPE} /></Section></div>}
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
  const dashboard = useRef(current.kind === 'dashboard' ? href : '/')
  const previousPath = useRef(location.pathname)
  const [visited, setVisited] = useState(current.kind === 'dashboard')
  const params = new URLSearchParams(current.kind === 'dashboard' ? current.search : location.search)
  const invalid = (params.has('tab') && !TABS.includes(params.get('tab') as (typeof TABS)[number])) || (params.has('range') && !['1M', '3M', 'YTD', 'All'].includes(params.get('range')!))
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
  return <><a className="skip-link" href="#main">Skip to content</a><nav className="page-nav" aria-label="Main navigation"><Link href={dashboard.current} aria-current={current.kind === 'dashboard' ? 'page' : undefined}>Agent dashboard</Link></nav><ThemeToggle /><main id="main" tabIndex={-1}>
    {(visited || current.kind === 'dashboard') && <div hidden={current.kind !== 'dashboard' || invalid}><DashboardPage search={new URL(dashboard.current, location.origin).search} /></div>}
    {current.kind === 'decision' && !invalid && <div><Section key={href} name="decision trace"><DecisionPage publicId={current.publicId} legacy={current.legacy} scope={SCOPE} back={dashboard.current} /></Section></div>}
    {(current.kind === 'unknown' || invalid) && <div className="request-state" role="alert"><h1 tabIndex={-1}>{invalid ? 'This dashboard link is invalid' : 'Page not found'}</h1><p>{invalid ? 'The section or performance range is not recognized.' : "This page isn't part of the public dashboard."}</p><Link href="/">Open agent dashboard</Link></div>}
  </main></>
}
