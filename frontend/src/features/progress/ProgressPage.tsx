// Progress page: counts from the current graph and evidence, with links to Facts and the system map.
import { ArrowRight } from 'lucide-react'
import type { Page } from '../../app/navigation'
import { PageCard } from '../../app/PageCard'
import { Button } from '../../components/ui/button'
import type { GraphData } from '../../types'
import { currentSourceCount } from '../evidence/evidence'

type ProgressPageProps = {
  graph: GraphData
  live: boolean
  pendingCount: number
  navigateTo: (page: Page) => void
}

function Stat({ value, label }: { value: number; label: string }) {
  return <div className="flex flex-col gap-[5px] rounded-[7px] border border-(--theme-line) bg-(--theme-panel-raised) p-[13px]">
    <strong className="[font:650_20px_Manrope,sans-serif] text-(--theme-source) dark:text-(--theme-brand)">{value}</strong>
    <span className="text-[12px] leading-normal text-(--theme-muted)">{label}</span>
  </div>
}

export function ProgressPage({ graph, live, pendingCount, navigateTo }: ProgressPageProps) {
  return <PageCard>
    <div className="section-heading"><div><div className="section-kicker">CURRENT GRAPH</div><h2>Progress</h2></div><Button variant="link" onClick={() => navigateTo('Facts')}>Review facts <ArrowRight size={13} /></Button></div>
    <div className="my-[15px] grid grid-cols-4 gap-[8px] max-sm:grid-cols-2">
      <Stat value={graph.entities.length} label="entities in graph" />
      <Stat value={graph.decisions.length} label="decisions in graph" />
      <Stat value={graph.evidence?.length ?? 0} label="evidence records" />
      <Stat value={pendingCount} label="items needing review" />
    </div>
    <p className="mt-[4px] mb-[14px] text-(length:--type-secondary) leading-normal text-(--theme-muted)">{live ? `${currentSourceCount(graph.evidence)} Markdown source files represented in the current graph.` : 'Sample graph data is shown. Open a repository to see discovered progress.'}</p>
    <Button variant="outline" className="self-start" onClick={() => navigateTo('Architecture')}>View system map <ArrowRight size={13} /></Button>
  </PageCard>
}
