import { ArrowUpRight, FileText } from 'lucide-react'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import type { SourceStatement } from '../../types'

const REJECTION_LABEL = 'Why not chosen (from source)'
const PREVIEW_LIMITATION_LABEL = 'Limitation stated in source'
const PREVIEW_BADGE = 'Previewed alternative'
const CONSEQUENCES_LABEL = 'Consequences (from source)'
const CONSEQUENCES_PREVIEW_NOTE = 'These consequences describe the saved choice, not the preview.'

type PassageProps = {
  passageLabel: (evidenceId: string) => string | undefined
  onOpenEvidence: (evidenceId: string, opener: HTMLElement) => void
}

function PassageLink({ evidenceId, passageLabel, onOpenEvidence }: PassageProps & { evidenceId: string }) {
  const label = passageLabel(evidenceId)
  if (!label) return null
  return <Button type="button" variant="ghost" size="sm" className="log-source-link" onClick={(event) => onOpenEvidence(evidenceId, event.currentTarget)}>
    <FileText size={13} />Open passage · {label}<ArrowUpRight size={13} />
  </Button>
}

/** Source-stated limitation of an option the saved record did not select. `previewed` relabels it while that option is the What-if preview. */
export function RejectionReason({ statement, previewed = false, ...passage }: PassageProps & { statement: SourceStatement; previewed?: boolean }) {
  return <div className="log-reason grid gap-1.5 rounded-md border border-(--theme-line) bg-(--theme-panel-raised) p-2 text-(--theme-ink)" data-kind={previewed ? 'preview-limitation' : 'rejection'}>
    <div className="flex flex-wrap items-center gap-1.5">
      <strong className="text-xs text-(--theme-muted)">{previewed ? PREVIEW_LIMITATION_LABEL : REJECTION_LABEL}</strong>
      {previewed && <Badge variant="warning">{PREVIEW_BADGE}</Badge>}
    </div>
    <p className="m-0 break-words">{statement.text}</p>
    <PassageLink evidenceId={statement.evidence_id} {...passage} />
  </div>
}

/** Consequence sentences from the decision's own Consequences section; each distinct passage gets one link. */
export function DecisionConsequences({ statements, previewing = false, ...passage }: PassageProps & { statements: SourceStatement[]; previewing?: boolean }) {
  const evidenceIds = [...new Set(statements.map((statement) => statement.evidence_id))]
  return <section className="log-consequences grid gap-1.5 rounded-md border border-(--theme-line) bg-(--theme-panel-raised) p-2 text-(--theme-ink)" aria-label={CONSEQUENCES_LABEL}>
    <strong className="text-xs text-(--theme-muted)">{CONSEQUENCES_LABEL}</strong>
    {previewing && <p className="m-0 text-xs text-(--theme-muted)">{CONSEQUENCES_PREVIEW_NOTE}</p>}
    <ul className="m-0 grid list-disc gap-1 pl-5">{statements.map((statement) => <li className="break-words" key={`${statement.evidence_id}:${statement.text}`}>{statement.text}</li>)}</ul>
    {evidenceIds.map((evidenceId) => <PassageLink key={evidenceId} evidenceId={evidenceId} {...passage} />)}
  </section>
}
