// Facts review queue: the claim and alias rows that still need a human look, the pending count, and the per-filter partitions.
// Pure: it reads only the graph and the active filter.
import type { GraphData } from '../../types'
import { evidencePath } from '../evidence/evidence'

/** Predicates whose subject and object must be existing entities. */
export const STRUCTURAL_PREDICATES = new Set(['uses', 'publishes_to', 'calls', 'depends_on', 'stores_in', 'communicates_with', 'implements'])

export type FactsFilter = 'all' | 'direct' | 'rejected' | 'conflicts' | 'claims' | 'aliases'

export type ReviewItem = ReturnType<typeof rawReviewItems>[number]

export type ReviewQueue = {
  /** Claim and alias rows that no later human judgment supersedes. */
  reviewItems: ReviewItem[]
  /** Inferred review rows plus every identity suggestion. */
  pendingCount: number
  directIdentitySuggestions: NonNullable<GraphData['identity_suggestions']>
  rejectedIdentitySuggestions: NonNullable<GraphData['identity_suggestions']>
  visibleIdentitySuggestions: NonNullable<GraphData['identity_suggestions']>
  visibleIdentityConflicts: NonNullable<GraphData['identity_conflicts']>
  visibleReviewItems: ReviewItem[]
}

function rawReviewItems(graph: GraphData) {
  return [
    ...(graph.claims ?? []).filter((claim) => claim.predicate !== 'same_entity_as').map((claim) => ({ id: claim.id, type: 'claim' as const, name: `${graph.entities.find((entity) => entity.id === claim.subject)?.name ?? claim.subject} ${claim.predicate.replaceAll('_', ' ')} ${graph.entities.find((entity) => entity.id === claim.object)?.name ?? claim.object}`, detail: `Relationship claim · ${claim.source_path ?? (claim.evidence?.length ? 'source evidence linked' : 'no source path')}`, status: claim.epistemic_state, confidence: claim.confidence })),
    ...(graph.aliases ?? []).map((alias) => ({ id: alias.id, type: 'alias' as const, subject: alias.entity_id, predicate: 'alias_of', object: alias.name, name: `“${alias.name}” refers to ${graph.entities.find((entity) => entity.id === alias.entity_id)?.name ?? alias.entity_id}`, detail: `Alias mapping · ${graph.evidence?.find((item) => alias.evidence?.some((reference) => (typeof reference === 'string' ? reference : reference.id) === item.id)) ? evidencePath(graph.evidence.find((item) => alias.evidence?.some((reference) => (typeof reference === 'string' ? reference : reference.id) === item.id))) : 'source evidence linked'}`, status: alias.epistemic_state, confidence: alias.confidence })),
  ]
}

export function deriveReviewQueue(graph: GraphData, factsFilter: FactsFilter): ReviewQueue {
  const identitySuggestions = graph.identity_suggestions ?? []
  const identityConflicts = graph.identity_conflicts ?? []
  const supersededClaimIds = new Set((graph.claims ?? []).flatMap((claim) => claim.supersedes ?? []))
  const supersededAliasIds = new Set((graph.aliases ?? []).flatMap((alias) => alias.supersedes ?? []))
  const reviewItems = rawReviewItems(graph).filter((item) => {
    const proposition = graph.claims?.find((claim) => claim.id === item.id)
    if (proposition) {
      if (supersededClaimIds.has(proposition.id)) return false
      if (proposition.epistemic_state === 'inferred' && graph.claims?.some((claim) => claim.epistemic_state !== 'inferred' && claim.supersedes?.includes(proposition.id))) return false
      if (proposition.epistemic_state !== 'inferred') return true
      return !graph.claims?.some((claim) => claim.subject === proposition.subject && claim.predicate === proposition.predicate && claim.object === proposition.object && claim.epistemic_state !== 'inferred')
    }
    if (item.type === 'alias') {
      if (supersededAliasIds.has(item.id)) return false
      if (item.status === 'inferred') return !graph.aliases?.some((alias) => alias.entity_id === item.subject && alias.name === item.object && alias.epistemic_state !== 'inferred')
    }
    return true
  })
  const pendingCount = reviewItems.filter((item) => item.status === 'inferred').length + (graph.identity_suggestions ?? []).length
  const directIdentitySuggestions = identitySuggestions.filter((suggestion) => suggestion.epistemic_state !== 'rejected')
  const rejectedIdentitySuggestions = identitySuggestions.filter((suggestion) => suggestion.epistemic_state === 'rejected')
  const visibleIdentitySuggestions = factsFilter === 'direct' ? directIdentitySuggestions : factsFilter === 'rejected' ? rejectedIdentitySuggestions : factsFilter === 'all' ? identitySuggestions : []
  const visibleIdentityConflicts = factsFilter === 'all' || factsFilter === 'conflicts' ? identityConflicts : []
  const visibleReviewItems = reviewItems.filter((item) => factsFilter === 'all' || factsFilter === 'claims' && item.type === 'claim' || factsFilter === 'aliases' && item.type === 'alias')
  return { reviewItems, pendingCount, directIdentitySuggestions, rejectedIdentitySuggestions, visibleIdentitySuggestions, visibleIdentityConflicts, visibleReviewItems }
}
