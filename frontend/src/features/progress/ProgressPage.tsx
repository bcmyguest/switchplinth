// Progress page: counts from the current graph and evidence, with links to Facts and the system map.
import { ArrowRight } from 'lucide-react'
import type { Page } from '../../app/navigation'
import type { GraphData } from '../../types'
import { currentSourceCount } from '../evidence/evidence'

type ProgressPageProps = {
  graph: GraphData
  live: boolean
  pendingCount: number
  navigateTo: (page: Page) => void
}

export function ProgressPage({ graph, live, pendingCount, navigateTo }: ProgressPageProps) {
  return <section className="page-card"><div className="section-heading"><div><div className="section-kicker">CURRENT GRAPH</div><h2>Progress</h2></div><button className="text-button" onClick={() => navigateTo('Facts')}>Review facts <ArrowRight size={13} /></button></div><div className="progress-grid"><div><strong>{graph.entities.length}</strong><span>entities in graph</span></div><div><strong>{graph.decisions.length}</strong><span>decisions in graph</span></div><div><strong>{graph.evidence?.length ?? 0}</strong><span>evidence records</span></div><div><strong>{pendingCount}</strong><span>items needing review</span></div></div><p className="progress-note">{live ? `${currentSourceCount(graph.evidence)} Markdown source files represented in the current graph.` : 'Sample graph data is shown. Open a repository to see discovered progress.'}</p><button className="button subtle" onClick={() => navigateTo('Architecture')}>View system map <ArrowRight size={13} /></button></section>
}
