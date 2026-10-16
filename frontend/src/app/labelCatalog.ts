// Display names for entity and relationship IDs that outlive the current graph.
// Scenario change lists name records that the resolved graph may no longer contain, so the catalog keeps every name it has seen
// until a repository switch replaces it.
import type { GraphData } from '../types'
import { allKnownEntities, relationshipLabelsForGraph } from '../features/graph-editor/deltaOperations'

export type LabelCatalog = {
  /** Records the entity names and relationship labels of one graph. */
  remember(graph: GraphData): void
  /** Forgets every name, then records `graph`. Used when another repository opens. */
  replace(graph: GraphData): void
  /** Records a backend-resolved scenario: base entities, option-delta entities and relationships, then both graphs' relationships. */
  rememberScenario(base: GraphData, resolved: GraphData): void
  /** Records a locally resolved demo scenario and returns a labeller that prefers the demo graphs' entity names. */
  rememberDemoScenario(base: GraphData, resolved: GraphData): (id: string) => string
  /** The entity name, else the relationship label, else the ID itself. */
  label(id: string): string
}

export function createLabelCatalog(): LabelCatalog {
  const entityNames = new Map<string, string>()
  const relationshipLabels = new Map<string, string>()

  function remember(graph: GraphData) {
    for (const entity of graph.entities) entityNames.set(entity.id, entity.name)
    for (const [id, label] of relationshipLabelsForGraph(graph)) relationshipLabels.set(id, label)
  }

  function replace(graph: GraphData) {
    entityNames.clear()
    relationshipLabels.clear()
    remember(graph)
  }

  function rememberScenario(base: GraphData, resolved: GraphData) {
    for (const entity of [...allKnownEntities(base), ...resolved.entities]) entityNames.set(entity.id, entity.name)
    for (const decision of base.decisions) for (const option of decision.options) for (const operation of option.delta?.operations ?? []) {
      if ((operation.op === 'add_entity' || operation.op === 'replace_entity') && operation.entity && typeof operation.entity === 'object' && 'id' in operation.entity && typeof operation.entity.id === 'string' && 'name' in operation.entity && typeof operation.entity.name === 'string') entityNames.set(operation.entity.id, operation.entity.name)
      if (operation.op !== 'add_relationship' && operation.op !== 'replace_relationship') continue
      const relationship = operation.relationship
      if (!relationship || typeof relationship !== 'object' || !('id' in relationship) || typeof relationship.id !== 'string') continue
      const relation = relationship as { id: string; from?: unknown; to?: unknown; kind?: unknown }
      const from = typeof relation.from === 'string' ? entityNames.get(relation.from) ?? relation.from : ''
      const to = typeof relation.to === 'string' ? entityNames.get(relation.to) ?? relation.to : ''
      relationshipLabels.set(relation.id, `${from} → ${to} (${String(relation.kind ?? 'relationship').replaceAll('_', ' ')})`)
    }
    for (const relation of [...base.relationships, ...resolved.relationships]) {
      const from = entityNames.get(relation.from) ?? relation.from
      const to = entityNames.get(relation.to) ?? relation.to
      relationshipLabels.set(relation.id, `${from} → ${to} (${relation.kind.replaceAll('_', ' ')})`)
    }
  }

  function rememberDemoScenario(base: GraphData, resolved: GraphData) {
    const demoEntityNames = new Map([...base.entities, ...resolved.entities].map((entity) => [entity.id, entity.name]))
    for (const [id, name] of demoEntityNames) entityNames.set(id, name)
    for (const relationship of [...base.relationships, ...resolved.relationships]) {
      const from = demoEntityNames.get(relationship.from) ?? relationship.from
      const to = demoEntityNames.get(relationship.to) ?? relationship.to
      relationshipLabels.set(relationship.id, `${from} → ${to} (${relationship.kind.replaceAll('_', ' ')})`)
    }
    return (id: string) => demoEntityNames.get(id) ?? relationshipLabels.get(id) ?? id
  }

  function label(id: string) {
    return entityNames.get(id) ?? relationshipLabels.get(id) ?? id
  }

  return { remember, replace, rememberScenario, rememberDemoScenario, label }
}
