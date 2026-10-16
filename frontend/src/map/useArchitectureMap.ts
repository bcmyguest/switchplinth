import { useCallback, useEffect, useMemo, useState, type RefObject } from 'react'
import { Position, type Edge, type Node, type ReactFlowInstance } from '@xyflow/react'
import { computeMapLayout, mapLayoutInputFromKey, mapLayoutKey, MAP_NODE_HEIGHT, MAP_NODE_WIDTH, type MapDirection, type MapLayout, type MapLayoutInput } from './layout'
import type { OrthogonalEdgeData } from './OrthogonalEdge'

const MAP_GROUP_NODE_TYPE = 'mapGroup'
// Node titles (21 graph px) and captions (19 graph px) reach 12px and 11px on screen at this zoom.
// Fit never zooms out further; the minimap and pan/zoom controls reach the rest of a large map.
const MIN_READABLE_FIT_ZOOM = 0.6
const MOBILE_BREAKPOINT = 640
const MINIMAP_BREAKPOINT = 1024
const SIDEBAR_AND_PADDING = 288
const MINIMAP_RAIL = 232
const MOBILE_PADDING = 32
const CANVAS_MIN_HEIGHT = 380
const CANVAS_MAX_HEIGHT = 820
const CANVAS_VERTICAL_PADDING = 48
const DIMMED_OPACITY = 0.25
const TOP_ALIGN_MARGIN = 16
export const MAP_FIT_VIEW_OPTIONS = { padding: 0.06, minZoom: MIN_READABLE_FIT_ZOOM }
const EDGE_STROKE = 1.75
const EDGE_HIGHLIGHT_STROKE = 2.5

type UseArchitectureMapOptions = {
  graph: MapLayoutInput
  baseNodes: Node[]
  baseEdges: Edge[]
  selectedId: string | null
  viewportWidth: number
  flowInstanceRef: RefObject<ReactFlowInstance | null>
}

export function isMapGroupNode(node: Node): boolean {
  return node.type === MAP_GROUP_NODE_TYPE
}

// Fit the map; when the readable-zoom floor stops the fit short, show the top of the map instead of its middle.
export async function fitMapViewport(flow: ReactFlowInstance | null | undefined, options: { padding: number; minZoom: number }): Promise<void> {
  if (!flow) return
  await flow.fitView({ ...options, duration: 0 })
  const viewport = flow.getViewport()
  if (viewport.zoom > options.minZoom + 0.001) return
  const bounds = flow.getNodesBounds(flow.getNodes())
  await flow.setViewport({ x: viewport.x, y: TOP_ALIGN_MARGIN - bounds.y * viewport.zoom, zoom: viewport.zoom }, { duration: 0 })
}

export function useArchitectureMap({ graph, baseNodes, baseEdges, selectedId, viewportWidth, flowInstanceRef }: UseArchitectureMapOptions) {
  const direction: MapDirection = 'DOWN'
  const mobile = viewportWidth <= MOBILE_BREAKPOINT
  const fitViewOptions = MAP_FIT_VIEW_OPTIONS
  // Layout and refit run only when the structural key changes, so a refetch of the same graph keeps pan/zoom.
  const key = useMemo(() => mapLayoutKey({
    entities: graph.entities.map((entity) => ({ id: entity.id, kind: entity.kind })),
    relationships: graph.relationships.map((relation) => ({ id: relation.id, from: relation.from, to: relation.to, kind: relation.kind })),
  }, direction), [graph, direction])
  const structure = useMemo(() => mapLayoutInputFromKey(key), [key])
  const [layout, setLayout] = useState<MapLayout | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    computeMapLayout(structure.input, structure.direction).then((result) => { if (!cancelled) setLayout(result) }).catch(() => { if (!cancelled) setLayout(null) })
    return () => { cancelled = true }
  }, [structure])

  const current = layout?.key === key ? layout : null

  useEffect(() => {
    if (!current) return
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => { void fitMapViewport(flowInstanceRef.current, fitViewOptions) })
    })
    return () => cancelAnimationFrame(frame)
  }, [current, fitViewOptions, flowInstanceRef])

  const focusId = hoveredId ?? selectedId
  const neighborhood = useMemo(() => {
    if (!focusId || !baseNodes.some((node) => node.id === focusId)) return null
    const nodeIds = new Set([focusId])
    const edgeIds = new Set<string>()
    for (const edge of baseEdges) if (edge.source === focusId || edge.target === focusId) { edgeIds.add(edge.id); nodeIds.add(edge.source); nodeIds.add(edge.target) }
    return { focusId, nodeIds, edgeIds }
  }, [focusId, baseNodes, baseEdges])

  const nodes = useMemo<Node[]>(() => {
    const stateClass = (id: string) => !neighborhood ? '' : id === neighborhood.focusId ? 'map-node-focus' : neighborhood.nodeIds.has(id) ? 'map-node-neighbor' : 'map-node-dimmed'
    if (!current) return baseNodes.map((node) => ({ ...node, className: stateClass(node.id) }))
    const groupById = new Map(current.groups.map((group) => [group.id, group]))
    const groupNodes: Node[] = current.groups.map((group) => ({
      id: group.id,
      type: MAP_GROUP_NODE_TYPE,
      position: { x: group.x, y: group.y },
      width: group.width,
      height: group.height,
      style: { width: group.width, height: group.height },
      data: { label: group.label, count: group.count },
      draggable: false,
      selectable: false,
      focusable: false,
      connectable: false,
      deletable: false,
    }))
    const entityNodes = baseNodes.map((node) => {
      const rect = current.nodes.get(node.id)
      const group = groupById.get(current.nodeGroup.get(node.id) ?? '')
      if (!rect || !group) return { ...node, className: stateClass(node.id) }
      return {
        ...node,
        parentId: group.id,
        position: { x: rect.x - group.x, y: rect.y - group.y },
        width: MAP_NODE_WIDTH,
        height: MAP_NODE_HEIGHT,
        className: stateClass(node.id),
        data: { ...node.data, targetPosition: Position.Top, sourcePosition: Position.Bottom },
      }
    })
    return [...groupNodes, ...entityNodes]
  }, [baseNodes, current, neighborhood])

  const edges = useMemo<Edge[]>(() => baseEdges.map((edge) => {
    const inferred = Boolean(edge.animated)
    const highlighted = Boolean(neighborhood?.edgeIds.has(edge.id))
    const dimmed = Boolean(neighborhood) && !highlighted
    const color = inferred ? 'var(--theme-warning)' : highlighted ? 'var(--theme-brand)' : 'var(--theme-muted)'
    const sourceRect = current?.nodes.get(edge.source)
    const targetRect = current?.nodes.get(edge.target)
    const data: OrthogonalEdgeData = {
      layout: current?.edges.get(edge.id),
      anchors: sourceRect && targetRect ? { source: { x: sourceRect.x, y: sourceRect.y }, target: { x: targetRect.x, y: targetRect.y } } : undefined,
      highlighted,
      dimmed,
    }
    return {
      ...edge,
      type: 'orthogonal',
      data,
      className: highlighted ? 'map-edge-highlighted' : dimmed ? 'map-edge-dimmed' : '',
      zIndex: highlighted ? 1 : 0,
      style: { stroke: color, strokeWidth: highlighted ? EDGE_HIGHLIGHT_STROKE : EDGE_STROKE, opacity: dimmed ? DIMMED_OPACITY : 1, strokeDasharray: inferred ? '6 4' : undefined },
      markerEnd: { type: 'arrowclosed' as const, color, width: 12, height: 12 },
      labelStyle: undefined,
      labelBgStyle: undefined,
    }
  }), [baseEdges, current, neighborhood])

  const canvasHeight = useMemo(() => {
    if (!current) return Math.max(CANVAS_MIN_HEIGHT, Math.ceil(baseNodes.length / 3) * 150 + 160)
    const availableWidth = mobile ? viewportWidth - MOBILE_PADDING : viewportWidth - SIDEBAR_AND_PADDING - (viewportWidth > MINIMAP_BREAKPOINT ? MINIMAP_RAIL : 0)
    const zoom = Math.min(1, Math.max(fitViewOptions.minZoom, availableWidth / Math.max(current.width, 1)))
    return Math.round(Math.min(CANVAS_MAX_HEIGHT, Math.max(CANVAS_MIN_HEIGHT, current.height * zoom + CANVAS_VERTICAL_PADDING)))
  }, [current, baseNodes.length, mobile, viewportWidth, fitViewOptions.minZoom])

  const onNodeMouseEnter = useCallback((_: unknown, node: Node) => { if (!isMapGroupNode(node)) setHoveredId(node.id) }, [])
  const onNodeMouseLeave = useCallback(() => setHoveredId(null), [])

  return { nodes, edges, canvasHeight, fitViewOptions, layoutReady: Boolean(current), onNodeMouseEnter, onNodeMouseLeave }
}
