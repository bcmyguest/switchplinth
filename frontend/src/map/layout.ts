import type { ELK as ElkEngine, ElkExtendedEdge, ElkNode, ElkPoint } from 'elkjs/lib/elk-api'

export const MAP_NODE_WIDTH = 232
export const MAP_NODE_HEIGHT = 112
const MAP_GROUP_PADDING = { top: 44, side: 20, bottom: 20 }
// Edge labels render at a constant 11px (DM Mono, uppercase) on screen. Reserve room for them down to MAP_LABEL_MIN_ZOOM.
export const MAP_LABEL_MIN_ZOOM = 0.5
const EDGE_LABEL_SCREEN_HEIGHT = 20
const EDGE_LABEL_SCREEN_CHAR_WIDTH = 7.6
const EDGE_LABEL_SCREEN_PADDING = 14

// Kind lanes. Grouping uses the entity kind already present in the projection; it never merges records.
const MAP_GROUPS = [
  { id: 'map-group-services', label: 'Services & workflows', kinds: ['service', 'worker', 'workflow', 'interface'] },
  { id: 'map-group-data', label: 'Data & resources', kinds: ['resource', 'datastore', 'queue'] },
  { id: 'map-group-platform', label: 'Technology & platform', kinds: ['technology', 'platform', 'runtime'] },
] as const
const OTHER_GROUP = { id: 'map-group-other', label: 'Other components', kinds: [] as string[] }

const ROOT_OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  'elk.edgeRouting': 'ORTHOGONAL',
  'elk.layered.spacing.nodeNodeBetweenLayers': '36',
  'elk.layered.spacing.edgeNodeBetweenLayers': '20',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '10',
  'elk.spacing.nodeNode': '24',
  'elk.spacing.edgeNode': '16',
  'elk.spacing.edgeEdge': '10',
  'elk.spacing.edgeLabel': '6',
  'elk.spacing.componentComponent': '48',
  'elk.edgeLabels.placement': 'CENTER',
  'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
  'elk.layered.nodePlacement.strategy': 'SIMPLE',
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  'elk.json.edgeCoords': 'ROOT',
}

export type MapDirection = 'RIGHT' | 'DOWN'
export type MapLayoutInput = {
  entities: Array<{ id: string; kind: string }>
  relationships: Array<{ id: string; from: string; to: string; kind: string }>
}
type MapRect = { x: number; y: number; width: number; height: number }
type MapGroupLayout = MapRect & { id: string; label: string; count: number }
export type MapEdgeLayout = { points: ElkPoint[]; label?: MapRect }
export type MapLayout = {
  key: string
  direction: MapDirection
  width: number
  height: number
  groups: MapGroupLayout[]
  nodeGroup: Map<string, string>
  nodes: Map<string, MapRect>
  edges: Map<string, MapEdgeLayout>
}

let elkEngine: Promise<ElkEngine> | null = null

// ELK is about 1.5 MB; load it on first layout so it stays out of the entry chunk.
function loadElk(): Promise<ElkEngine> {
  elkEngine ??= import('elkjs/lib/elk.bundled.js').then(({ default: ELK }) => new ELK())
  return elkEngine
}

function mapGroupForKind(kind: string): { id: string; label: string } {
  return MAP_GROUPS.find((group) => (group.kinds as readonly string[]).includes(kind)) ?? OTHER_GROUP
}

function edgeLabelText(kind: string): string {
  return kind.replaceAll('_', ' ')
}

export function mapLayoutKey(input: MapLayoutInput, direction: MapDirection): string {
  return JSON.stringify([direction, input.entities.map((entity) => [entity.id, entity.kind]), input.relationships.map((relation) => [relation.id, relation.from, relation.to, relation.kind])])
}

export function mapLayoutInputFromKey(key: string): { input: MapLayoutInput; direction: MapDirection } {
  const [direction, entities, relationships] = JSON.parse(key) as [MapDirection, Array<[string, string]>, Array<[string, string, string, string]>]
  return {
    direction,
    input: {
      entities: entities.map(([id, kind]) => ({ id, kind })),
      relationships: relationships.map(([id, from, to, kind]) => ({ id, from, to, kind })),
    },
  }
}

export async function computeMapLayout(input: MapLayoutInput, direction: MapDirection): Promise<MapLayout> {
  const entityIds = new Set(input.entities.map((entity) => entity.id))
  const groups = new Map<string, { id: string; label: string; children: ElkNode[] }>()
  const nodeGroup = new Map<string, string>()
  const targetSide = direction === 'RIGHT' ? 'WEST' : 'NORTH'
  const sourceSide = direction === 'RIGHT' ? 'EAST' : 'SOUTH'
  for (const entity of input.entities) {
    const group = mapGroupForKind(entity.kind)
    if (!groups.has(group.id)) groups.set(group.id, { id: group.id, label: group.label, children: [] })
    groups.get(group.id)?.children.push({
      id: entity.id,
      width: MAP_NODE_WIDTH,
      height: MAP_NODE_HEIGHT,
      layoutOptions: { 'elk.portConstraints': 'FIXED_SIDE' },
      ports: [
        { id: `${entity.id}::in`, width: 1, height: 1, layoutOptions: { 'elk.port.side': targetSide } },
        { id: `${entity.id}::out`, width: 1, height: 1, layoutOptions: { 'elk.port.side': sourceSide } },
      ],
    })
    nodeGroup.set(entity.id, group.id)
  }
  const edges: ElkExtendedEdge[] = input.relationships.filter((relation) => entityIds.has(relation.from) && entityIds.has(relation.to)).map((relation) => {
    const text = edgeLabelText(relation.kind)
    return {
      id: relation.id,
      sources: [`${relation.from}::out`],
      targets: [`${relation.to}::in`],
      labels: [{ id: `${relation.id}::label`, text, width: Math.ceil((text.length * EDGE_LABEL_SCREEN_CHAR_WIDTH + EDGE_LABEL_SCREEN_PADDING) / MAP_LABEL_MIN_ZOOM), height: Math.ceil(EDGE_LABEL_SCREEN_HEIGHT / MAP_LABEL_MIN_ZOOM) }],
    }
  })
  const orderedGroups = [...MAP_GROUPS, OTHER_GROUP].map((group) => groups.get(group.id)).filter((group): group is NonNullable<typeof group> => Boolean(group))
  const root: ElkNode = {
    id: 'map-root',
    layoutOptions: { ...ROOT_OPTIONS, 'elk.direction': direction },
    children: orderedGroups.map((group) => ({
      id: group.id,
      layoutOptions: { 'elk.padding': `[top=${MAP_GROUP_PADDING.top},left=${MAP_GROUP_PADDING.side},bottom=${MAP_GROUP_PADDING.bottom},right=${MAP_GROUP_PADDING.side}]`, 'elk.direction': direction },
      children: group.children,
    })),
    edges,
  }
  const elk = await loadElk()
  const result = await elk.layout(root)
  const nodes = new Map<string, MapRect>()
  const groupLayouts: MapGroupLayout[] = []
  for (const group of result.children ?? []) {
    const gx = group.x ?? 0
    const gy = group.y ?? 0
    groupLayouts.push({ id: group.id, label: groups.get(group.id)?.label ?? group.id, count: group.children?.length ?? 0, x: gx, y: gy, width: group.width ?? 0, height: group.height ?? 0 })
    for (const child of group.children ?? []) nodes.set(child.id, { x: gx + (child.x ?? 0), y: gy + (child.y ?? 0), width: child.width ?? MAP_NODE_WIDTH, height: child.height ?? MAP_NODE_HEIGHT })
  }
  const edgeLayouts = new Map<string, MapEdgeLayout>()
  for (const edge of result.edges ?? []) {
    const section = edge.sections?.[0]
    if (!section) continue
    const label = edge.labels?.[0]
    edgeLayouts.set(edge.id, {
      points: [section.startPoint, ...(section.bendPoints ?? []), section.endPoint],
      label: label && label.x !== undefined && label.y !== undefined ? { x: label.x, y: label.y, width: label.width ?? 0, height: label.height ?? 0 } : undefined,
    })
  }
  return { key: mapLayoutKey(input, direction), direction, width: result.width ?? 0, height: result.height ?? 0, groups: groupLayouts, nodeGroup, nodes, edges: edgeLayouts }
}
