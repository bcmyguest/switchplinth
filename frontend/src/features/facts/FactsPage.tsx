// Facts page: the identity review (groups, direct and rejected candidates, conflicts), the claim and alias review rows with
// their correction form, and the review log. The page stays mounted and hidden off-page so form state survives navigation.
import { ArrowRight, Check, Code2, FileText, LoaderCircle, X } from 'lucide-react'
import type { Page } from '../../app/navigation'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { Input } from '../../components/ui/input'
import type { Evidence, GraphData } from '../../types'
import { evidenceHeading, evidencePath, evidenceText } from '../evidence/evidence'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import { ReviewLogPanel } from '../review-log/ReviewLogPanel'
import { InlineError } from '../../components/InlineError'
import { IdentityConflictCard, IdentityGroupCard, IdentitySuggestionCard } from './IdentityReviewSection'
import { STRUCTURAL_PREDICATES } from './reviewQueue'
import type { FactsReview } from './useFactsReview'
import { Select } from '../../components/ui/select'

/** Correction fields keep the form's compact monospace look. */
const CORRECTION_INPUT = 'rounded-[4px] px-[7px] py-0 text-(length:--type-tertiary) [font-family:"DM_Mono",monospace]'

type FactsPageProps = {
  /** True on the Facts page. The review block stays mounted with `display: none` elsewhere. */
  active: boolean
  graph: GraphData
  live: boolean
  facts: FactsReview
  evidenceRecords: Evidence[]
  onOpenEvidence: EvidenceViewer['open']
  onReviewLogChanged: () => Promise<void>
  navigateTo: (page: Page) => void
}

/** Review row actions keep their `.review-actions button` styling; the Button supplies the element. */
const REVIEW_ACTION = 'min-h-0 p-0'
const CORRECTION_SELECT = 'w-full rounded-[4px] border border-(--theme-line) bg-(--theme-panel) px-[7px] font-[\'DM_Mono\',monospace] text-(length:--type-tertiary) text-(--theme-ink)'

export function FactsPage({ active, graph, live, facts, evidenceRecords, onOpenEvidence, onReviewLogChanged, navigateTo }: FactsPageProps) {
  const identityGroups = graph.identity_groups ?? []
  const identitySuggestions = graph.identity_suggestions ?? []
  const identityConflicts = graph.identity_conflicts ?? []
  const { reviewItems, pendingCount, directIdentitySuggestions, rejectedIdentitySuggestions, visibleIdentitySuggestions, visibleIdentityConflicts, visibleReviewItems } = facts.queue
  const { filter: factsFilter, setFilter: setFactsFilter, knownEntities: knownEntityChoices, correctionBusy, correctionError } = facts
  const { id: correctionId, draft: correctionDraft, setDraft: setCorrectionDraft } = facts.correction
  return <>
    {active && <div className="section-heading review-heading" id="review-section"><div><div className="section-kicker">HUMAN IN THE LOOP</div><h2>Needs a closer look <span>{pendingCount}</span></h2></div><div className="flex flex-wrap items-center justify-end gap-[10px]"><Button variant="link" onClick={() => document.getElementById('review-log')?.scrollIntoView({ block: 'start' })}>Review log</Button><Button variant="link" onClick={() => navigateTo('Architecture')}>Open system map <ArrowRight size={13} /></Button></div></div>}
    <div style={{ display: active ? undefined : 'none' }}>
    <p className="facts-intro">Review direct identity candidates, earlier rejected judgments, and conflicts separately. Identity suggestions cover the whole graph, even when the selected component has no local candidates.</p>
    <nav className="facts-filters" aria-label="Filter facts for review">{[
      ['all', `All · ${reviewItems.length + identitySuggestions.length + identityConflicts.length}`],
      ['direct', `Direct candidates · ${directIdentitySuggestions.length}`],
      ['rejected', `Previously rejected · ${rejectedIdentitySuggestions.length}`],
      ['conflicts', `Conflicts · ${identityConflicts.length}`],
      ['claims', `Claims · ${reviewItems.filter((item) => item.type === 'claim').length}`],
      ['aliases', `Aliases · ${reviewItems.filter((item) => item.type === 'alias').length}`],
    ].map(([filter, label]) => <Button type="button" variant={factsFilter === filter ? 'secondary' : 'ghost'} size="sm" key={filter} aria-pressed={factsFilter === filter} onClick={() => setFactsFilter(filter as typeof factsFilter)}>{label}</Button>)}</nav>
    <Card asChild className="identity-facts mb-[12px] grid! gap-[8px] rounded-[8px] bg-(--theme-panel-raised) p-[12px] shadow-none max-sm:p-[9px]"><section aria-labelledby="identity-facts-title">
      <div className="identity-review-heading"><strong id="identity-facts-title">{factsFilter === 'rejected' ? 'Previously rejected identity judgments' : factsFilter === 'conflicts' ? 'Identity conflicts' : 'Entity identity'}</strong><span>Separate from alias review</span></div>
      {identityGroups.length > 0 && <div className="identity-groups-list">{identityGroups.map((group) => <IdentityGroupCard key={group.entity_ids.join('|')} group={group} graph={graph} />)}</div>}
      {visibleIdentitySuggestions.length > 0 && <h3 className="facts-group-label">{factsFilter === 'rejected' ? 'Previously rejected' : 'Direct candidates'}</h3>}
      {visibleIdentitySuggestions.map((suggestion) => <IdentitySuggestionCard key={`facts-${suggestion.source}-${suggestion.entity_ids[0]}-${suggestion.entity_ids[1]}-${suggestion.claim_id ?? ''}`} suggestion={suggestion} graph={graph} claims={graph.claims ?? []} evidenceRecords={evidenceRecords} live={live} facts={facts} onOpenEvidence={onOpenEvidence} />)}
      {visibleIdentityConflicts.length > 0 && <h3 className="facts-group-label">Conflicts that need review</h3>}
      {visibleIdentityConflicts.map((conflict) => <IdentityConflictCard key={`facts-${conflict.type}-${conflict.entity_ids.join('|')}`} conflict={conflict} graph={graph} claims={graph.claims ?? []} evidence={graph.evidence ?? []} live={live} facts={facts} onOpenEvidence={onOpenEvidence} />)}
      {facts.error && <InlineError message={facts.error} />}
      {!visibleIdentitySuggestions.length && !visibleIdentityConflicts.length && !identityGroups.length && <p className="identity-empty">{factsFilter === 'direct' ? 'No direct identity candidates need review.' : factsFilter === 'rejected' ? 'No previously rejected identity judgments.' : factsFilter === 'conflicts' ? 'No identity conflicts need review.' : 'No identity suggestions, conflicts, or confirmed groups.'}</p>}
    </section></Card>
    {visibleReviewItems.length > 0 && <h3 className="facts-group-label">{factsFilter === 'aliases' ? 'Alias review' : factsFilter === 'claims' ? 'Claims and relationships' : 'Claims and aliases'}</h3>}
    <div className="grid gap-[8px]">{visibleReviewItems.length ? visibleReviewItems.map((item) => {
      const claim = item.type === 'claim' ? graph.claims?.find((candidate) => candidate.id === item.id) : undefined
      const alias = item.type === 'alias' ? graph.aliases?.find((candidate) => candidate.id === item.id) : undefined
      const evidenceRefs = alias?.evidence ?? claim?.evidence ?? []
      const evidenceItems = evidenceRefs.map((reference) => typeof reference === 'string' ? graph.evidence?.find((evidence) => evidence.id === reference) : reference).filter((evidence): evidence is Evidence => Boolean(evidence))
      return <Card className="review-item min-h-[60px] flex-row! items-center gap-[12px] rounded-[8px] px-[12px] py-[10px] shadow-none max-sm:flex-wrap max-sm:items-start" key={`${item.type}-${item.id}`}>
        <div className={`review-confidence ${item.status}`}><span>{Math.round(item.confidence * 100)}%</span></div>
        <div className="review-copy"><strong>{item.name}</strong><span>{item.detail}</span>{evidenceItems[0] ? <Button variant="ghost" className="flex max-w-full items-start gap-[5px] px-0 py-[2px] text-left text-(length:--type-tertiary) leading-[1.4] text-(--theme-source) [overflow-wrap:anywhere] [&>svg]:mt-px [&>svg]:flex-none" onClick={() => onOpenEvidence(evidenceItems[0])}><FileText size={12} />Open passage · {evidencePath(evidenceItems[0])} · {evidenceHeading(evidenceItems[0])}</Button> : <small>No source passage linked</small>}</div>
        <span className={`review-status ${item.status}`}>{item.status}</span>
        <div className="review-actions"><Button variant="ghost" className={REVIEW_ACTION} disabled={!live} aria-label={`${item.status === 'confirmed' ? 'Reaffirm' : 'Confirm'} ${item.type}`} title={`${item.status === 'confirmed' ? 'Reaffirm' : 'Confirm'} ${item.type}`} onClick={() => facts.mark(item.id, 'confirmed')}><Check size={14} /></Button><Button variant="ghost" className={REVIEW_ACTION} disabled={!live} aria-label={`${item.status === 'rejected' ? 'Reaffirm rejection of' : 'Reject'} ${item.type}`} title={`${item.status === 'rejected' ? 'Reaffirm rejection of' : 'Reject'} ${item.type}`} onClick={() => facts.mark(item.id, 'rejected')}><X size={14} /></Button><Button variant="ghost" className={REVIEW_ACTION} disabled={!live} aria-label={`Correct ${item.type}`} title={`Correct ${item.type}`} onClick={() => correctionId === item.id ? facts.correction.close() : facts.correction.open(item)}><Code2 size={13} /></Button></div>
        {correctionId === item.id && <div className="correction-form">
          <strong>Correct interpretation</strong><p>This saves a new asserted record linked to this record family; source evidence and earlier records are preserved.</p>
          {evidenceItems.length ? <div className="correction-evidence">{evidenceItems.map((evidence) => <blockquote key={evidence.id}><span>{evidencePath(evidence)} · {evidenceHeading(evidence)}</span>{evidenceText(evidence)}</blockquote>)}</div> : <div className="correction-evidence empty">No source passage is attached to this record.</div>}
          {item.type === 'alias' ? <><label>Alias name<Input className={CORRECTION_INPUT} value={correctionDraft.name} onChange={(event) => setCorrectionDraft({ ...correctionDraft, name: event.target.value })} /></label><label>Refers to entity<Select className={CORRECTION_SELECT} value={correctionDraft.entity_id} onChange={(event) => setCorrectionDraft({ ...correctionDraft, entity_id: event.target.value })}>{knownEntityChoices.map((entity) => <option key={entity.id} value={entity.id}>{entity.name} · {entity.id}</option>)}</Select></label></> : <>
            <label>Subject {STRUCTURAL_PREDICATES.has(correctionDraft.predicate) ? 'entity' : 'or decision ID'}{STRUCTURAL_PREDICATES.has(correctionDraft.predicate) ? <Select className={CORRECTION_SELECT} value={correctionDraft.subject} onChange={(event) => setCorrectionDraft({ ...correctionDraft, subject: event.target.value })}>{knownEntityChoices.map((entity) => <option key={entity.id} value={entity.id}>{entity.name} · {entity.id}</option>)}</Select> : <Input className={CORRECTION_INPUT} list={`correction-values-${item.id}`} value={correctionDraft.subject} onChange={(event) => setCorrectionDraft({ ...correctionDraft, subject: event.target.value })} />}</label>
            <label>Predicate<Input className={CORRECTION_INPUT} list={`correction-predicates-${item.id}`} value={correctionDraft.predicate} onChange={(event) => facts.correction.updatePredicate(event.target.value)} placeholder="publishes_to" /><datalist id={`correction-predicates-${item.id}`}><option value="uses" /><option value="publishes_to" /><option value="calls" /><option value="depends_on" /><option value="stores_in" /><option value="communicates_with" /><option value="implements" /><option value="mentioned_in" /><option value="requires" /><option value="consequence" /></datalist></label>
            <label>Object {STRUCTURAL_PREDICATES.has(correctionDraft.predicate) ? 'entity' : 'or descriptive value'}{STRUCTURAL_PREDICATES.has(correctionDraft.predicate) ? <Select className={CORRECTION_SELECT} value={correctionDraft.object} onChange={(event) => setCorrectionDraft({ ...correctionDraft, object: event.target.value })}>{knownEntityChoices.map((entity) => <option key={entity.id} value={entity.id}>{entity.name} · {entity.id}</option>)}</Select> : <Input className={CORRECTION_INPUT} list={`correction-values-${item.id}`} value={correctionDraft.object} onChange={(event) => setCorrectionDraft({ ...correctionDraft, object: event.target.value })} />}</label>
            <datalist id={`correction-values-${item.id}`}>{knownEntityChoices.map((entity) => <option key={entity.id} value={entity.id} label={entity.name} />)}{graph.decisions.map((decision) => <option key={decision.id} value={decision.id} label={decision.title} />)}</datalist>
          </>}
          {correctionError && <InlineError message={correctionError} />}
          <div className="form-actions"><Button variant="subtle" disabled={correctionBusy} onClick={() => facts.correction.close()}>Cancel</Button><Button className="text-(length:--type-tertiary)" disabled={!live || correctionBusy} onClick={() => void facts.correction.save(item)}>{correctionBusy ? <LoaderCircle className="spin" size={13} /> : <Check size={13} />} Save asserted correction</Button></div>
        </div>}
      </Card>
    }) : factsFilter === 'claims' || factsFilter === 'aliases' ? <div className="empty-state">{factsFilter === 'claims' ? 'No claims or relationships match this filter.' : 'No aliases match this filter.'}</div> : identitySuggestions.length > 0 || identityConflicts.length > 0 ? null : <div className="empty-state">{live ? 'No claim, alias, or identity reviews are waiting.' : 'Reviewable claims and aliases appear after the backend scans your repository.'}</div>}</div>

    {active && <ReviewLogPanel live={live} revision={graph} onChanged={onReviewLogChanged} />}
    </div>
  </>
}
