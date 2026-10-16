// Facts review: the filter, claim and alias judgments and corrections, identity judgments, and identity endpoint corrections.
// Every judgment writes through the API and then refreshes the workspace graph.
import { useMemo, useState } from 'react'
import { correctAlias, correctClaim, reviewAlias, reviewClaim, reviewExactIdentityCandidate } from '../../api'
import type { Workspace } from '../../app/useWorkspace'
import type { IdentitySuggestion } from '../../types'
import { allKnownEntities } from '../graph-editor/deltaOperations'
import { deriveReviewQueue, STRUCTURAL_PREDICATES, type FactsFilter, type ReviewItem, type ReviewQueue } from './reviewQueue'

type IdentityJudgment = 'confirmed' | 'rejected'
type CorrectionDraft = { name: string; entity_id: string; subject: string; predicate: string; object: string }
type IdentityCorrection = { claimId: string; kind: string; subject: string; object: string }

export type FactsReview = {
  filter: FactsFilter
  setFilter: (filter: FactsFilter) => void
  queue: ReviewQueue
  /** Entities a correction may target. */
  knownEntities: ReturnType<typeof allKnownEntities>
  /** The last failed review or identity judgment. */
  error: string
  /** Shared by the claim/alias correction form and the identity endpoint correction form. */
  correctionError: string
  correctionBusy: boolean
  mark(id: string, status: IdentityJudgment): void
  correction: {
    id: string
    draft: CorrectionDraft
    setDraft: (draft: CorrectionDraft) => void
    open(item: ReviewItem): void
    close(): void
    save(item: ReviewItem): Promise<void>
    updatePredicate(predicate: string): void
  }
  identity: {
    busyId: string
    review(claimId: string, status: IdentityJudgment): Promise<void>
    reviewExactName(suggestion: IdentitySuggestion, status: 'confirmed' | 'asserted' | 'rejected'): Promise<void>
    correction: IdentityCorrection | null
    setCorrection: (correction: IdentityCorrection | null) => void
    openCorrection(suggestion: IdentitySuggestion): void
    saveCorrection(): Promise<void>
  }
  /** Clears this module's share of the repository-switch reset: review error, open correction, correction error. */
  reset(): void
}

export function useFactsReview(workspace: Pick<Workspace, 'graph' | 'refreshGraph'>): FactsReview {
  const { graph, refreshGraph } = workspace
  const [factsFilter, setFactsFilter] = useState<FactsFilter>('all')
  const [reviewError, setReviewError] = useState('')
  const [identityBusyId, setIdentityBusyId] = useState('')
  const [identityCorrection, setIdentityCorrection] = useState<IdentityCorrection | null>(null)
  const [correctionId, setCorrectionId] = useState('')
  const [correctionDraft, setCorrectionDraft] = useState<CorrectionDraft>({ name: '', entity_id: '', subject: '', predicate: '', object: '' })
  const [correctionError, setCorrectionError] = useState('')
  const [correctionBusy, setCorrectionBusy] = useState(false)
  const knownEntityChoices = useMemo(() => allKnownEntities(graph), [graph])
  const queue = deriveReviewQueue(graph, factsFilter)
  const { reviewItems } = queue

  async function reviewIdentityClaim(claimId: string, status: IdentityJudgment) {
    setReviewError('')
    setIdentityBusyId(claimId)
    try {
      await reviewClaim(claimId, status)
      await refreshGraph()
      setIdentityCorrection(null)
    } catch (error) {
      setReviewError(`Could not save identity review: ${error instanceof Error ? error.message : 'connection error'}`)
    } finally {
      setIdentityBusyId('')
    }
  }

  async function reviewExactNameCandidate(suggestion: IdentitySuggestion, status: 'confirmed' | 'asserted' | 'rejected') {
    const [leftId, rightId] = suggestion.entity_ids
    const pairId = `exact-name:${[leftId, rightId].sort().join('|')}`
    setReviewError('')
    setIdentityBusyId(pairId)
    try {
      await reviewExactIdentityCandidate([leftId, rightId], status)
      await refreshGraph()
    } catch (error) {
      setReviewError(`Could not save identity review: ${error instanceof Error ? error.message : 'connection error'}`)
    } finally {
      setIdentityBusyId('')
    }
  }

  function openIdentityCorrection(suggestion: IdentitySuggestion) {
    if (!suggestion.claim_id || suggestion.entity_ids.length !== 2) return
    setCorrectionError('')
    setIdentityCorrection({ claimId: suggestion.claim_id, kind: suggestion.kind ?? knownEntityChoices.find((entity) => entity.id === suggestion.entity_ids[0])?.kind ?? '', subject: suggestion.entity_ids[0], object: suggestion.entity_ids[1] })
  }

  async function saveIdentityCorrection() {
    if (!identityCorrection) return
    setCorrectionError('')
    setCorrectionBusy(true)
    try {
      const subject = graph.entities.find((entity) => entity.id === identityCorrection.subject)
      const object = graph.entities.find((entity) => entity.id === identityCorrection.object)
      if (!subject || !object || subject.id === object.id || subject.kind !== object.kind || subject.kind !== identityCorrection.kind) {
        throw new Error('Choose two distinct existing entities of the same kind.')
      }
      await correctClaim(identityCorrection.claimId, { subject: subject.id, predicate: 'same_entity_as', object: object.id })
      await refreshGraph()
      setIdentityCorrection(null)
    } catch (error) {
      setCorrectionError(`Could not save identity correction: ${error instanceof Error ? error.message : 'connection error'}`)
    } finally {
      setCorrectionBusy(false)
    }
  }

  function markReviewed(id: string, status: IdentityJudgment) {
    const item = reviewItems.find((candidate) => candidate.id === id)
    if (!item) return
    setReviewError('')
    const action = item.type === 'alias' ? reviewAlias : reviewClaim
    void action(id, status).then(() => refreshGraph()).catch((error) => setReviewError(`Could not save review: ${error instanceof Error ? error.message : 'connection error'}`))
  }

  function openCorrection(item: ReviewItem) {
    const claim = item.type === 'claim' ? graph.claims?.find((candidate) => candidate.id === item.id) : undefined
    const alias = item.type === 'alias' ? graph.aliases?.find((candidate) => candidate.id === item.id) : undefined
    setCorrectionDraft({ name: alias?.name ?? '', entity_id: alias?.entity_id ?? knownEntityChoices[0]?.id ?? '', subject: claim?.subject ?? knownEntityChoices[0]?.id ?? '', predicate: claim?.predicate ?? '', object: claim?.object ?? knownEntityChoices[0]?.id ?? '' })
    setCorrectionId(item.id)
    setCorrectionError('')
  }

  async function saveCorrection(item: ReviewItem) {
    setCorrectionError('')
    setCorrectionBusy(true)
    try {
      if (item.type === 'alias') {
        if (!correctionDraft.name.trim() || !knownEntityChoices.some((entity) => entity.id === correctionDraft.entity_id)) throw new Error('Enter an alias and select a valid target entity.')
        await correctAlias(item.id, { name: correctionDraft.name.trim(), entity_id: correctionDraft.entity_id })
      } else {
        const structural = STRUCTURAL_PREDICATES.has(correctionDraft.predicate.trim())
        if (!correctionDraft.subject.trim() || !correctionDraft.predicate.trim() || !correctionDraft.object.trim() || (structural && (!knownEntityChoices.some((entity) => entity.id === correctionDraft.subject) || !knownEntityChoices.some((entity) => entity.id === correctionDraft.object)))) throw new Error(structural ? 'Choose valid subject and object entities and enter a predicate.' : 'Enter a subject, predicate, and object value.')
        await correctClaim(item.id, { subject: correctionDraft.subject.trim(), predicate: correctionDraft.predicate.trim(), object: correctionDraft.object.trim() })
      }
      await refreshGraph()
      setCorrectionId('')
    } catch (error) {
      setCorrectionError(`Could not save asserted correction: ${error instanceof Error ? error.message : 'connection error'}`)
    } finally {
      setCorrectionBusy(false)
    }
  }

  function updateCorrectionPredicate(predicate: string) {
    const firstEntityId = knownEntityChoices[0]?.id ?? ''
    const subject = knownEntityChoices.some((entity) => entity.id === correctionDraft.subject) ? correctionDraft.subject : firstEntityId
    const object = knownEntityChoices.some((entity) => entity.id === correctionDraft.object) ? correctionDraft.object : firstEntityId
    setCorrectionDraft({ ...correctionDraft, predicate, subject: STRUCTURAL_PREDICATES.has(predicate) ? subject : correctionDraft.subject, object: STRUCTURAL_PREDICATES.has(predicate) ? object : correctionDraft.object })
  }

  function reset() {
    setReviewError('')
    setCorrectionId('')
    setCorrectionError('')
  }

  return {
    filter: factsFilter,
    setFilter: setFactsFilter,
    queue,
    knownEntities: knownEntityChoices,
    error: reviewError,
    correctionError,
    correctionBusy,
    mark: markReviewed,
    correction: {
      id: correctionId,
      draft: correctionDraft,
      setDraft: setCorrectionDraft,
      open: openCorrection,
      close: () => setCorrectionId(''),
      save: saveCorrection,
      updatePredicate: updateCorrectionPredicate,
    },
    identity: {
      busyId: identityBusyId,
      review: reviewIdentityClaim,
      reviewExactName: reviewExactNameCandidate,
      correction: identityCorrection,
      setCorrection: setIdentityCorrection,
      openCorrection: openIdentityCorrection,
      saveCorrection: saveIdentityCorrection,
    },
    reset,
  }
}
