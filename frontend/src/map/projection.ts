// Projects a compiled graph onto React Flow nodes and edges, including confirmed identity-group merging for display.
import type { Edge, Node } from '@xyflow/react'
import type { Entity, GraphData } from '../types'

export function entityNodes(graph: GraphData, columns = 3): Node[] {
  return graph.entities.map((entity, index) => ({
    id: entity.id,
    position: { x: 90 + (index % columns) * 300, y: 100 + Math.floor(index / columns) * 150 },
    width: 252,
    height: 72,
    data: {
      label: entity.name,
      title: [entity.name, ...(entity.aliases ?? []).map((alias) => `${alias.name} (${alias.epistemic_state})`), entity.evidence?.length ? `${entity.evidence.length} source references aggregated` : '', entity.description ?? ''].filter(Boolean).join(' · '),
      kind: entity.kind,
      status: entity.epistemic_state ?? (graph.claims?.some((claim) => (claim.subject === entity.id || claim.object === entity.id) && claim.epistemic_state === 'inferred') ? 'inferred' : 'confirmed'),
      confidence: entity.confidence,
    },
    type: 'architecture',
  }))
}

export function mapGraphWithConfirmedIdentityGroups(graph: GraphData): GraphData {
  const entityById = new Map(graph.entities.map((entity) => [entity.id, entity]))
  const representativeById = new Map<string, string>()
  const membersByRepresentative = new Map<string, Entity[]>()
  for (const group of graph.identity_groups ?? []) {
    const members = group.entity_ids.map((id) => entityById.get(id)).filter((entity): entity is Entity => Boolean(entity))
    if (members.length < 2) continue
    const representative = members[0].id
    membersByRepresentative.set(representative, members)
    for (const member of members) representativeById.set(member.id, representative)
  }
  if (!membersByRepresentative.size) return graph
  const entities = graph.entities.filter((entity) => !representativeById.has(entity.id) || representativeById.get(entity.id) === entity.id).map((entity) => {
    const members = membersByRepresentative.get(entity.id)
    if (!members) return entity
    const aliasesById = new Map<string, NonNullable<Entity['aliases']>[number]>()
    for (const member of members) for (const alias of member.aliases ?? []) aliasesById.set(alias.id, alias)
    for (const member of members) for (const alias of graph.aliases ?? []) if (alias.entity_id === member.id) aliasesById.set(alias.id, alias)
    const evidence = [...new Set(members.flatMap((member) => (member.evidence ?? []).map((reference) => typeof reference === 'string' ? reference : reference.id)))]
    const confidence = Math.max(...members.map((member) => member.confidence ?? 1))
    const otherMembers = members.filter((member) => member.id !== entity.id).map((member) => `${member.name} (${member.id})`)
    return { ...entity, aliases: [...aliasesById.values()], evidence, confidence, description: `${entity.description ?? ''}${entity.description ? ' ' : ''}Human-reviewed identity group also includes ${otherMembers.join(', ')}.` }
  })
  const remap = (id: string) => representativeById.get(id) ?? id
  return {
    ...graph,
    entities,
    relationships: graph.relationships.map((relationship) => ({ ...relationship, from: remap(relationship.from), to: remap(relationship.to) })),
  }
}

export function entityEdges(graph: GraphData): Edge[] {
  const parallelCounts = new Map<string, number>()
  const parallelTotals = new Map<string, number>()
  for (const relation of graph.relationships) {
    const pair = `${relation.from}\u0000${relation.to}`
    parallelTotals.set(pair, (parallelTotals.get(pair) ?? 0) + 1)
  }
  return graph.relationships.map((relation) => {
    const claim = graph.claims?.find((item) => item.id === relation.claim_id)
    const inferred = relation.epistemic_state === 'inferred' || claim?.epistemic_state === 'inferred'
    const pair = `${relation.from}\u0000${relation.to}`
    const parallelIndex = parallelCounts.get(pair) ?? 0
    parallelCounts.set(pair, parallelIndex + 1)
    const parallelCount = parallelTotals.get(pair) ?? 1
    const labelOffset = parallelCount > 1 ? (parallelIndex - (parallelCount - 1) / 2) * 22 : 0
    return ({
    id: relation.id,
    source: relation.from,
    target: relation.to,
    label: relation.kind.replaceAll('_', ' '),
    type: 'readable',
    data: { labelOffset },
    animated: inferred,
    style: { stroke: inferred ? 'var(--theme-warning)' : 'var(--theme-muted)', strokeWidth: 1.75 },
    labelStyle: { fill: 'var(--theme-muted)', fontSize: 10, fontWeight: 550 },
    labelBgStyle: { fill: 'var(--theme-map-canvas)', fillOpacity: 0.92 },
    markerEnd: { type: 'arrowclosed' as const, color: 'var(--theme-muted)', width: 12, height: 12 },
  })})
}
