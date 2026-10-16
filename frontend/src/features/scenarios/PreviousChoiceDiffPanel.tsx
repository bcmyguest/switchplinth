// "Changes vs previous choice" and "Affected downstream" in the What-if panel. Both compare the last switch with the selection
// resolved just before it, unlike the repository-choices outcome below them.
import type { ReactNode } from 'react'
import { InlineError } from '../../components/InlineError'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import type { PreviousChoiceDiffState } from './usePreviousChoiceDiff'
import type { ScenarioDiffView } from './scenarioDiff'

const SECTION = 'order-6 my-[6px] min-w-0 gap-[8px] rounded-[6px] bg-(--theme-panel-raised) px-[10px] py-[10px] text-(length:--type-tertiary) leading-[1.45] shadow-none'
const HEADING = 'flex flex-wrap items-baseline justify-between gap-x-[8px] gap-y-[2px] [&>strong]:text-(length:--type-secondary) [&>span]:text-(--theme-muted)'
const LIST = 'm-0 grid min-w-0 list-none gap-[4px] p-0'
const ITEM = 'flex min-w-0 flex-wrap items-baseline gap-x-[6px] gap-y-[2px] [overflow-wrap:anywhere]'
/** A status badge beside wrapping text: the text wraps in its own column instead of dropping below the badge. */
const ROW = 'grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-[6px] [overflow-wrap:anywhere]'
const NOTE = 'm-0 text-(--theme-muted) [overflow-wrap:anywhere]'

function Group({ title, empty, children }: { title: string; empty: string; children: ReactNode[] }) {
  return <div className="grid min-w-0 gap-[4px]"><strong className="text-(--theme-ink)">{title}</strong>{children.length ? <ul className={LIST} aria-label={`${title} vs previous choice`}>{children}</ul> : <p className={NOTE}>{empty}</p>}</div>
}

function Changes({ view }: { view: ScenarioDiffView }) {
  return <>
    {view.switched.length ? <ul className={LIST} aria-label="Switched decisions">{view.switched.map((line, index) => <li key={`${line}-${index}`} className={`${ITEM} font-semibold`}>{line}</li>)}</ul> : <p className={NOTE}>Same choices as before; nothing changed.</p>}
    {view.switched.length > 0 && <>
    <Group title="Components" empty="No components added, removed, or changed.">{view.components.map((line, index) => <li key={`${line.change}-${line.text}-${index}`} className={ROW} data-change={line.change}><Badge variant="outline">{line.change}</Badge><span>{line.text}</span></li>)}</Group>
    <Group title="Relationships" empty="No relationships added, removed, or changed.">{view.relationships.map((line, index) => <li key={`${line.change}-${line.text}-${index}`} className={ROW} data-change={line.change}><Badge variant="outline">{line.change}</Badge><span>{line.text}</span></li>)}</Group>
    <Group title="Conflicts and assumptions" empty="No conflicts or invalid assumptions appeared or disappeared.">{view.problems.map((line, index) => <li key={`${line.change}-${line.text}-${index}`} className={ROW} data-change={line.change}><Badge variant={line.change === 'Appeared' ? 'warning' : 'outline'}>{line.change}</Badge><span>{line.kind}: {line.text}</span></li>)}</Group>
    {view.unmet.length > 0 && <Group title="Unmet requirements" empty="">{view.unmet.map((line, index) => <li key={`${line.change}-${line.text}-${index}`} className={ROW} data-change={line.change} data-unmet-requirement={line.text}><Badge variant={line.change === 'Appeared' ? 'warning' : 'outline'}>{line.change}</Badge><span>{line.text}</span></li>)}</Group>}
    <Group title="Decisions affected" empty="No decisions affected.">{view.decisions.map((decision, index) => <li key={`${decision.title}-${index}`} className={ITEM}><span className="font-semibold">{decision.title}</span><span className="text-(--theme-muted)">{decision.reasons}</span></li>)}</Group>
    </>}
  </>
}

function Downstream({ view }: { view: ScenarioDiffView }) {
  return <Card asChild className={SECTION}><section aria-label="Affected downstream">
    <div className={HEADING}><strong>Affected downstream</strong><span>vs previous choice</span></div>
    {view.downstream.length ? <ul className={`${LIST} gap-[8px]`} aria-label="Removed or replaced elements">{view.downstream.map((item, index) => <li key={`${item.label}-${index}`} className="grid min-w-0 gap-[4px]" data-impact-item={item.label}>
      <div className={ROW}><Badge variant="outline">{item.change}</Badge><span className="font-semibold">{item.label}</span></div>
      {item.dependents.length ? <ul className={`${LIST} border-l border-(--theme-line) pl-[8px]`} aria-label={`Dependents of ${item.label}`}>{item.dependents.map((dependent) => <li key={`${dependent.name}-${dependent.path}`} className="grid min-w-0 gap-[2px]" data-dependent={dependent.name} data-status={dependent.status}>
        <div className={ITEM}><span className="font-semibold">{dependent.name}</span><Badge variant={dependent.status === 'Dangling' ? 'destructive' : dependent.status === 'Rewired' ? 'secondary' : 'outline'}>{dependent.status}</Badge><span className="text-(--theme-muted)">depth {dependent.depth}</span></div>
        <p className={NOTE}>Path: {dependent.path}</p>
        {dependent.details.map((detail) => <p key={detail} className="m-0 [overflow-wrap:anywhere]">{detail}</p>)}
      </li>)}</ul> : <p className={NOTE}>Nothing depended on it.</p>}
      {item.truncated && <p className={NOTE}>More dependents lie beyond {view.maxDepth} hops.</p>}
    </li>)}</ul> : <p className={NOTE}>Nothing the previous choice relied on was removed or replaced.</p>}
    <p className={`${NOTE} text-(length:--type-caption)`}>Estimate from declared relationships only, up to {view.maxDepth} hops; “rewired” is a heuristic; no code or runtime data.</p>
  </section></Card>
}

export function PreviousChoiceDiffPanel({ state, onRetry }: { state: PreviousChoiceDiffState; onRetry: () => void }) {
  return <>
    <Card asChild className={SECTION}><section aria-label="Changes vs previous choice" aria-busy={state.status === 'loading'}>
      <div className={HEADING}><strong>Changes vs previous choice</strong><span>Baseline: the choices before your last switch</span></div>
      {state.status === 'idle' && <p className={NOTE}>Switch an option to see what it changes relative to the previous choice.</p>}
      {state.status === 'loading' && <p className={NOTE} role="status">Comparing with the previous choice…</p>}
      {state.status === 'error' && <InlineError message={`Could not compare with the previous choice: ${state.message}`}><Button type="button" variant="link" size="sm" className="min-h-0 px-0" onClick={onRetry}>Retry</Button></InlineError>}
      {state.status === 'ready' && <Changes view={state.view} />}
    </section></Card>
    {state.status === 'ready' && <Downstream view={state.view} />}
  </>
}
