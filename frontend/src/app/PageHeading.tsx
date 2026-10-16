// Page heading (focus target after navigation) with the review and Discover actions, plus the related-page links.
import type { RefObject } from 'react'
import { AlertTriangle, ArrowRight, Check, LoaderCircle, Sparkles } from 'lucide-react'
import type { ScanState } from '../features/discovery/scanState'
import type { Page } from './navigation'

type PageHeadingProps = {
  activeNav: Page
  navigateTo: (page: Page) => void
  headingRef: RefObject<HTMLDivElement | null>
  live: boolean
  pendingCount: number
  scanState: ScanState
  onDiscover: () => void
}

export function PageHeading({ activeNav, navigateTo, headingRef: pageHeadingRef, live, pendingCount, scanState, onDiscover: beginDiscover }: PageHeadingProps) {
  return <>
  <div className="page-heading" ref={pageHeadingRef} tabIndex={-1}><div><div className="eyebrow"><span className="eyebrow-dot" /> {live ? 'YOUR SYSTEM, AS UNDERSTOOD' : 'INTERACTIVE SAMPLE · NOT CONNECTED TO REPOSITORY'}</div><h1>{activeNav}</h1><p>{activeNav === 'Architecture' ? 'The system map and the decisions that shape it.' : activeNav === 'Architecture log' ? 'Decisions recorded across your repository.' : activeNav === 'Progress' ? 'Discovery and review progress from the current graph.' : activeNav === 'Facts' ? 'Claims and aliases that need a closer look.' : activeNav === 'Scenarios' ? 'Explore how decisions change the architecture.' : 'Ask grounded questions about this architecture.'}</p></div><div className="heading-actions"><button className="button subtle" onClick={() => navigateTo('Facts')}>Needs a closer look · {pendingCount}</button><button className="button primary" onClick={beginDiscover} disabled={scanState === 'scanning'}>{scanState === 'scanning' ? <LoaderCircle className="spin" size={15} /> : scanState === 'done' ? <Check size={15} /> : scanState === 'error' || scanState === 'refresh-error' ? <AlertTriangle size={15} /> : <Sparkles size={15} />}{scanState === 'scanning' ? 'Discovering…' : scanState === 'done' ? 'Discover complete' : scanState === 'error' ? 'Discovery failed' : scanState === 'refresh-error' ? 'Refresh failed' : 'Discover decisions'}</button></div></div>
  {['Architecture log', 'Progress', 'Facts'].includes(activeNav) && <nav className="page-links page-context-links" aria-label="Related architecture pages"><button onClick={() => navigateTo('Architecture log')}>Architecture log</button><button onClick={() => navigateTo('Progress')}>Progress</button><button onClick={() => navigateTo('Facts')}>Facts</button><button onClick={() => navigateTo('Architecture')}>System map <ArrowRight size={12} /></button></nav>}
  {activeNav === 'Scenarios' && <nav className="page-links page-context-links" aria-label="Scenario navigation"><span>Option changes update the selected component rationale below.</span><button onClick={() => navigateTo('Architecture')}>View system map <ArrowRight size={12} /></button></nav>}
  </>
}
