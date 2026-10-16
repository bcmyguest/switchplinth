import type { Entity, GraphData } from './types'

export function resolveDemoScenario(baseGraph: GraphData, selections: Record<string, string>): GraphData {
  const entities = new Map(baseGraph.entities.map((entity) => [entity.id, entity]))
  const relationships = new Map(baseGraph.relationships.map((relationship) => [relationship.id, relationship]))
  for (const decision of baseGraph.decisions) {
    const optionId = selections[decision.id] ?? decision.selected_option
    const option = decision.options.find((candidate) => candidate.id === optionId)
    for (const operation of option?.delta?.operations ?? []) {
      const entity = operation.entity
      const relationship = operation.relationship
      if (operation.op.endsWith('_entity')) {
        const id = typeof entity === 'string' ? entity : entity && typeof entity === 'object' && 'id' in entity && typeof entity.id === 'string' ? entity.id : ''
        if (!id) continue
        if (operation.op === 'remove_entity') {
          entities.delete(id)
          for (const [relationshipId, current] of relationships) if (current.from === id || current.to === id) relationships.delete(relationshipId)
        } else if (entity && typeof entity === 'object') {
          entities.set(id, { ...entities.get(id), ...entity } as Entity)
        }
      } else if (operation.op.endsWith('_relationship')) {
        const id = relationship && typeof relationship === 'object' && 'id' in relationship && typeof relationship.id === 'string' ? relationship.id : ''
        if (!id) continue
        if (operation.op === 'remove_relationship') relationships.delete(id)
        else if (relationship && typeof relationship === 'object' && 'from' in relationship && typeof relationship.from === 'string' && 'to' in relationship && typeof relationship.to === 'string' && 'kind' in relationship && typeof relationship.kind === 'string') {
          relationships.set(id, { ...relationships.get(id), ...relationship } as GraphData['relationships'][number])
        }
      }
    }
  }
  const decisions = baseGraph.decisions.map((decision) => ({ ...decision, selected_option: selections[decision.id] ?? decision.selected_option }))
  const baseSelections = Object.fromEntries(baseGraph.decisions.filter((decision) => decision.selected_option).map((decision) => [decision.id, decision.selected_option as string]))
  const addedEntities = [...entities.keys()].filter((id) => !baseGraph.entities.some((entity) => entity.id === id))
  const removedEntities = baseGraph.entities.filter((entity) => !entities.has(entity.id)).map((entity) => entity.id)
  const addedRelationships = [...relationships.keys()].filter((id) => !baseGraph.relationships.some((relationship) => relationship.id === id))
  const removedRelationships = baseGraph.relationships.filter((relationship) => !relationships.has(relationship.id)).map((relationship) => relationship.id)
  return {
    ...baseGraph,
    entities: [...entities.values()],
    relationships: [...relationships.values()],
    decisions,
    claims: baseGraph.claims?.filter((claim) => entities.has(claim.subject) && entities.has(claim.object)),
    aliases: baseGraph.aliases?.filter((alias) => entities.has(alias.entity_id)),
    scenario: {
      selections,
      affected: {
        added: [...addedEntities, ...addedRelationships],
        removed: [...removedEntities, ...removedRelationships],
        changed: [],
      },
      affected_decisions: decisions.filter((decision) => baseSelections[decision.id] !== (selections[decision.id] ?? decision.selected_option)).map((decision) => decision.id),
      conflicts: [],
      invalid_assumptions: [],
    },
  }
}
