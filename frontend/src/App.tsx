import type { GraphData } from './types'
import { PRODUCT_NAME, PRODUCT_TAGLINE } from './brand'
import { ArchitectureLogPage } from './features/architecture-log/ArchitectureLogPage'
import { ProgressPage } from './features/progress/ProgressPage'
import { ScenarioWorkspace } from './features/scenarios/ScenarioWorkspace'
import { useHashNavigation } from './app/useHashNavigation'
import { useTheme } from './app/useTheme'
import { useWorkspace } from './app/useWorkspace'
import { useConnections } from './features/settings/useConnections'
import { ConnectionSettingsDialog } from './features/settings/ConnectionSettingsDialog'
import { useRepositorySwitch } from './features/repository/useRepositorySwitch'
import { RepositoryPickerDialog } from './features/repository/RepositoryPickerDialog'
import { Sidebar } from './app/Sidebar'
import { Topbar } from './app/Topbar'
import { PageHeading } from './app/PageHeading'
import { useDiscovery } from './features/discovery/useDiscovery'
import { DiscoverDialog } from './features/discovery/DiscoverDialog'
import { ScanSummary } from './features/discovery/ScanSummary'
import { useExplore } from './features/explore/useExplore'
import { ExplorePage } from './features/explore/ExplorePage'
import { useScenarioSelection } from './features/scenarios/useScenarioSelection'
import { useDeltaEditor } from './features/graph-editor/useDeltaEditor'
import { useEvidenceViewer } from './features/evidence/useEvidenceViewer'
import { SourceEvidenceDialog } from './features/evidence/SourceEvidenceDialog'
import { useComponentDetail } from './features/architecture/useComponentDetail'
import { useArchitecturePanelHost, useArchitecturePanels } from './features/architecture/useArchitecturePanels'
import { ArchitecturePage } from './features/architecture/ArchitecturePage'
import { useFactsReview } from './features/facts/useFactsReview'
import { FactsPage } from './features/facts/FactsPage'

function App() {
  const [theme, setTheme] = useTheme()
  const panelHost = useArchitecturePanelHost()

  const { page: activeNav, navigateTo, headingRef: pageHeadingRef } = useHashNavigation()

  const workspace = useWorkspace(handleInitialGraph)
  const { graph, live, projectName, projectRoot, refreshGraph } = workspace
  const scenario = useScenarioSelection(workspace, { onResolved: selectResolvedEntity })
  const { displayed: displayedSelection, refreshSaved: refreshSavedScenarios, jumpTo: jumpToScenarioDecision } = scenario

  function handleInitialGraph(data: GraphData, generation: number) {
    void refreshSavedScenarios(generation)
    scenario.rebase(data)
    if (data.entities[0]) setSelectedEntity(data.entities[0].id)
  }

  function selectResolvedEntity(resolvedGraph: GraphData, preferredEntityId: string | undefined) {
    setSelectedEntity((currentEntityId) => resolvedGraph.entities.some((entity) => entity.id === currentEntityId) ? currentEntityId : preferredEntityId ?? resolvedGraph.entities[0]?.id ?? currentEntityId)
  }

  const editor = useDeltaEditor(workspace, scenario, { setPanel: panelHost.setPanel, openerRef: panelHost.openerRef })
  const { preview: deltaPreview, close: closeDeltaEditor } = editor
  const facts = useFactsReview(workspace)
  const { pendingCount } = facts.queue
  const connections = useConnections(workspace)

  const componentDetail = useComponentDetail(workspace, displayedSelection, deltaPreview)
  const { select: setSelectedEntity, evidenceRecords } = componentDetail
  const evidenceViewer = useEvidenceViewer(evidenceRecords, graph.evidence)
  const { open: openEvidenceDetail, openSearchPassage } = evidenceViewer
  const panels = useArchitecturePanels(panelHost, closeDeltaEditor, setSelectedEntity, jumpToScenarioDecision)
  const { panel: architecturePanel, panelRef: architecturePanelRef, setPanel: setArchitecturePanel, exploreDecision } = panels
  const explore = useExplore(workspace, scenario, editor, connections)
  const discovery = useDiscovery(workspace, scenario, connections)
  const { scanState, begin: beginDiscover } = discovery
  const repositorySwitch = useRepositorySwitch(workspace, connections, { scenario, componentDetail, explore, editor, facts, discovery })
  const repositoryBusy = repositorySwitch.busy

  return <main className={`app-shell${activeNav === 'Scenarios' ? ' app-scenarios' : ''}`} data-theme={theme}>
    <Sidebar activeNav={activeNav} navigateTo={navigateTo} projectName={projectName} projectRoot={projectRoot} live={live} pendingCount={pendingCount} scanState={scanState} scanSummary={discovery.summary} onOpenRepository={repositorySwitch.open} onOpenSettings={connections.openSettings} onDiscover={beginDiscover} />

    <section className="main-column">
      <Topbar projectName={projectName} activeNav={activeNav} live={live} theme={theme} onToggleTheme={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')} activeConnection={connections.active} onOpenSettings={connections.openSettings} />

      <div className="content-scroll">
        <PageHeading activeNav={activeNav} navigateTo={navigateTo} headingRef={pageHeadingRef} live={live} pendingCount={pendingCount} scanState={scanState} onDiscover={beginDiscover} />
        <ScanSummary discovery={discovery} />

        {activeNav === 'Explore' && <ExplorePage explore={explore} graph={graph} live={live} displayedSelection={displayedSelection} editor={editor} onOpenSearchPassage={openSearchPassage} />}

        {activeNav === 'Architecture log' && <ArchitectureLogPage graph={graph} scenario={scenario} evidenceRecords={evidenceRecords} evidence={evidenceViewer} scanState={scanState} onExploreDecision={(decisionId) => { navigateTo('Architecture'); exploreDecision(decisionId) }} navigateTo={navigateTo} />}

        {activeNav === 'Progress' && <ProgressPage graph={graph} live={live} pendingCount={pendingCount} navigateTo={navigateTo} />}

        <ArchitecturePage active={activeNav === 'Architecture'} panels={panels} graph={graph} live={live} theme={theme} editor={editor} detail={componentDetail} scenario={scenario} facts={facts} evidence={evidenceViewer} pendingCount={pendingCount} scanState={scanState} onDiscover={beginDiscover} />

        <ScenarioWorkspace mode={activeNav === 'Scenarios' ? 'page' : architecturePanel === 'scenario' && activeNav === 'Architecture' ? 'overlay' : 'hidden'} panelOpen={architecturePanel === 'scenario'} panelRef={architecturePanelRef} onClosePanel={() => setArchitecturePanel(null)} graph={graph} live={live} projectRoot={projectRoot} catalog={workspace.catalog} scenario={scenario} evidenceRecords={evidenceRecords} onOpenEvidence={openEvidenceDetail} repositoryBusy={repositoryBusy} scanState={scanState} />

        <FactsPage active={activeNav === 'Facts'} graph={graph} live={live} facts={facts} evidenceRecords={evidenceRecords} onOpenEvidence={openEvidenceDetail} onReviewLogChanged={refreshGraph} navigateTo={navigateTo} />

        <footer className="page-footer"><span>{PRODUCT_NAME} <i>·</i> {PRODUCT_TAGLINE}</span><span>Data stays in your repository</span></footer>
      </div>
    </section>

    <DiscoverDialog discovery={discovery} connections={connections} />

    <RepositoryPickerDialog picker={repositorySwitch.dialog} projectName={projectName} projectRoot={projectRoot} />

    <ConnectionSettingsDialog connections={connections} live={live} />
    <SourceEvidenceDialog viewer={evidenceViewer} />
  </main>
}

export default App
