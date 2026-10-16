// Explore page: the decision assistant with ask/propose modes, the proposal target pickers, the grounded answer with
// supporting and related claims and cited passages, the proposed delta, the query input, and suggested questions.
import { stringify } from 'yaml'
import { AlertTriangle, ArrowRight, Bot, Check, FileText, LoaderCircle, MessageCircle, Search, Sparkles } from 'lucide-react'
import type { SearchEvidence } from '../../api'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import type { Claim, GraphData } from '../../types'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import type { DeltaEditor } from '../graph-editor/useDeltaEditor'
import type { Explore } from './useExplore'

const ANSWER_CARD = 'mb-[9px] block! rounded-[8px] text-[12px] border-(--theme-line) p-[11px] shadow-none'
const CLAIM_STATE_VARIANT = { inferred: 'warning', rejected: 'destructive', confirmed: 'secondary', asserted: 'secondary' } as const

type ExplorePageProps = {
  explore: Explore
  graph: GraphData
  live: boolean
  /** The displayed scenario selection, summarized above the conversation. */
  displayedSelection: Record<string, string>
  editor: Pick<DeltaEditor, 'decisionId' | 'optionId' | 'chooseDecision' | 'chooseOption'>
  onOpenSearchPassage: EvidenceViewer['openSearchPassage']
}

export function ExplorePage({ explore, graph, live, displayedSelection, editor, onOpenSearchPassage: openSearchPassage }: ExplorePageProps) {
  const { query, setQuery, mode: chatMode, setMode: setChatMode, answer, proposal, proposalError, searching } = explore
  const { decisionId: editingDecisionId, optionId: editingOptionId, chooseDecision: updateEditorDecision, chooseOption: updateEditorOption } = editor
  const scenarioContext = graph.decisions.map((decision) => `${decision.title}: ${decision.options.find((option) => option.id === displayedSelection[decision.id])?.title ?? 'unselected'}`).join(' · ')
  const supportingAnswerClaims = answer?.claims.filter((claim) => answer.whyQuery || (claim.evidence ?? []).some((id) => answer.evidence.some((item) => item.id === id))) ?? []
  const relatedAnswerClaims = answer?.claims.filter((claim) => !supportingAnswerClaims.includes(claim)) ?? []
  function renderAnswerClaim(claim: Claim, category: 'supporting' | 'related') {
    if (!answer) return null
    const citedEvidence = (claim.evidence ?? []).map((id) => answer.evidence.find((item) => item.id === id)).filter((item): item is SearchEvidence => Boolean(item))
    const sourcePath = citedEvidence[0]?.path ?? citedEvidence[0]?.source ?? claim.source_path
    const endpointName = (id: string) => graph.entities.find((entity) => entity.id === id)?.name ?? answer.inactiveEntities.find((entity) => entity.id === id)?.name ?? id
    return <Card asChild key={claim.id} className="answer-claim gap-[4px] [.answer-claim+&]:mt-[6px] rounded-[6px] border-(--theme-line) bg-(--theme-panel-raised) px-[9px] py-[8px] shadow-none [overflow-wrap:anywhere]"><article><strong>{endpointName(claim.subject)} · {claim.predicate.replaceAll('_', ' ')} · {endpointName(claim.object)}</strong><div className="flex flex-wrap items-center gap-[6px]"><Badge variant={category === 'supporting' ? 'secondary' : 'outline'} className="answer-claim-kind">{category === 'supporting' ? 'Supports this answer' : 'Related claim'}</Badge><Badge variant={CLAIM_STATE_VARIANT[claim.epistemic_state]}>{claim.epistemic_state}</Badge><span className="text-(length:--type-caption) text-(--theme-muted)">{Math.round(claim.confidence * 100)}% confidence</span></div>{sourcePath && <small>Source: {sourcePath}</small>}{citedEvidence.map((source, index) => <blockquote key={`${source.id ?? source.source}-${index}`}>{source.text ?? source.passage}</blockquote>)}</article></Card>
  }

  return <div className="chat-area" id="decision-assistant">
    <div className="chat-intro"><div className="chat-spark"><Sparkles size={16} /></div><div><h3>Decision assistant</h3><p>Ask a grounded question or propose a change to one option's delta.</p><small>Current scenario: {scenarioContext || 'no decisions selected'}</small></div></div>
    <div className="chat-mode-toolbar"><div className="chat-mode-switch"><button className={chatMode === 'ask' ? 'active' : ''} onClick={() => setChatMode('ask')}><Search size={12} /> Ask</button><button className={chatMode === 'propose' ? 'active' : ''} disabled={!live || graph.decisions.length === 0} onClick={explore.startPropose}><Sparkles size={12} /> Propose a delta</button></div>{chatMode === 'propose' && <div className="proposal-target"><Select aria-label="Target decision" value={editingDecisionId} onChange={(event) => updateEditorDecision(event.target.value)}>{graph.decisions.map((decision) => <option key={decision.id} value={decision.id}>{decision.title}</option>)}</Select><Select aria-label="Target option" value={editingOptionId} onChange={(event) => updateEditorOption(event.target.value)}>{graph.decisions.find((decision) => decision.id === editingDecisionId)?.options.map((option) => <option key={option.id} value={option.id}>{option.title}</option>)}</Select></div>}</div>
    {answer && <>
      <div className="answer-announcement" role="status" aria-live="polite" aria-atomic="true">{answer.text}</div>
      <Card className={`answer-card ${ANSWER_CARD}`}>
        <div className="answer-label"><Bot size={14} /> {answer.kind === 'error' ? 'REQUEST FAILED' : answer.grounded ? 'ANSWER · GROUNDED' : answer.claims.length ? 'CLAIMS · NO CURRENT EVIDENCE' : answer.evidence.length ? 'PASSAGES · NO SUPPORTING CLAIM' : 'NO SUPPORTING EVIDENCE'}{answer.grounded && <><span>·</span> {answer.evidence.length} source{answer.evidence.length === 1 ? '' : 's'}</>}</div>
        <p>{answer.text}</p>
        {supportingAnswerClaims.length > 0 && <section className="answer-claims" aria-label="Supporting claims"><h4>Supporting claims</h4>{supportingAnswerClaims.map((claim) => renderAnswerClaim(claim, 'supporting'))}</section>}
        {relatedAnswerClaims.length > 0 && <section className="answer-claims" aria-label="Related claims"><h4>Related claims</h4>{relatedAnswerClaims.map((claim) => renderAnswerClaim(claim, 'related'))}</section>}
        {answer.evidence.length > 0 && <section className="answer-passages" aria-label="Answer passages">{answer.claims.length > 0 && <h4>Passages</h4>}{answer.evidence.map((source, index) => { const heading = Array.isArray(source.heading) ? source.heading.join(' / ') : source.heading ?? source.location?.heading_path?.join(' / ') ?? 'Passage'; return <button type="button" className="answer-source" key={`${source.id ?? source.path ?? source.source}-${index}`} aria-label={`Open passage ${source.path ?? source.source ?? 'source document'} ${heading}`} onClick={() => openSearchPassage(source)} disabled={!source.path && !source.source}><FileText size={13} /><strong>{source.path ?? source.source ?? 'Source document'}</strong><span>{heading}</span><blockquote>{source.passage ?? source.text}</blockquote></button>})}</section>}
      </Card>
    </>}
    {proposal && <Card className={`answer-card proposal-card ${ANSWER_CARD}`}><div className="answer-label"><Sparkles size={14} /> PROPOSED DELTA · NOT SAVED</div><p>{proposal.rationale ?? 'Review the proposed operations before applying them.'}</p><pre>{stringify(proposal.delta)}</pre>{proposal.warnings?.map((warning) => <div className="proposal-warning" key={warning}><AlertTriangle size={12} />{warning}</div>)}{proposalError && <div className="inline-error"><AlertTriangle size={13} />{proposalError}</div>}<div className="proposal-actions"><Button type="button" variant="secondary" className="button subtle" onClick={explore.discardProposal}>Discard</Button><Button type="button" className="button primary" disabled={searching} onClick={() => void explore.applyProposal()}>{searching ? <LoaderCircle className="spin" size={13} /> : <Check size={13} />} Apply to option</Button></div></Card>}
    <form className="chat-input" onSubmit={(event) => void explore.submit(event)}><MessageCircle size={16} /><Input className="min-h-0 flex-1 border-0 bg-transparent px-0 py-0 text-(length:--type-secondary)! shadow-none" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={chatMode === 'ask' ? 'Why are we using Kafka?' : 'Replace Kafka with SQS and add a dead letter queue'} /><kbd>↵</kbd><button type="submit" aria-label={chatMode === 'ask' ? 'Ask' : 'Propose delta'} disabled={searching || (chatMode === 'propose' && !live)}>{searching ? <LoaderCircle className="spin" size={16} /> : chatMode === 'ask' ? <ArrowRight size={16} /> : <Sparkles size={15} />}</button></form>
    {chatMode === 'ask' && <div className="suggestions"><span>Try asking</span><button onClick={() => setQuery('What depends on Kafka?')}>What depends on Kafka?</button><button onClick={() => setQuery('Which decisions mention replay?')}>Which decisions mention replay?</button><button onClick={() => setQuery('What changes if we choose SQS?')}>What changes if we choose SQS?</button></div>}
  </div>
}
