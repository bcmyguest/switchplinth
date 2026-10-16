// Identity review views: confirmed identity groups, identity suggestion cards with their judgment and correction controls,
// and identity conflict cards. Facts lists them for the whole graph; the selected-component panel lists one entity's share.
import { AlertTriangle, FileText } from 'lucide-react'
import type { getEntityDetail } from '../../api'
import type { Claim, Entity, Evidence, GraphData, IdentityConflict, IdentityGroup, IdentitySuggestion } from '../../types'
import { evidenceHeading, evidencePath, resolveEvidence } from '../evidence/evidence'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import type { FactsReview } from './useFactsReview'

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
  return <div className="identity-group"><span>Human-reviewed identity group</span><div>{group.entity_ids.map((id) => <span className="identity-endpoint" key={id}>{graph.entities.find((entity) => entity.id === id)?.name ?? id}<code>{id}</code></span>)}</div></div>
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
  return <div className="identity-card">
    <div className="identity-pair"><strong>{graph.entities.find((entity) => entity.id === leftId)?.name ?? leftId}</strong><span aria-hidden="true">↔</span><strong>{graph.entities.find((entity) => entity.id === rightId)?.name ?? rightId}</strong></div>
    <div className="identity-meta"><span>{rejectedExactName ? `Rejected identity judgment · ${suggestion.kind ?? kind}` : suggestion.source === 'exact_name' ? `Exact-name candidate · ${suggestion.kind ?? kind}` : `Inferred identity claim · ${claim?.epistemic_state ?? 'inferred'}`}</span>{suggestion.confidence !== undefined && <span>{Math.round(suggestion.confidence * 100)}% confidence</span>}</div>
    {attachedEvidence.length > 0 && <div className="identity-evidence">{attachedEvidence.map((item) => <button key={item.id} onClick={() => onOpenEvidence(item)}><FileText size={12} /><span><strong>Open passage</strong><small>{evidencePath(item)} · {evidenceHeading(item)}</small></span></button>)}</div>}
    <div className="identity-endpoint-ids"><code>{leftId}</code><code>{rightId}</code></div>
    {suggestion.claim_id && <div className="identity-provenance">Claim {suggestion.claim_id}{claim?.source_path ? ` · ${claim.source_path}` : ''}{claim?.supersedes?.length ? ` · supersedes ${claim.supersedes.join(', ')}` : ''}</div>}
    {suggestion.source === 'exact_name' ? exactNameReviewable && <div className="identity-actions"><button disabled={!live || identityBusyId === `exact-name:${[leftId, rightId].sort().join('|')}`} onClick={() => void facts.identity.reviewExactName(suggestion, 'confirmed')}>{rejectedExactName ? 'Confirm judgment' : 'Confirm link'}</button><button disabled={!live || identityBusyId === `exact-name:${[leftId, rightId].sort().join('|')}`} onClick={() => void facts.identity.reviewExactName(suggestion, 'asserted')}>Assert identity</button><button disabled={!live || identityBusyId === `exact-name:${[leftId, rightId].sort().join('|')}`} onClick={() => void facts.identity.reviewExactName(suggestion, 'rejected')}>{rejectedExactName ? 'Keep rejected' : 'Reject link'}</button></div> : <div className="identity-actions"><button disabled={!live || identityBusyId === suggestion.claim_id} onClick={() => void facts.identity.review(suggestion.claim_id!, 'confirmed')}>Confirm link</button><button disabled={!live || identityBusyId === suggestion.claim_id} onClick={() => void facts.identity.review(suggestion.claim_id!, 'rejected')}>Reject link</button><button disabled={!live || correctionBusy} onClick={() => facts.identity.openCorrection(suggestion)}>Correct endpoints</button></div>}
    {suggestion.claim_id && identityCorrection && identityCorrection.claimId === suggestion.claim_id && <div className="identity-correction"><label>First {kind}<select value={identityCorrection.subject} onChange={(event) => setIdentityCorrection({ ...identityCorrection, subject: event.target.value })}>{graph.entities.filter((entity) => entity.kind === identityCorrection.kind).map((entity) => <option key={entity.id} value={entity.id}>{entity.name} · {entity.id}</option>)}</select></label><label>Second {kind}<select value={identityCorrection.object} onChange={(event) => setIdentityCorrection({ ...identityCorrection, object: event.target.value })}>{graph.entities.filter((entity) => entity.kind === identityCorrection.kind).map((entity) => <option key={entity.id} value={entity.id}>{entity.name} · {entity.id}</option>)}</select></label>{correctionError && <div className="inline-error" role="alert"><AlertTriangle size={13} />{correctionError}</div>}<div className="identity-actions"><button disabled={correctionBusy} onClick={() => setIdentityCorrection(null)}>Cancel</button><button disabled={!live || correctionBusy} onClick={() => void facts.identity.saveCorrection()}>{correctionBusy ? 'Saving…' : 'Save asserted correction'}</button></div></div>}
  </div>
}

export function IdentityConflictCard({ conflict, graph, claims, evidence, live, facts, onOpenEvidence }: IdentityConflictCardProps) {
  const identityBusyId = facts.identity.busyId
  return <div className="identity-conflict"><strong>Identity conflict · {conflict.type.replaceAll('_', ' ')}</strong><p>Conflicting pair: {conflict.entity_ids.map((id) => graph.entities.find((entity) => entity.id === id)?.name ?? id).join(' ↔ ')}</p><div className="identity-endpoint-ids">{(conflict.component_entity_ids ?? conflict.entity_ids).map((id) => <code key={id}>{graph.entities.find((entity) => entity.id === id)?.name ?? id} · {id}</code>)}</div>{conflict.claim_ids?.map((claimId) => { const claim = claims.find((item) => item.id === claimId); return <div className="identity-conflict-claim" key={claimId}><span>{claim?.epistemic_state ?? 'Judgment'} · {claimId}{claim?.source_path ? ` · ${claim.source_path}` : ''}</span>{claim?.evidence?.map((id) => evidence.find((item) => item.id === id)).filter((item): item is Evidence => Boolean(item)).map((item) => <button key={item.id} onClick={() => onOpenEvidence(item)}><FileText size={12} />{evidencePath(item)} · {evidenceHeading(item)}</button>)}<div className="identity-actions"><button disabled={!live || identityBusyId === claimId} onClick={() => void facts.identity.review(claimId, 'confirmed')}>Confirm judgment</button><button disabled={!live || identityBusyId === claimId} onClick={() => void facts.identity.review(claimId, 'rejected')}>Reject judgment</button></div></div>})}</div>
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
    {(entityDetail?.aliases ?? graph.aliases ?? []).filter((alias) => alias.entity_id === selected.id && alias.epistemic_state === 'rejected').map((alias) => <div className="identity-conflict" key={`rejected-alias-${alias.id}`}><strong>Rejected alias · “{alias.name}”</strong><p>This name is not linked to {selected.name}. The similarly named map nodes remain separate.</p><div className="identity-provenance">Human alias review{alias.reviewer ? ` · ${alias.reviewer}` : ''}{alias.reviewed_alias ? ` · reviewed ${alias.reviewed_alias}` : ''}</div>{alias.evidence?.map((reference) => resolveEvidence(reference, evidenceRecords)).filter((item): item is Evidence => Boolean(item)).map((item) => <button className="linked-evidence" key={item.id} onClick={() => onOpenEvidence(item)}><FileText size={12} />{evidencePath(item)} · {evidenceHeading(item)}</button>)}</div>)}
    {identitySuggestions.filter((suggestion) => suggestion.entity_ids.includes(selected.id)).map((suggestion) => <IdentitySuggestionCard key={`${suggestion.source}-${suggestion.entity_ids[0]}-${suggestion.entity_ids[1]}-${suggestion.claim_id ?? ''}`} suggestion={suggestion} graph={graph} claims={claims} evidenceRecords={evidenceRecords} live={live} facts={facts} onOpenEvidence={onOpenEvidence} />)}
    {identityConflicts.filter((conflict) => (conflict.component_entity_ids ?? conflict.entity_ids).includes(selected.id)).map((conflict) => <IdentityConflictCard key={`${conflict.type}-${conflict.entity_ids.join('|')}`} conflict={conflict} graph={graph} claims={claims} evidence={evidenceRecords} live={live} facts={facts} onOpenEvidence={onOpenEvidence} />)}
    {facts.error && <div className="inline-error" role="alert"><AlertTriangle size={13} />{facts.error}</div>}
    {!identitySuggestions.some((suggestion) => suggestion.entity_ids.includes(selected.id)) && !identityConflicts.some((conflict) => (conflict.component_entity_ids ?? conflict.entity_ids).includes(selected.id)) && !identityGroups.some((group) => group.entity_ids.includes(selected.id)) && !(entityDetail?.aliases ?? graph.aliases ?? []).some((alias) => alias.entity_id === selected.id && alias.epistemic_state === 'rejected') && <p className="identity-empty">No identity suggestions or conflicts for this entity.</p>}
  </section>
}
