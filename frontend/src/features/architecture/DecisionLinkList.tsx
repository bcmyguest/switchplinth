// Linked decisions for a selected component: each option with its state, rationale, preview action, and source passage.
import { ArrowRight, ArrowUpRight, FileText } from 'lucide-react'
import { Button } from '../../components/ui/button'
import type { Decision, Evidence, Option } from '../../types'
import { evidenceHeading, evidencePath, resolveEvidence } from '../evidence/evidence'
import { compactScenarioDecisionTitle } from '../scenarios/scenarioSelection'

/** A decision linked to the selected component; `relatedBy` names the candidate identity link when the link is indirect. */
type LinkedDecision = { id: string; title: string; selected_option?: Option | null; options: Option[]; relatedBy?: string; extraction_review?: Decision['extraction_review'] }

type DecisionLinkListProps = {
  decisions: LinkedDecision[]
  evidence: Evidence[]
  onOpenEvidence: (item: Evidence) => void
  onChooseOption: (decisionId: string, optionId: string) => void
  onExploreDecision: (decisionId: string) => void
  disabled?: boolean
}

export function DecisionLinkList({ decisions, evidence, onOpenEvidence, onChooseOption, onExploreDecision, disabled = false }: DecisionLinkListProps) {
  if (!decisions.length) return <div className="linked-decisions empty">No linked decisions were found for this component.</div>
  return <div className="linked-decisions">
    <div className="linked-decisions-title">LINKED DECISIONS <span>{decisions.length}</span></div>
    {decisions.map((decision) => {
      const activeOption = decision.selected_option
      const options = decision.options
      const decisionScope = compactScenarioDecisionTitle(decision.title).replace(/^[^:]+:\s*/, '').trim()
      return <article className="linked-decision" key={decision.id}>
        <div className="linked-decision-heading"><strong>{decision.title}</strong><span className="linked-option-state">{activeOption ? 'Current choice shown' : 'No current choice'}</span></div>
        {decision.relatedBy && <p className="linked-decision-relation">Related through {decision.relatedBy}. Candidate links do not merge entity records.</p>}
        <div className="linked-option-list" aria-label={`Options for ${decision.title}`}>
          {options.map((option) => {
            const isActive = option.id === activeOption?.id
            const needsDeltaReview = decision.extraction_review?.rejected_options.some((item) => item.option_id === option.id) ?? false
            const source = option.evidence?.map((reference) => resolveEvidence(reference, evidence)).find((item): item is Evidence => Boolean(item))
            return <div className={`linked-option-card ${isActive ? 'active' : 'alternative'}`} key={option.id}>
              <div className="linked-option-heading"><span className="linked-option">{option.title}</span><span className="linked-option-state">{isActive ? `Selected for ${decisionScope}` : `Alternative for ${decisionScope}`}{needsDeltaReview ? ' · review required' : ''}</span></div>
              {!isActive && <Button type="button" variant="choice" size="sm" className="block justify-self-start bg-(--theme-panel-raised) py-[5px] text-center text-(length:--type-tertiary) font-[650] disabled:text-(--theme-muted) disabled:opacity-75 max-sm:w-full" disabled={disabled} onClick={() => onChooseOption(decision.id, option.id)}>Preview this option</Button>}
              {option.rationale && <p className="linked-option-rationale">{option.rationale}</p>}
              {source && <Button type="button" variant="ghost" className="flex min-h-[30px] w-full items-start gap-[5px] px-0 py-[4px] text-left text-[11px] leading-[1.3] text-(--theme-ink) max-sm:min-h-(--control-target) max-sm:text-(length:--type-tertiary) [&>span]:min-w-0 [&>span]:flex-1 [&>span]:text-(length:--type-tertiary) [&>span]:[overflow-wrap:anywhere] [&>svg]:mt-px [&>svg]:flex-none" title={`${evidencePath(source)} · ${evidenceHeading(source)}`} aria-label={`Open source passage ${evidencePath(source)}, ${evidenceHeading(source)}`} onClick={() => onOpenEvidence(source)}><FileText size={12} /><span>Open passage · {evidencePath(source)}</span><ArrowUpRight size={12} /></Button>}
            </div>
          })}
        </div>
        <Button type="button" variant="ghost" className="mt-[7px] inline-flex min-h-[36px] items-center gap-[5px] p-0 text-(length:--type-tertiary) whitespace-nowrap text-(--theme-ink) [&>svg]:flex-none" onClick={() => onExploreDecision(decision.id)}>Explore alternatives <ArrowRight size={13} /></Button>
      </article>
    })}
  </div>
}
