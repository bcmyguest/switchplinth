import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, useInternalNode, useStore, type EdgeProps, type ReactFlowState } from '@xyflow/react'
import { MAP_LABEL_MIN_ZOOM } from './layout'
import type { MapEdgeLayout } from './layout'

const CORNER_RADIUS = 8
const ANCHOR_TOLERANCE = 1

export type OrthogonalEdgeData = {
  layout?: MapEdgeLayout
  anchors?: { source: { x: number; y: number }; target: { x: number; y: number } }
  highlighted?: boolean
  dimmed?: boolean
}

function zoomSelector(state: ReactFlowState): number {
  return Math.floor(state.transform[2] * 40) / 40
}

function roundedPolyline(points: Array<{ x: number; y: number }>): string {
  if (points.length < 2) return ''
  let path = `M ${points[0].x} ${points[0].y}`
  for (let index = 1; index < points.length - 1; index += 1) {
    const previous = points[index - 1]
    const corner = points[index]
    const next = points[index + 1]
    const inLength = Math.hypot(corner.x - previous.x, corner.y - previous.y)
    const outLength = Math.hypot(next.x - corner.x, next.y - corner.y)
    const radius = Math.min(CORNER_RADIUS, inLength / 2, outLength / 2)
    if (radius <= 0) { path += ` L ${corner.x} ${corner.y}`; continue }
    const start = { x: corner.x - ((corner.x - previous.x) / inLength) * radius, y: corner.y - ((corner.y - previous.y) / inLength) * radius }
    const end = { x: corner.x + ((next.x - corner.x) / outLength) * radius, y: corner.y + ((next.y - corner.y) / outLength) * radius }
    path += ` L ${start.x} ${start.y} Q ${corner.x} ${corner.y} ${end.x} ${end.y}`
  }
  const last = points[points.length - 1]
  return `${path} L ${last.x} ${last.y}`
}

function longestSegmentMidpoint(points: Array<{ x: number; y: number }>): { x: number; y: number } {
  let best = { x: points[0]?.x ?? 0, y: points[0]?.y ?? 0 }
  let bestLength = -1
  for (let index = 1; index < points.length; index += 1) {
    const length = Math.hypot(points[index].x - points[index - 1].x, points[index].y - points[index - 1].y)
    if (length > bestLength) { bestLength = length; best = { x: (points[index].x + points[index - 1].x) / 2, y: (points[index].y + points[index - 1].y) / 2 } }
  }
  return best
}

function near(position: { x: number; y: number } | undefined, expected: { x: number; y: number } | undefined): boolean {
  return Boolean(position && expected && Math.abs(position.x - expected.x) <= ANCHOR_TOLERANCE && Math.abs(position.y - expected.y) <= ANCHOR_TOLERANCE)
}

export function OrthogonalEdge({ id, source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, label, data }: EdgeProps) {
  const sourceNode = useInternalNode(source)
  const targetNode = useInternalNode(target)
  const zoom = useStore(zoomSelector)
  const edgeData = (data ?? {}) as OrthogonalEdgeData
  const layout = edgeData.layout
  // ELK bend points stay valid only while both endpoints sit where the layout put them.
  const intact = Boolean(layout && near(sourceNode?.internals.positionAbsolute, edgeData.anchors?.source) && near(targetNode?.internals.positionAbsolute, edgeData.anchors?.target))
  let path: string
  let labelX: number
  let labelY: number
  if (intact && layout) {
    path = roundedPolyline(layout.points)
    const center = layout.label ? { x: layout.label.x + layout.label.width / 2, y: layout.label.y + layout.label.height / 2 } : longestSegmentMidpoint(layout.points)
    labelX = center.x
    labelY = center.y
  } else {
    [path, labelX, labelY] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: CORNER_RADIUS })
  }
  const showLabel = Boolean(label) && (edgeData.highlighted || zoom >= MAP_LABEL_MIN_ZOOM)
  const labelState = edgeData.highlighted ? ' is-highlighted' : edgeData.dimmed ? ' is-dimmed' : ''
  return <>
    <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} interactionWidth={18} />
    {showLabel && <EdgeLabelRenderer><div className={`relationship-label map-edge-label nodrag nopan${labelState}`} data-edge-id={id} style={{ transform: `translate(${labelX}px, ${labelY}px) translate(-50%, -50%) scale(${1 / Math.max(zoom, 0.05)})` }}>{label}</div></EdgeLabelRenderer>}
  </>
}
