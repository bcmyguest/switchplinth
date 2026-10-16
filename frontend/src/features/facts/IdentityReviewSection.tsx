// Identity review views: confirmed identity groups, identity suggestion cards with their judgment and correction controls,
// and identity conflict cards. Facts lists them for the whole graph; the selected-component panel lists one entity's share.
import { FileText } from 'lucide-react'
import type { getEntityDetail } from '../../api'
import { InlineError } from '../../components/InlineError'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { Select } from '../../components/ui/select'
import type { Claim, Entity, Evidence, GraphData, IdentityConflict, IdentityGroup, IdentitySuggestion } from '../../types'
import { evidenceHeading, evidencePath, resolveEvidence } from '../evidence/evidence'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import type { FactsReview } from './useFactsReview'

const IDENTITY_CARD = 'min-w-0 rounded-[7px] border-(--theme-line) bg-(--theme-panel-raised) p-[10px] shadow-none [overflow-wrap:anywhere]'
/** Passage link inside an identity card: icon, then the passage label that wraps anywhere. */
const PASSAGE_LINK = 'flex items-start gap-[5px] px-0 py-[3px] text-left text-(length:--type-tertiary) text-(--theme-source) [overflow-wrap:anywhere] [&>svg]:mt-[2px] [&>svg]:flex-none'
/** Identity judgment action; actions share a wrapping row and grow on mobile. */
const IDENTITY_ACTION = 'justify-center px-[8px] py-[5px] text-center text-(length:--type-tertiary) font-semibold text-(--theme-source) max-sm:flex-[1_1_90px]'
const IDENTITY_SELECT = 'w-full min-w-0 rounded-[5px] border border-(--theme-line) bg-(--theme-panel) px-[5px] text-[12px] text-(--theme-ink)'
const CONFLICT_CARD = `identity-conflict block! ${IDENTITY_CARD} border-(--theme-danger)`

type IdentityGroupCardProps = { group: IdentityGroup; graph: GraphData }

type IdentitySuggestionCardProps = {
  suggestion: IdentitySuggestion
  graph: GraphData
  /** Claims searched for the suggestion's claim ID. */
  claims: Claim[]
  evidenceRecords: Evidence[]
  live: boolean
  facts: FactsReview
  onOpenEvidence: EvidenceViewer['open']
}

type IdentityConflictCardProps = {
  conflict: IdentityConflict
  graph: GraphData
  /** Claims searched for the conflict's claim IDs. */
  claims: Claim[]
  /** Evidence records searched for each conflict claim's evidence IDs. */
  evidence: Evidence[]
  live: boolean
  facts: FactsReview
  onOpenEvidence: EvidenceViewer['open']
}

type IdentityReviewSectionProps = {
  selected: Entity
  graph: GraphData
  entityDetail: Awaited<ReturnType<typeof getEntityDetail>> | null
  evidenceRecords: Evidence[]
  live: boolean
  facts: FactsReview
  onOpenEvidence: EvidenceViewer['open']
}

export function IdentityGroupCard({ group, graph }: IdentityGroupCardProps) {
  return <Card className={`identity-group block! ${IDENTITY_CARD}`}><span>Human-reviewed identity group</span><div>{group.entity_ids.map((id) => <span className="identity-endpoint" key={id}>{graph.entities.find((entity) => entity.id === id)?.name ?? id}<code>{id}</code></span>)}</div></Card>
}

export function IdentitySuggestionCard({ suggestion, graph, claims, evidenceRecords, live, facts, onOpenEvidence }: IdentitySuggestionCardProps) {
  const { busyId: identityBusyId, correction: identityCorrection, setCorrection: setIdentityCorrection } = facts.identity
  const { correctionBusy, correctionError } = facts
  const canonicalEntityIds = new Set(graph.entities.map((entity) => entity.id))
  const scenarioAddedEntityIds = new Set(graph.scenario?.affected?.added ?? [])
  const [leftId, rightId] = suggestion.entity_ids
  const claim = claims.find((item) => item.id === suggestion.claim_id)
  const refs = suggestion.evidence ?? claim?.evidence ?? []
  const attachedEvidence = refs.map((reference) => resolveEvidence(reference, evidenceRecords)).filter((item): item is Evidence => Boolean(item))
  const kind = graph.entities.find((entity) => entity.id === leftId)?.kind ?? suggestion.kind ?? 'entity'
  const exactNameReviewable = canonicalEntityIds.has(leftId) && canonicalEntityIds.has(rightId) && !scenarioAddedEntityIds.has(leftId) && !scenarioAddedEntityIds.has(rightId)
  const rejectedExactName = suggestion.source === 'exact_name' && suggestion.epistemic_state === 'rejected'
  return <Card className={`identity-card gap-[7px] ${IDENTITY_CARD}`}>
    <div className="identity-pair"><strong>{graph.entities.find((entity) => entity.id === leftId)?.name ?? leftId}</strong><span aria-hidden="true">↔</span><strong>{graph.entities.find((entity) => entity.id === rightId)?.name ?? rightId}</strong></div>
    <div className="identity-meta"><span>{rejectedExactName ? `Rejected identity judgment · ${suggestion.kind ?? kind}` : suggestion.source === 'exact_name' ? `Exact-name candidate · ${suggestion.kind ?? kind}` : `Inferred identity claim · ${claim?.epistemic_state ?? 'inferred'}`}</span>{suggestion.confidence !== undefined && <span>{Math.round(suggestion.confidence * 100)}% confidence</span>}</div>
    {attachedEvidence.length > 0 && <div className="identity-evidence">{attachedEvidence.map((item) => <Button variant="ghost" className={PASSAGE_LINK} key={item.id} onClick={() => onOpenEvidence(item)}><FileText size={12} /><span className="grid min-w-0 gap-[2px]"><strong className="text-[11px]">Open passage</strong><small className="text-[10px] leading-[1.4] text-(--theme-muted) [overflow-wrap:anywhere]">{evidencePath(item)} · {evidenceHeading(item)}</small></span></Button>)}</div>}
    <div className="identity-endpoint-ids"><code>{leftId}</code><code>{rightId}</code></div>
    {suggestion.claim_id && <div className="identity-provenance">Claim {suggestion.claim_id}{claim?.source_path ? ` · ${claim.source_path}` : ''}{claim?.supersedes?.length ? ` · supersedes ${claim.supersedes.join(', ')}` : ''}</div>}
    {suggestion.source === 'exact_name' ? exactNameReviewable && <div className="identity-actions"><Button variant="choice" className={IDENTITY_ACTION} disabled={!live || identityBusyId === `exact-name:${[leftId, rightId].sort().join('|')}`} onClick={() => void facts.identity.reviewExactName(suggestion, 'confirmed')}>{rejectedExactName ? 'Confirm judgment' : 'Confirm link'}</Button><Button variant="choice" className={IDENTITY_ACTION} disabled={!live || identityBusyId === `exact-name:${[leftId, rightId].sort().join('|')}`} onClick={() => void facts.identity.reviewExactName(suggestion, 'asserted')}>Assert identity</Button><Button variant="choice" className={IDENTITY_ACTION} disabled={!live || identityBusyId === `exact-name:${[leftId, rightId].sort().join('|')}`} onClick={() => void facts.identity.reviewExactName(suggestion, 'rejected')}>{rejectedExactName ? 'Keep rejected' : 'Reject link'}</Button></div> : <div className="identity-actions"><Button variant="choice" className={IDENTITY_ACTION} disabled={!live || identityBusyId === suggestion.claim_id} onClick={() => void facts.identity.review(suggestion.claim_id!, 'confirmed')}>Confirm link</Button><Button variant="choice" className={IDENTITY_ACTION} disabled={!live || identityBusyId === suggestion.claim_id} onClick={() => void facts.identity.review(suggestion.claim_id!, 'rejected')}>Reject link</Button><Button variant="choice" className={IDENTITY_ACTION} disabled={!live || correctionBusy} onClick={() => facts.identity.openCorrection(suggestion)}>Correct endpoints</Button></div>}
    {suggestion.claim_id && identityCorrection && identityCorrection.claimId === suggestion.claim_id && <div className="identity-correction"><label>First {kind}<Select className={IDENTITY_SELECT} value={identityCorrection.subject} onChange={(event) => setIdentityCorrection({ ...identityCorrection, subject: event.target.value })}>{graph.entities.filter((entity) => entity.kind === identityCorrection.kind).map((entity) => <option key={entity.id} value={entity.id}>{entity.name} · {entity.id}</option>)}</Select></label><label>Second {kind}<Select className={IDENTITY_SELECT} value={identityCorrection.object} onChange={(event) => setIdentityCorrection({ ...identityCorrection, object: event.target.value })}>{graph.entities.filter((entity) => entity.kind === identityCorrection.kind).map((entity) => <option key={entity.id} value={entity.id}>{entity.name} · {entity.id}</option>)}</Select></label>{correctionError && <InlineError message={correctionError} />}<div className="identity-actions"><Button variant="choice" className={IDENTITY_ACTION} disabled={correctionBusy} onClick={() => setIdentityCorrection(null)}>Cancel</Button><Button variant="choice" className={IDENTITY_ACTION} disabled={!live || correctionBusy} onClick={() => void facts.identity.saveCorrection()}>{correctionBusy ? 'Saving…' : 'Save asserted correction'}</Button></div></div>}
  </Card>
}

export function IdentityConflictCard({ conflict, graph, claims, evidence, live, facts, onOpenEvidence }: IdentityConflictCardProps) {
  const identityBusyId = facts.identity.busyId
  return <Card className={CONFLICT_CARD}><strong>Identity conflict · {conflict.type.replaceAll('_', ' ')}</strong><p>Conflicting pair: {conflict.entity_ids.map((id) => graph.entities.find((entity) => entity.id === id)?.name ?? id).join(' ↔ ')}</p><div className="identity-endpoint-ids">{(conflict.component_entity_ids ?? conflict.entity_ids).map((id) => <code key={id}>{graph.entities.find((entity) => entity.id === id)?.name ?? id} · {id}</code>)}</div>{conflict.claim_ids?.map((claimId) => { const claim = claims.find((item) => item.id === claimId); return <div className="identity-conflict-claim" key={claimId}><span>{claim?.epistemic_state ?? 'Judgment'} · {claimId}{claim?.source_path ? ` · ${claim.source_path}` : ''}</span>{claim?.evidence?.map((id) => evidence.find((item) => item.id === id)).filter((item): item is Evidence => Boolean(item)).map((item) => <Button variant="ghost" className={PASSAGE_LINK} key={item.id} onClick={() => onOpenEvidence(item)}><FileText size={12} />{evidencePath(item)} · {evidenceHeading(item)}</Button>)}<div className="identity-actions"><Button variant="choice" className={IDENTITY_ACTION} disabled={!live || identityBusyId === claimId} onClick={() => void facts.identity.review(claimId, 'confirmed')}>Confirm judgment</Button><Button variant="choice" className={IDENTITY_ACTION} disabled={!live || identityBusyId === claimId} onClick={() => void facts.identity.review(claimId, 'rejected')}>Reject judgment</Button></div></div>})}</Card>
}

/** The selected component's identity groups, rejected aliases, suggestions, and conflicts. */
export function IdentityReviewSection({ selected, graph, entityDetail, evidenceRecords, live, facts, onOpenEvidence }: IdentityReviewSectionProps) {
  const identityGroups = graph.identity_groups ?? []
  const identitySuggestions = graph.identity_suggestions ?? []
  const identityConflicts = graph.identity_conflicts ?? []
  const claims = entityDetail?.claims ?? graph.claims ?? []
  return <section className="identity-review" aria-labelledby="selected-identity-title">
    <div className="identity-review-heading"><strong id="selected-identity-title">Identity review</strong><span>Entity IDs stay separate</span></div>
    {identityGroups.filter((group) => group.entity_ids.includes(selected.id)).map((group) => <IdentityGroupCard key={group.entity_ids.join('|')} group={group} graph={graph} />)}
    {(entityDetail?.aliases ?? graph.aliases ?? []).filter((alias) => alias.entity_id === selected.id && alias.epistemic_state === 'rejected').map((alias) => <Card className={CONFLICT_CARD} key={`rejected-alias-${alias.id}`}><strong>Rejected alias · “{alias.name}”</strong><p>This name is not linked to {selected.name}. The similarly named map nodes remain separate.</p><div className="identity-provenance">Human alias review{alias.reviewer ? ` · ${alias.reviewer}` : ''}{alias.reviewed_alias ? ` · reviewed ${alias.reviewed_alias}` : ''}</div>{alias.evidence?.map((reference) => resolveEvidence(reference, evidenceRecords)).filter((item): item is Evidence => Boolean(item)).map((item) => <Button variant="ghost" className="mt-[7px] flex min-h-0 items-start gap-[5px] p-0 text-left text-[11px] leading-[1.4] text-(--theme-ink) [&>svg]:mt-px [&>svg]:flex-none" key={item.id} onClick={() => onOpenEvidence(item)}><FileText size={12} />{evidencePath(item)} · {evidenceHeading(item)}</Button>)}</Card>)}
    {identitySuggestions.filter((suggestion) => suggestion.entity_ids.includes(selected.id)).map((suggestion) => <IdentitySuggestionCard key={`${suggestion.source}-${suggestion.entity_ids[0]}-${suggestion.entity_ids[1]}-${suggestion.claim_id ?? ''}`} suggestion={suggestion} graph={graph} claims={claims} evidenceRecords={evidenceRecords} live={live} facts={facts} onOpenEvidence={onOpenEvidence} />)}
    {identityConflicts.filter((conflict) => (conflict.component_entity_ids ?? conflict.entity_ids).includes(selected.id)).map((conflict) => <IdentityConflictCard key={`${conflict.type}-${conflict.entity_ids.join('|')}`} conflict={conflict} graph={graph} claims={claims} evidence={evidenceRecords} live={live} facts={facts} onOpenEvidence={onOpenEvidence} />)}
    {facts.error && <InlineError message={facts.error} />}
    {!identitySuggestions.some((suggestion) => suggestion.entity_ids.includes(selected.id)) && !identityConflicts.some((conflict) => (conflict.component_entity_ids ?? conflict.entity_ids).includes(selected.id)) && !identityGroups.some((group) => group.entity_ids.includes(selected.id)) && !(entityDetail?.aliases ?? graph.aliases ?? []).some((alias) => alias.entity_id === selected.id && alias.epistemic_state === 'rejected') && <p className="identity-empty">No identity suggestions or conflicts for this entity.</p>}
  </section>
}
