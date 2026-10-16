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
              {!isActive && <Button type="button" variant="secondary" size="sm" className="linked-option-preview" disabled={disabled} onClick={() => onChooseOption(decision.id, option.id)}>Preview this option</Button>}
              {option.rationale && <p className="linked-option-rationale">{option.rationale}</p>}
              {source && <button type="button" className="linked-evidence" title={`${evidencePath(source)} · ${evidenceHeading(source)}`} aria-label={`Open source passage ${evidencePath(source)}, ${evidenceHeading(source)}`} onClick={() => onOpenEvidence(source)}><FileText size={12} /><span>Open passage · {evidencePath(source)}</span><ArrowUpRight size={12} /></button>}
            </div>
          })}
        </div>
        <button type="button" className="linked-decision-explore" onClick={() => onExploreDecision(decision.id)}>Explore alternatives <ArrowRight size={13} /></button>
      </article>
    })}
  </div>
}
