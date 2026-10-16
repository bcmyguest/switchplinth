export type MapGroupNodeData = { label: string; count: number }

export function GroupNode({ data }: { data: MapGroupNodeData }) {
  return <div className="map-group" aria-hidden="true">
    <span className="map-group-label">{data.label}<small>{data.count}</small></span>
  </div>
}
