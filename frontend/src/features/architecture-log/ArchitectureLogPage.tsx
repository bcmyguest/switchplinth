// Architecture log page: each decision with its current choice, rationale, alternatives, rejection reasons, and consequences.
// Alternative previews go through the scenario selection, so the log and the What-if panel show the same temporary choice.
import { ArrowRight } from 'lucide-react'
import type { Page } from '../../app/navigation'
import { PageCard } from '../../app/PageCard'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import type { Evidence, GraphData } from '../../types'
import type { ScanState } from '../discovery/scanState'
import { evidenceHeading, evidencePath, resolveEvidence } from '../evidence/evidence'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import type { ScenarioSelection } from '../scenarios/useScenarioSelection'
import { DecisionConsequences, LogSourceLink, RejectionReason } from './DecisionReasons'

const BOX = 'grid min-w-0 gap-[7px] rounded-[7px] border p-[10px] max-sm:p-[9px]'
const BOX_LABEL = 'text-(length:--type-tertiary) text-[#435448] dark:text-(--theme-muted)'
const BODY_TEXT = 'm-0 text-(length:--type-secondary) leading-normal text-(--theme-muted) [overflow-wrap:anywhere]'

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
  return <PageCard>
    <div className="section-heading mb-[8px]"><div><div className="section-kicker">DECISION RECORDS</div><h2>Architecture log</h2></div><Button variant="link" onClick={() => navigateTo('Architecture')}>Open system map <ArrowRight size={13} /></Button></div>
    {graph.decisions.length ? <div className="grid gap-[10px]">{graph.decisions.map((decision) => {
      const selectedOptionId = displayedSelection[decision.id] ?? decision.selected_option
      const selectedOption = decision.options.find((option) => option.id === selectedOptionId)
      const selectedEvidence = selectedOption?.evidence?.map((reference) => resolveEvidence(reference, evidenceRecords)).find((item): item is Evidence => Boolean(item))
      const savedOptionId = repositorySelection.current[decision.id] ?? decision.selected_option
      const previewing = selectedOptionId !== savedOptionId
      const reasons = decision.derived?.rejection_reasons ?? {}
      const passage = { passageLabel: logPassageLabel, onOpenEvidence: openLogPassage }
      return <Card asChild key={decision.id} className="log-entry grid grid-cols-[12px_minmax(0,1fr)] gap-[10px] rounded-[8px] px-[12px] py-[14px] shadow-none max-sm:grid-cols-[10px_minmax(0,1fr)] max-sm:gap-[7px] max-sm:px-[8px]"><article><span className="decision-dot mt-[8px]" /><div className="grid min-w-0 gap-[9px] max-sm:gap-[8px]">
        <h3 className="m-0 mb-[5px] [font-family:Manrope,sans-serif] text-[16px] leading-[1.4] font-[650] text-(--theme-ink)">{decision.title}{decision.extraction_review && <Badge variant="warning" className="ml-[8px] align-middle">Delta review required</Badge>}</h3>
        <p className={BODY_TEXT}>{decision.context ?? 'Decision discovered in repository sources.'}</p>
        <section className={`log-selected-choice ${BOX} border-(--theme-brand) bg-(--theme-selected) text-(--theme-ink) dark:border-(--theme-line) dark:bg-(--theme-panel-raised)`} aria-label={`Current choice and rationale for ${decision.title}`}>
          <div className="flex flex-wrap items-baseline gap-x-[8px] gap-y-[4px] log-choice-heading"><strong className={BOX_LABEL}>Current choice</strong><span className="text-(length:--type-secondary) font-bold text-(--theme-ink)">{selectedOption?.title ?? 'No option selected'}</span></div>
          {selectedOption?.rationale && <p className={BODY_TEXT}>{selectedOption.rationale}</p>}
          {selectedEvidence && <LogSourceLink onOpen={() => openEvidenceDetail(selectedEvidence)}>Open cited passage · {evidencePath(selectedEvidence)} · {evidenceHeading(selectedEvidence)}</LogSourceLink>}
          {previewing && selectedOptionId && reasons[selectedOptionId] && <RejectionReason statement={reasons[selectedOptionId]} previewed {...passage} />}
        </section>
        <div className={`log-alternatives ${BOX} border-(--theme-line) bg-(--theme-panel-raised) text-(--theme-ink)`} aria-label={`Alternative choices for ${decision.title}`}><strong className={BOX_LABEL}>Alternatives and tradeoffs</strong>{decision.options.filter((option) => option.id !== selectedOptionId).map((option) => {
          const needsDeltaReview = decision.extraction_review?.rejected_options.some((item) => item.option_id === option.id) ?? false
          const optionEvidence = option.evidence?.map((reference) => resolveEvidence(reference, evidenceRecords)).find((item): item is Evidence => Boolean(item))
          return <div className="log-alternative grid gap-[5px] border-t border-(--theme-line) pt-[8px]" key={option.id}>
            <Button type="button" variant="choice" aria-pressed="false" className="justify-between text-(length:--type-secondary) font-[650] text-(--theme-source) disabled:bg-(--theme-panel-raised) disabled:text-(--theme-muted) max-sm:min-h-[44px] max-sm:w-full" disabled={scenarioResolutionPending || scanState === 'scanning'} onClick={() => { setActiveScenarioDecisionId(decision.id); void chooseOption(decision, option.id) }}>Preview {option.title}<ArrowRight size={12} /></Button>
            <Badge variant={needsDeltaReview ? 'warning' : option.id === savedOptionId ? 'secondary' : 'outline'} className={needsDeltaReview ? undefined : 'text-(--theme-muted)'}>{needsDeltaReview ? 'Delta review required' : option.id === savedOptionId ? 'Saved choice' : 'Alternative'}</Badge>
            {option.rationale && <p className={BODY_TEXT}>{option.rationale}</p>}
            {optionEvidence && <LogSourceLink onOpen={() => openEvidenceDetail(optionEvidence)}>Open cited passage · {evidencePath(optionEvidence)} · {evidenceHeading(optionEvidence)}</LogSourceLink>}
            {option.id !== savedOptionId && reasons[option.id] && <RejectionReason statement={reasons[option.id]} {...passage} />}
          </div>
        })}{!decision.options.some((option) => option.id !== selectedOptionId) && <p className={BODY_TEXT}>No alternatives are recorded.</p>}</div>
        {decision.derived?.consequences.length ? <DecisionConsequences statements={decision.derived.consequences} previewing={previewing} {...passage} /> : null}
        <Button variant="link" className="justify-self-start px-0" onClick={() => exploreDecision(decision.id)}>Explore full scenario <ArrowRight size={13} /></Button>
      </div></article></Card>
    })}</div> : <div className="empty-state">No decisions are available yet. Discover decisions from repository Markdown.</div>}
  </PageCard>
}
