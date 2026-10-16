// Component detail derivation: the selected component, its linked decisions (directly or through identity links), and the
// rationale, label, and source passage the detail panel shows. Pure: it reads only its arguments.
import type { getEntityDetail } from '../../api'
import type { Evidence, GraphData, Option } from '../../types'
import { evidenceText, resolveEvidence } from '../evidence/evidence'
import { operationTouchesEntity } from '../graph-editor/deltaOperations'
import type { DeltaEditor } from '../graph-editor/useDeltaEditor'

export type EntityDetail = Awaited<ReturnType<typeof getEntityDetail>>

type ComponentDetailInput = {
  /** The canonical graph shown when no delta preview is open. */
  graph: GraphData
  /** The graph on the map: the delta preview graph while one exists, else `graph`. */
  visibleGraph: GraphData
  /** The requested entity; the first visible entity stands in when it is absent from `visibleGraph`. */
  selectedId: string
  /** The last fetched entity detail; ignored unless it belongs to the visible selected entity. */
  entityDetail: EntityDetail | null
  displayed: Record<string, string>
  preview: DeltaEditor['preview']
}

export type ComponentDetail = ReturnType<typeof deriveComponentDetail>

/**
 * Puts decisions whose current choice involves the entity first; the rest keep their order (stable partition).
 * `involvesEntity` tells whether an option's typed delta touches the selected entity or an identity-related one.
 */
export function orderLinkedDecisions<D extends { selected_option?: Option | null }>(decisions: D[], involvesEntity: (option: Option) => boolean): D[] {
  const involved = decisions.filter((decision) => decision.selected_option && involvesEntity(decision.selected_option))
  return [...involved, ...decisions.filter((decision) => !involved.includes(decision))]
}

export function deriveComponentDetail({ graph, visibleGraph, selectedId, entityDetail, displayed: displayedSelection, preview: deltaPreview }: ComponentDetailInput) {
  const selected = visibleGraph.entities.find((entity) => entity.id === selectedId) ?? visibleGraph.entities[0]
  const visibleSelectedEntityId = selected?.id ?? ''
  const currentEntityDetail = entityDetail?.entity.id === visibleSelectedEntityId ? entityDetail : null
  const identityGroups = graph.identity_groups ?? []
  const identitySuggestions = graph.identity_suggestions ?? []
  const identityConflicts = graph.identity_conflicts ?? []
  const evidenceRecords = [...(currentEntityDetail?.evidence ?? []), ...(graph.evidence ?? [])]
  const conflictedIdentityEntityIds = new Set(identityConflicts.flatMap((conflict) => conflict.component_entity_ids ?? conflict.entity_ids))
  const relatedEntityIds = new Set([visibleSelectedEntityId])
  const relatedEntityReasons = new Map<string, string>()
  if (visibleSelectedEntityId && !conflictedIdentityEntityIds.has(visibleSelectedEntityId)) {
    for (const group of identityGroups) {
      if (group.entity_ids.includes(visibleSelectedEntityId)) {
        for (const id of group.entity_ids) {
          relatedEntityIds.add(id)
          if (id !== visibleSelectedEntityId) relatedEntityReasons.set(id, 'a human-reviewed identity group')
        }
      }
    }
    for (const suggestion of identitySuggestions) {
      if (suggestion.epistemic_state === 'rejected' || !suggestion.entity_ids.includes(visibleSelectedEntityId) || suggestion.entity_ids.some((id) => conflictedIdentityEntityIds.has(id))) continue
      if (suggestion.source === 'inferred_claim') {
        const hasCurrentEvidence = (suggestion.evidence ?? []).some((reference) => {
          const evidenceId = typeof reference === 'string' ? reference : reference.id
          return evidenceRecords.some((item) => item.id === evidenceId && item.state !== 'unresolved')
        })
        if (!hasCurrentEvidence) continue
      } else if (suggestion.source !== 'exact_name') continue
      for (const id of suggestion.entity_ids) {
        relatedEntityIds.add(id)
        if (id !== visibleSelectedEntityId) relatedEntityReasons.set(id, suggestion.source === 'exact_name' ? 'an unresolved exact-name identity candidate' : 'an evidence-backed inferred identity candidate')
      }
    }
  }
  const detailedDecisionIds = new Set(currentEntityDetail?.decisions.map((decision) => decision.id) ?? [])
  const touchesRelatedEntity = (option: Option) => Boolean(option.delta?.operations.some((operation) => [...relatedEntityIds].some((entityId) => operationTouchesEntity(operation, entityId))))
  const linkedDecisionsInGraphOrder = visibleGraph.decisions.filter((decision) => detailedDecisionIds.has(decision.id) || decision.context?.includes(visibleSelectedEntityId) || decision.options.some(touchesRelatedEntity)).map((decision) => ({
    id: decision.id,
    title: decision.title,
    selected_option: decision.options.find((option) => option.id === displayedSelection[decision.id]) ?? null,
    options: decision.options,
    extraction_review: decision.extraction_review,
    relatedBy: [...relatedEntityIds].filter((id) => id !== visibleSelectedEntityId && relatedEntityReasons.has(id) && decision.options.some((option) => option.delta?.operations.some((operation) => operationTouchesEntity(operation, id)))).map((id) => `${relatedEntityReasons.get(id)} (${visibleGraph.entities.find((entity) => entity.id === id)?.name ?? id})`).join(' · '),
  }))
  const linkedDecisions = orderLinkedDecisions(linkedDecisionsInGraphOrder, touchesRelatedEntity)
  const entityDecisionOptions = linkedDecisions.flatMap((decision) => {
    const selectedOptionId = deltaPreview?.decisionId === decision.id ? deltaPreview.optionId : displayedSelection[decision.id] ?? decision.selected_option?.id
    return decision.options.filter(touchesRelatedEntity).map((option) => ({ decision, option, isSelected: option.id === selectedOptionId }))
  })
  const selectedEntityDecision = entityDecisionOptions.find((item) => item.isSelected)
  const alternativeEntityDecision = entityDecisionOptions[0]
  const rationaleDecision = selectedEntityDecision ?? alternativeEntityDecision
  const selectedDecision = rationaleDecision?.decision
  const selectedOption = rationaleDecision?.option
  const selectedDecisionIsAlternative = Boolean(selectedDecision && !selectedEntityDecision)
  const selectedOptionEvidence = selectedOption?.evidence?.map((reference) => resolveEvidence(reference, evidenceRecords)).find((evidence): evidence is Evidence => Boolean(evidence))
  const entityEvidenceReferences = [
    ...(selected?.evidence ?? []),
    ...(currentEntityDetail?.claims?.filter((claim) => claim.subject === visibleSelectedEntityId || claim.object === visibleSelectedEntityId).flatMap((claim) => claim.evidence ?? []) ?? []),
    ...(currentEntityDetail?.aliases?.flatMap((alias) => alias.evidence ?? []) ?? []),
  ]
  const entityEvidence = entityEvidenceReferences.map((reference) => resolveEvidence(reference, evidenceRecords)).find((evidence): evidence is Evidence => Boolean(evidence))
  const selectedEvidence = selectedOptionEvidence ?? entityEvidence ?? currentEntityDetail?.evidence?.[0]
  const selectedRationale = selectedOption?.rationale ?? (entityEvidence ? evidenceText(entityEvidence) : 'No rationale has been linked to this component yet.')
  const rationaleLabel = selectedDecisionIsAlternative ? 'WHY CONSIDERED · NOT SELECTED' : selectedDecision ? 'WHY IT EXISTS' : 'SOURCE CONTEXT'
  return { selected, visibleSelectedEntityId, entityDetail: currentEntityDetail, evidenceRecords, linkedDecisions, rationaleLabel, rationale: selectedRationale, evidence: selectedEvidence }
}
