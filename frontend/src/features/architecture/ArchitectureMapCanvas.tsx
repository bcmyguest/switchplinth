// System map frame: the breadcrumb with the evidence-source filter and the full-screen toggle, the ReactFlow canvas with its
// width-change refit, the minimap rail on wide viewports, and the footer. `children` renders inside the frame after the
// canvas (the option editor overlay). The frame stays mounted while other pages show, so ReactFlow never remounts.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Background, BackgroundVariant, Controls, MiniMap, ReactFlow, ReactFlowProvider, type Edge, type ReactFlowInstance } from '@xyflow/react'
import { ArrowRight, GitCommitHorizontal, Maximize2, Minimize2 } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { Select } from '../../components/ui/select'
import { EDGE_TYPES, NODE_TYPES } from '../../map/flowTypes'
import { entityEdges, entityNodes } from '../../map/projection'
import { fitMapViewport, isMapGroupNode, MAP_FIT_VIEW_OPTIONS, useArchitectureMap } from '../../map/useArchitectureMap'
import { useMapFullscreen } from '../../map/useMapFullscreen'
import type { AppTheme } from '../../theme-preference'
import type { Evidence, GraphData } from '../../types'
import { currentSourceCount, evidenceHeading, evidencePath, resolveEvidence } from '../evidence/evidence'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import type { DeltaEditor } from '../graph-editor/useDeltaEditor'

const INITIAL_EDGES: Edge[] = []

type ArchitectureMapCanvasProps = {
  /** The repository graph: source-filter choices and the footer source count. */
  graph: GraphData
  /** The projected graph the map draws (preview graph with confirmed identity groups combined). */
  mapGraph: GraphData
  live: boolean
  theme: AppTheme
  /** The requested entity ID: minimap highlight and the opener for canvas edits. */
  selectedEntity: string
  /** The entity the map highlights while component details are open; null otherwise. */
  highlightedEntityId: string | null
  /** True while the Architecture page shows; leaving it exits full screen. */
  active: boolean
  /** True while an Architecture overlay or the source dialog is open; Escape then closes it before leaving full screen. */
  overlayOpen: boolean
  editor: Pick<DeltaEditor, 'connect' | 'deleteEdges'>
  onSelectEntity: (entityId: string) => void
  onOpenEvidence: EvidenceViewer['open']
  children?: ReactNode
}

export function ArchitectureMapCanvas({ graph, mapGraph, live, theme, selectedEntity, highlightedEntityId, active, overlayOpen, editor, onSelectEntity, onOpenEvidence, children }: ArchitectureMapCanvasProps) {
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth)
  const graphCanvasRef = useRef<HTMLDivElement | null>(null)
  const flowInstanceRef = useRef<ReactFlowInstance | null>(null)

  useEffect(() => {
    const updateViewportWidth = () => setViewportWidth(window.innerWidth)
    window.addEventListener('resize', updateViewportWidth)
    return () => window.removeEventListener('resize', updateViewportWidth)
  }, [])

  useEffect(() => {
    const canvas = graphCanvasRef.current
    if (!canvas) return
    let previousWidth = 0
    let fitFrame = 0
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width
      if (previousWidth > 0 && width > 0 && Math.abs(width - previousWidth) > 1) {
        const flow = flowInstanceRef.current
        if (flow?.viewportInitialized) {
          cancelAnimationFrame(fitFrame)
          fitFrame = requestAnimationFrame(() => {
            fitFrame = requestAnimationFrame(() => {
              if (flowInstanceRef.current === flow && flow.viewportInitialized) void fitMapViewport(flow, MAP_FIT_VIEW_OPTIONS)
            })
          })
        }
      }
      previousWidth = width
    })
    observer.observe(canvas)
    return () => {
      observer.disconnect()
      cancelAnimationFrame(fitFrame)
    }
  }, [])

  const sourceEvidenceChoices = [...new Map([
    ...(graph.evidence ?? []),
    ...graph.entities.flatMap((entity) => entity.evidence ?? []).map((reference) => resolveEvidence(reference, graph.evidence ?? [])).filter((item): item is Evidence => Boolean(item)),
    ...graph.decisions.flatMap((decision) => [
      ...(decision.evidence ?? []),
      ...decision.options.flatMap((option) => option.evidence ?? []),
    ]).map((reference) => resolveEvidence(reference, graph.evidence ?? [])).filter((item): item is Evidence => Boolean(item)),
  ].map((item) => [item.id, item])).values()]
  const sourceDocumentChoices = [...new Map(sourceEvidenceChoices.map((item) => [evidencePath(item), item])).values()]
  const graphColumns = viewportWidth <= 640 ? 1 : 3
  const nodes = useMemo(() => entityNodes(mapGraph, graphColumns), [mapGraph, graphColumns])
  const edges = useMemo(() => entityEdges(mapGraph), [mapGraph])
  const architectureMap = useArchitectureMap({ graph: mapGraph, baseNodes: nodes, baseEdges: edges, selectedId: highlightedEntityId, viewportWidth, flowInstanceRef })
  const mapFullscreen = useMapFullscreen({ active, overlayOpen, flowInstanceRef, fitViewOptions: architectureMap.fitViewOptions })

  return <div className={`graph-frame${mapFullscreen.fullscreen ? ' is-fullscreen' : ''}`}>
    <div className="graph-breadcrumb"><span>Architecture</span><ArrowRight size={12} /><span>Services & infrastructure</span><div className="graph-filter"><span className="source-dot green" /><Select aria-label="All evidence source documents" value="" onChange={(event) => {
      const source = sourceDocumentChoices.find((item) => evidencePath(item) === event.target.value)
      if (source) onOpenEvidence(source)
    }}><option value="">All evidence</option>{sourceDocumentChoices.map((item) => <option key={item.id} value={evidencePath(item)}>{evidencePath(item)} · {evidenceHeading(item)}</option>)}</Select></div><Button type="button" variant="icon" size="icon" ref={mapFullscreen.toggleRef} className="map-fullscreen-toggle ml-[8px] size-[32px] flex-none border border-(--theme-line) bg-(--theme-panel-raised) p-0 text-(--theme-ink) hover:bg-(--theme-hover) aria-pressed:border-(--theme-brand) aria-pressed:bg-(--theme-selected)" aria-pressed={mapFullscreen.fullscreen} aria-label={mapFullscreen.fullscreen ? 'Exit full-screen map' : 'Open map full screen'} title={mapFullscreen.fullscreen ? 'Exit full screen (Esc)' : 'Full screen'} onClick={mapFullscreen.toggle}>{mapFullscreen.fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}</Button></div>
    <div className="graph-canvas" ref={graphCanvasRef} style={{ height: mapFullscreen.fullscreen ? undefined : architectureMap.canvasHeight }}>
      <ReactFlowProvider>
        <div className="graph-flow-viewport" data-testid="graph-flow-viewport">
          <ReactFlow nodes={architectureMap.nodes} edges={architectureMap.edges.length ? architectureMap.edges : INITIAL_EDGES} nodeTypes={NODE_TYPES} edgeTypes={EDGE_TYPES} fitView fitViewOptions={architectureMap.fitViewOptions} minZoom={0.2} maxZoom={1.6} deleteKeyCode="Delete" onInit={(flow) => { flowInstanceRef.current = flow }} onNodeClick={(_, node) => { if (!isMapGroupNode(node)) onSelectEntity(node.id) }} onNodeMouseEnter={architectureMap.onNodeMouseEnter} onNodeMouseLeave={architectureMap.onNodeMouseLeave} onConnect={(connection) => editor.connect(connection, selectedEntity)} onEdgesDelete={(edgesToDelete) => editor.deleteEdges(edgesToDelete, selectedEntity)} proOptions={{ hideAttribution: true }}>
            <Background id="map-minor" className="map-grid-minor" variant={BackgroundVariant.Lines} gap={20} lineWidth={0.5} color="var(--theme-map-dot)" /><Background id="map-major" className="map-grid-major" variant={BackgroundVariant.Lines} gap={100} lineWidth={1} color="var(--theme-map-dot)" /><Controls showInteractive={false} position="bottom-left" />
          </ReactFlow>
        </div>
        {viewportWidth > 1024 && <aside className="graph-minimap-rail" aria-label="Architecture map overview"><span>MAP OVERVIEW</span><MiniMap data-testid="graph-minimap" className="reserved-minimap" pannable zoomable nodeColor={(node) => isMapGroupNode(node) ? 'transparent' : theme === 'dark' ? node.id === selectedEntity ? '#a6d0ae' : '#405444' : node.id === selectedEntity ? '#557b66' : '#cbd9cf'} maskColor={theme === 'dark' ? 'rgba(17,23,19,.72)' : 'rgba(243,244,241,.72)'} /></aside>}
      </ReactFlowProvider>
      <div className="selection-hint"><span className="hint-ring" /> Drag a handle to connect; select an edge and press Delete to remove it</div>
    </div>
    {children}
    <div className="graph-footer"><span><GitCommitHorizontal size={13} /> {live ? 'Compiled from repository files' : 'Sample graph · changes are not saved'}</span><span>Source: <strong>{live ? `${currentSourceCount(graph.evidence)} Markdown files` : 'synthetic sample'}</strong></span><Button type="button" variant="ghost" className="ml-auto flex items-center gap-[5px] p-0 text-(length:--type-tertiary) leading-[1.45] text-(--theme-brand) max-sm:ml-0" onClick={mapFullscreen.toggle} aria-pressed={mapFullscreen.fullscreen}>{mapFullscreen.fullscreen ? <>Exit full screen <Minimize2 size={13} /></> : <>Open full screen <Maximize2 size={13} /></>}</Button></div>
  </div>
}
