// Selected-component overlay: the component heading and state, its rationale and source passage when no decision links it,
// its linked decisions with preview controls, and its identity review. The section stays mounted; `is-open` shows it.
import type { RefObject } from 'react'
import { ArrowUpRight, FileText, GitPullRequest, Sparkles, X } from 'lucide-react'
import type { GraphData } from '../../types'
import type { ScanState } from '../discovery/scanState'
import { evidenceHeading, evidencePath } from '../evidence/evidence'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import { IdentityReviewSection } from '../facts/IdentityReviewSection'
import type { FactsReview } from '../facts/useFactsReview'
import type { ScenarioSelection } from '../scenarios/useScenarioSelection'
import type { ComponentDetail } from './componentDetail'
import { DecisionLinkList } from './DecisionLinkList'

type ComponentDetailOverlayProps = {
  /** True while the detail panel is the open Architecture overlay panel; it then owns `panelRef`. */
  panelOpen: boolean
  panelRef: RefObject<HTMLElement | null>
  onClose: () => void
  onOpenScenario: () => void
  detail: ComponentDetail
  graph: GraphData
  live: boolean
  scenario: ScenarioSelection
  facts: FactsReview
  onOpenEvidence: EvidenceViewer['open']
  onExploreDecision: (decisionId: string) => void
  scanState: ScanState
}

export function ComponentDetailOverlay({ panelOpen, panelRef, onClose, onOpenScenario, detail, graph, live, scenario, facts, onOpenEvidence, onExploreDecision, scanState }: ComponentDetailOverlayProps) {
  const { selected, entityDetail, evidenceRecords, linkedDecisions, rationaleLabel, rationale, evidence } = detail
  return <section className={`graph-selection-summary ${panelOpen ? 'is-open' : ''}`} ref={(element) => { if (panelOpen) panelRef.current = element }} aria-live="polite" aria-label="Selected component details" role="dialog" aria-modal="false" aria-labelledby="selected-component-title">
  {selected ? <>
    <div className="selection-summary-heading"><div><div className="panel-kicker">SELECTED COMPONENT · {selected.kind.toUpperCase()}</div><h3 id="selected-component-title">{selected.name}</h3></div><button className="icon-button" aria-label="Close component details" onClick={onClose}><X size={15} /></button><span className={`state-tag ${selected.epistemic_state ?? 'inferred'}`}><i />{selected.epistemic_state ?? 'inferred'}{selected.confidence ? ` · ${Math.round(selected.confidence * 100)}%` : ''}</span></div>
    {!linkedDecisions.length && <><div className="selection-summary-rationale"><strong><Sparkles size={13} /> {rationaleLabel}</strong><p>{rationale}</p></div><button className="linked-evidence selection-summary-evidence" disabled={!evidence} onClick={(event) => onOpenEvidence(evidence, event.currentTarget)}><FileText size={14} /><span><strong>Open passage</strong><small>{evidence ? `${evidencePath(evidence)} · ${evidenceHeading(evidence)}` : 'No source passage linked'}</small></span><ArrowUpRight size={14} /></button></>}
    <DecisionLinkList decisions={linkedDecisions} evidence={evidenceRecords} onOpenEvidence={onOpenEvidence} onChooseOption={(decisionId, optionId) => { const decision = graph.decisions.find((item) => item.id === decisionId); if (decision) void scenario.choose(decision, optionId) }} onExploreDecision={onExploreDecision} disabled={scenario.pending || scanState === 'scanning'} />
    {linkedDecisions.length > 0 && <button type="button" className="text-button selection-return-scenario" onClick={onOpenScenario}><GitPullRequest size={13} /> Open full What-if scenario</button>}
    <IdentityReviewSection selected={selected} graph={graph} entityDetail={entityDetail} evidenceRecords={evidenceRecords} live={live} facts={facts} onOpenEvidence={onOpenEvidence} />
  </> : <div className="empty-state">Choose a component in the map to inspect it.</div>}
</section>
}
