// Architecture log page: each decision with its current choice, rationale, alternatives, rejection reasons, and consequences.
// Alternative previews go through the scenario selection, so the log and the What-if panel show the same temporary choice.
import { ArrowRight, ArrowUpRight, FileText } from 'lucide-react'
import type { Page } from '../../app/navigation'
import type { Evidence, GraphData } from '../../types'
import type { ScanState } from '../discovery/scanState'
import { evidenceHeading, evidencePath, resolveEvidence } from '../evidence/evidence'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import type { ScenarioSelection } from '../scenarios/useScenarioSelection'
import { DecisionConsequences, RejectionReason } from './DecisionReasons'

type ArchitectureLogPageProps = {
  graph: GraphData
  scenario: ScenarioSelection
  evidenceRecords: Evidence[]
  evidence: Pick<EvidenceViewer, 'open' | 'passageLabel' | 'openPassage'>
  scanState: ScanState
  onExploreDecision: (decisionId: string) => void
  navigateTo: (page: Page) => void
}

export function ArchitectureLogPage({ graph, scenario, evidenceRecords, evidence, scanState, onExploreDecision: exploreDecision, navigateTo }: ArchitectureLogPageProps) {
  const { displayed: displayedSelection, baseline: repositorySelection, pending: scenarioResolutionPending, setActiveDecisionId: setActiveScenarioDecisionId, choose: chooseOption } = scenario
  const { open: openEvidenceDetail, passageLabel: logPassageLabel, openPassage: openLogPassage } = evidence
  return <section className="page-card page-list"><div className="section-heading"><div><div className="section-kicker">DECISION RECORDS</div><h2>Architecture log</h2></div><button className="text-button" onClick={() => navigateTo('Architecture')}>Open system map <ArrowRight size={13} /></button></div>{graph.decisions.length ? graph.decisions.map((decision) => {
    const selectedOptionId = displayedSelection[decision.id] ?? decision.selected_option
    const selectedOption = decision.options.find((option) => option.id === selectedOptionId)
    const selectedEvidence = selectedOption?.evidence?.map((reference) => resolveEvidence(reference, evidenceRecords)).find((item): item is Evidence => Boolean(item))
    const savedOptionId = repositorySelection.current[decision.id] ?? decision.selected_option
    const previewing = selectedOptionId !== savedOptionId
    const reasons = decision.derived?.rejection_reasons ?? {}
    const passage = { passageLabel: logPassageLabel, onOpenEvidence: openLogPassage }
    return <article className="log-entry" key={decision.id}><span className="decision-dot" /><div className="log-entry-content"><h3>{decision.title}{decision.extraction_review && <span className="review-status inferred">Delta review required</span>}</h3><p>{decision.context ?? 'Decision discovered in repository sources.'}</p>
      <section className="log-selected-choice" aria-label={`Current choice and rationale for ${decision.title}`}><div className="log-choice-heading"><strong>Current choice</strong><span>{selectedOption?.title ?? 'No option selected'}</span></div>{selectedOption?.rationale && <p>{selectedOption.rationale}</p>}{selectedEvidence && <button type="button" className="log-source-link" onClick={() => openEvidenceDetail(selectedEvidence)}><FileText size={13} />Open cited passage · {evidencePath(selectedEvidence)} · {evidenceHeading(selectedEvidence)}<ArrowUpRight size={13} /></button>}{previewing && selectedOptionId && reasons[selectedOptionId] && <RejectionReason statement={reasons[selectedOptionId]} previewed {...passage} />}</section>
      <div className="log-alternatives" aria-label={`Alternative choices for ${decision.title}`}><strong>Alternatives and tradeoffs</strong>{decision.options.filter((option) => option.id !== selectedOptionId).map((option) => {
        const needsDeltaReview = decision.extraction_review?.rejected_options.some((item) => item.option_id === option.id) ?? false
        const optionEvidence = option.evidence?.map((reference) => resolveEvidence(reference, evidenceRecords)).find((item): item is Evidence => Boolean(item))
        return <div className="log-alternative" key={option.id}><button type="button" aria-pressed="false" disabled={scenarioResolutionPending || scanState === 'scanning'} onClick={() => { setActiveScenarioDecisionId(decision.id); void chooseOption(decision, option.id) }}>Preview {option.title}<ArrowRight size={12} /></button><span>{needsDeltaReview ? 'Delta review required' : option.id === savedOptionId ? 'Saved choice' : 'Alternative'}</span>{option.rationale && <p>{option.rationale}</p>}{optionEvidence && <button type="button" className="log-source-link" onClick={() => openEvidenceDetail(optionEvidence)}><FileText size={13} />Open cited passage · {evidencePath(optionEvidence)} · {evidenceHeading(optionEvidence)}<ArrowUpRight size={13} /></button>}{option.id !== savedOptionId && reasons[option.id] && <RejectionReason statement={reasons[option.id]} {...passage} />}</div>
      })}{!decision.options.some((option) => option.id !== selectedOptionId) && <p>No alternatives are recorded.</p>}</div>
      {decision.derived?.consequences.length ? <DecisionConsequences statements={decision.derived.consequences} previewing={previewing} {...passage} /> : null}
      <button className="text-button log-explore" onClick={() => exploreDecision(decision.id)}>Explore full scenario <ArrowRight size={13} /></button>
    </div></article>
  }) : <div className="empty-state">No decisions are available yet. Discover decisions from repository Markdown.</div>}</section>
}
