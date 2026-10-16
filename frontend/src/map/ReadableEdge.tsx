// Bezier relationship edge with an offset label so parallel edges stay readable.
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react'

export function ReadableEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, label, data }: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const labelOffset = typeof data?.labelOffset === 'number' ? data.labelOffset : 0
  const horizontalLabelOffset = Math.abs(sourceY - targetY) < 24 ? -60 : 0
  return <>
    <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} style={style} />
    {label && <EdgeLabelRenderer><div className="relationship-label nodrag nopan" style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY + labelOffset + horizontalLabelOffset}px)` }}>{label}</div></EdgeLabelRenderer>}
  </>
}
