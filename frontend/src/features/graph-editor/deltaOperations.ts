// Pure helpers for typed option deltas: YAML parsing, validation for preview, and applying operations to a graph.
import { parse, stringify } from 'yaml'
import type { DeltaOperation, Entity, GraphData } from '../../types'

export const DEFAULT_DELTA = stringify({ base: 'architecture', operations: [] })

export function deltaOperationsFromText(text: string): DeltaOperation[] {
  try {
    const parsed = parse(text) as { operations?: DeltaOperation[] } | null
    return Array.isArray(parsed?.operations)
      ? parsed.operations.filter((operation): operation is DeltaOperation => Boolean(operation && typeof operation === 'object' && 'op' in operation && typeof operation.op === 'string'))
      : []
  } catch { return [] }
}

export function parseDeltaForPreview(text: string): { base?: string; operations: DeltaOperation[] } {
  const parsed = parse(text) as { base?: string; operations?: unknown[] } | null
  if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.operations)) throw new Error('Delta must contain an operations list.')
  const supportedOperations = new Set(['add_entity', 'remove_entity', 'replace_entity', 'add_relationship', 'remove_relationship', 'replace_relationship'])
  const operations = parsed.operations.map((operation, index) => {
    if (!operation || typeof operation !== 'object' || Array.isArray(operation) || !('op' in operation) || typeof operation.op !== 'string' || !operation.op.trim()) {
      throw new Error(`Operation ${index + 1} is incomplete. Add an operation type and its required fields before previewing.`)
    }
    const record = operation as DeltaOperation
    if (!supportedOperations.has(record.op)) throw new Error(`Operation ${index + 1} uses unsupported type “${record.op}”.`)
    const entityOperation = record.op.endsWith('_entity')
    const payload = entityOperation ? record.entity : record.relationship
    const requiredFields = record.op.startsWith('remove_') ? ['id'] : entityOperation ? ['id', 'kind', 'name'] : ['id', 'from', 'to', 'kind']
    if (!payload || typeof payload !== 'object' || Array.isArray(payload) || requiredFields.some((field) => typeof (payload as Record<string, unknown>)[field] !== 'string' || !(payload as Record<string, string>)[field].trim())) {
      throw new Error(`Operation ${index + 1} (${record.op}) needs ${requiredFields.join(', ')} before previewing.`)
    }
    return record
  })
  return { base: parsed.base, operations }
}

export function entitiesForOption(graph: GraphData, operations: DeltaOperation[]): Entity[] {
  const entities = new Map(graph.entities.map((entity) => [entity.id, entity]))
  for (const operation of operations) {
    const payload = operation.entity
    if (typeof payload === 'string') {
      if (operation.op === 'remove_entity') entities.delete(payload)
      continue
    }
    if (!payload || typeof payload !== 'object' || !('id' in payload) || typeof payload.id !== 'string') continue
    if (operation.op === 'remove_entity') entities.delete(payload.id)
    else if (operation.op === 'add_entity' || operation.op === 'replace_entity') {
      const current = entities.get(payload.id)
      entities.set(payload.id, { ...current, ...payload } as Entity)
    }
  }
  return [...entities.values()]
}

export function allKnownEntities(graph: GraphData): Entity[] {
  const entities = new Map(graph.entities.map((entity) => [entity.id, entity]))
  for (const decision of graph.decisions) for (const option of decision.options) for (const operation of option.delta?.operations ?? []) {
    if (operation.op !== 'add_entity' && operation.op !== 'replace_entity') continue
    const entity = operation.entity
    if (entity && typeof entity === 'object' && 'id' in entity && typeof entity.id === 'string') entities.set(entity.id, { ...(entities.get(entity.id) ?? {}), ...entity } as Entity)
  }
  return [...entities.values()]
}

export function relationshipLabelsForGraph(graph: GraphData): Map<string, string> {
  const entityNames = new Map(allKnownEntities(graph).map((entity) => [entity.id, entity.name]))
  const relationships = new Map(graph.relationships.map((relationship) => [relationship.id, relationship]))
  for (const decision of graph.decisions) for (const option of decision.options) for (const operation of option.delta?.operations ?? []) {
    if (operation.op !== 'add_relationship' && operation.op !== 'replace_relationship') continue
    const relationship = operation.relationship
    if (!relationship || typeof relationship !== 'object' || !('id' in relationship) || typeof relationship.id !== 'string') continue
    relationships.set(relationship.id, relationship as GraphData['relationships'][number])
  }
  return new Map([...relationships.values()].map((relationship) => [relationship.id, `${entityNames.get(relationship.from) ?? relationship.from} → ${entityNames.get(relationship.to) ?? relationship.to} (${relationship.kind.replaceAll('_', ' ')})`]))
}

export function relationshipsForOption(graph: GraphData, operations: DeltaOperation[]): GraphData['relationships'] {
  const relationships = new Map(graph.relationships.map((relationship) => [relationship.id, relationship]))
  for (const operation of operations) {
    const payload = operation.relationship
    if (!payload || typeof payload !== 'object' || !('id' in payload) || typeof payload.id !== 'string') continue
    if (operation.op === 'remove_relationship') relationships.delete(payload.id)
    else if (operation.op === 'add_relationship' || operation.op === 'replace_relationship') relationships.set(payload.id, payload as GraphData['relationships'][number])
  }
  return [...relationships.values()]
}

export function operationTouchesEntity(operation: DeltaOperation, entityId: string): boolean {
  const entity = operation.entity as { id?: string } | undefined
  const relationship = operation.relationship as { from?: string; to?: string } | undefined
  return entity?.id === entityId || operation.entity === entityId || operation.from === entityId || operation.to === entityId || relationship?.from === entityId || relationship?.to === entityId
}
