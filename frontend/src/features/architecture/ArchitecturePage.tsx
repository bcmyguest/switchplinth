// Architecture page: the overlay backdrop, component details, the map summary and heading with the What-if action, the
// first-use guide, the system map with the option editor overlay, and the map editing controls. It stays mounted and is
// hidden with `display: none` on other pages so the map keeps its viewport and the overlays keep their state.
import { useMemo } from 'react'
import { ArrowRight, GitPullRequest } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { mapGraphWithConfirmedIdentityGroups } from '../../map/projection'
import type { AppTheme } from '../../theme-preference'
import type { GraphData } from '../../types'
import type { ScanState } from '../discovery/scanState'
import { currentSourceCount } from '../evidence/evidence'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import type { FactsReview } from '../facts/useFactsReview'
import { DeltaEditorOverlay } from '../graph-editor/DeltaEditorOverlay'
import type { DeltaEditor } from '../graph-editor/useDeltaEditor'
import type { ScenarioSelection } from '../scenarios/useScenarioSelection'
import { ArchitectureMapCanvas } from './ArchitectureMapCanvas'
import { ComponentDetailOverlay } from './ComponentDetailOverlay'
import { MapActions } from './MapActions'
import type { ArchitecturePanels } from './useArchitecturePanels'
import type { ComponentDetailController } from './useComponentDetail'

/** First-use guide action: full width on mobile, a fixed 340px truncating column on wide screens. */
const START_ACTION = 'flex-none justify-center rounded-[6px] bg-(--theme-panel-raised) px-[12px] py-0 text-center text-(length:--type-control) font-[650] max-sm:w-full min-[1025px]:min-w-0 min-[1025px]:flex-[0_0_340px] min-[1025px]:justify-between min-[1025px]:overflow-hidden min-[1025px]:text-ellipsis min-[1025px]:whitespace-nowrap'

type ArchitecturePageProps = {
  active: boolean
  panels: ArchitecturePanels
  graph: GraphData
  live: boolean
  theme: AppTheme
  editor: DeltaEditor
  detail: ComponentDetailController
  scenario: ScenarioSelection
  facts: FactsReview
  evidence: EvidenceViewer
  pendingCount: number
  scanState: ScanState
  onDiscover: () => void
}

export function ArchitecturePage({ active, panels, graph, live, theme, editor, detail, scenario, facts, evidence, pendingCount, scanState, onDiscover }: ArchitecturePageProps) {
  const { panel: architecturePanel, setPanel: setArchitecturePanel, panelRef: architecturePanelRef, selectCanvasEntity } = panels
  const { selected, selectedId: selectedEntity, visibleSelectedEntityId } = detail
  const visibleGraph = editor.preview?.graph ?? graph
  const mapGraph = useMemo(() => mapGraphWithConfirmedIdentityGroups(visibleGraph), [visibleGraph])
  const nodeCount = mapGraph.entities.length

  return <div className={`architecture-layout${architecturePanel ? ` panel-${architecturePanel}` : ''}`} style={{ display: active ? undefined : 'none' }}>

    {architecturePanel && <Button type="button" variant="ghost" className="architecture-overlay-backdrop" aria-label={`Close ${architecturePanel === 'detail' ? 'component details' : architecturePanel === 'scenario' ? 'What-if' : 'option editor'}`} onClick={panels.close} />}

    <ComponentDetailOverlay panelOpen={architecturePanel === 'detail'} panelRef={architecturePanelRef} onClose={() => setArchitecturePanel(null)} onOpenScenario={() => setArchitecturePanel('scenario')} detail={detail} graph={graph} live={live} scenario={scenario} facts={facts} onOpenEvidence={evidence.open} onExploreDecision={panels.exploreDecision} scanState={scanState} />

    <div className="map-overview-line" aria-label="Map summary"><span><strong>{nodeCount}</strong> components</span><span><strong>{graph.decisions.length}</strong> {graph.decisions.length === 1 ? 'decision' : 'decisions'}</span><span><strong>{pendingCount}</strong> to review</span><span><strong>{live ? currentSourceCount(graph.evidence) : 'Sample'}</strong> {live ? 'Markdown sources' : 'data'}</span></div>

    <div className="section-heading graph-heading"><div><div className="section-kicker">{live ? 'REPOSITORY MODEL' : 'DEMO MODEL'} <span className="live-dot" /></div><h2>System map</h2></div><div className="graph-tools"><div className="legend"><span><i className="legend-solid" /> confirmed</span><span><i className="legend-dashed" /> inferred</span></div><Button variant="subtle" size="tiny" className="text-(length:--type-control) max-sm:flex-1 max-sm:justify-center max-sm:px-[6px]" onClick={(event) => panels.openScenario(event.currentTarget)}><GitPullRequest size={14} /> What-if</Button></div></div>
    <section className="map-start-guide" aria-label="How to read the system map">
      <div><strong>Start with a component</strong><p>Each card is a system component. Solid links are confirmed; dashed links are inferred. Select a card to see why it appears and open its source passage.</p></div>
      {selected ? <Button type="button" variant="choice" className={START_ACTION} onClick={() => selectCanvasEntity(selected.id)}>Inspect {selected.name}<ArrowRight size={14} /></Button> : <Button type="button" variant="choice" className={START_ACTION} onClick={onDiscover}>Discover decisions<ArrowRight size={14} /></Button>}
    </section>

    <ArchitectureMapCanvas graph={graph} mapGraph={mapGraph} live={live} theme={theme} selectedEntity={selectedEntity} highlightedEntityId={architecturePanel === 'detail' ? visibleSelectedEntityId : null} active={active} overlayOpen={Boolean(architecturePanel) || evidence.isOpen} editor={editor} onSelectEntity={selectCanvasEntity} onOpenEvidence={evidence.open}>
      {editor.isOpen && architecturePanel === 'editor' && <DeltaEditorOverlay editor={editor} graph={graph} panelRef={architecturePanelRef} />}
    </ArchitectureMapCanvas>
    <MapActions editor={editor} graph={graph} live={live} selectedEntity={selectedEntity} />

  </div>
}
