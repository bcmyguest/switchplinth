// The selected-component rationale panel and the What-if scenario panel. It renders once: the Architecture overlay and the
// Scenarios page show the same DOM instance, so the decision refs and the panel focus target stay valid in both places.
import type { ComponentProps, RefObject } from 'react'
import { AlertTriangle, ArrowRight, ArrowUpRight, Check, ChevronDown, CircleHelp, Database, FileText, GitFork, Minus, MoreHorizontal, Sparkles, X } from 'lucide-react'
import type { getEntityDetail } from '../../api'
import type { LabelCatalog } from '../../app/labelCatalog'
import { InlineError } from '../../components/InlineError'
import { Alert, AlertDescription } from '../../components/ui/alert'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { cn } from '../../lib/utils'
import type { Entity, Evidence, GraphData } from '../../types'
import { DecisionLinkList } from '../architecture/DecisionLinkList'
import type { ScanState } from '../discovery/scanState'
import { evidenceHeading, evidencePath, resolveEvidence } from '../evidence/evidence'
import type { EvidenceViewer } from '../evidence/useEvidenceViewer'
import { compactScenarioDecisionTitle, describeScenarioDifference, describeScenarioSelection, scenarioSelectionKey } from './scenarioSelection'
import type { ScenarioSelection } from './useScenarioSelection'

/** Derived component-detail values the rationale panel shows; App computes them until the component-detail module lands. */
type ComponentDetailView = {
  selected: Entity | undefined
  entityDetail: Awaited<ReturnType<typeof getEntityDetail>> | null
  rationaleLabel: string
  rationale: string
  evidence: Evidence | undefined
  linkedDecisions: ComponentProps<typeof DecisionLinkList>['decisions']
}

type ScenarioWorkspaceProps = {
  /** `overlay`: the Architecture What-if overlay; `page`: the Scenarios page; `hidden`: mounted but not displayed. */
  mode: 'overlay' | 'page' | 'hidden'
  /** True while the Architecture What-if panel is the open overlay panel; it then owns `panelRef` and shows a close button. */
  panelOpen: boolean
  panelRef: RefObject<HTMLElement | null>
  onClosePanel: () => void
  graph: GraphData
  live: boolean
  projectRoot: string
  catalog: LabelCatalog
  scenario: ScenarioSelection
  detail: ComponentDetailView
  evidenceRecords: Evidence[]
  onOpenEvidence: EvidenceViewer['open']
  onExploreDecision: (decisionId: string) => void
  repositoryBusy: boolean
  scanState: ScanState
}

/** History row: a full-width wrapped label; the first row is the pinned repository base. */
const HISTORY_ITEM = 'block w-full px-[8px] py-[6px] text-(length:--type-secondary) leading-[1.4] [overflow-wrap:break-word] aria-pressed:font-semibold max-sm:px-[7px] max-sm:py-[5px] max-sm:leading-[1.35]'
/** Sticky decision-picker pill; the current decision widens on mobile so its title is not truncated. */
const PICKER_ITEM = 'max-w-[190px] flex-none gap-[5px] rounded-[16px] px-[8px] py-[5px] text-(length:--type-secondary) leading-[1.2] whitespace-nowrap aria-[current=location]:border-(--theme-brand) aria-[current=location]:bg-(--theme-selected) aria-[current=location]:font-[650] max-sm:max-w-[155px] max-sm:aria-[current=location]:max-w-[240px] [&>span]:overflow-hidden [&>span]:text-ellipsis max-sm:aria-[current=location]:[&>span]:overflow-visible max-sm:aria-[current=location]:[&>span]:[text-overflow:clip]'

export function ScenarioWorkspace({ mode, panelOpen, panelRef, onClosePanel, graph, live, projectRoot, catalog, scenario, detail, evidenceRecords, onOpenEvidence: openEvidenceDetail, onExploreDecision: exploreDecision, repositoryBusy, scanState }: ScenarioWorkspaceProps) {
  const { selected, entityDetail: currentEntityDetail, rationaleLabel, rationale: selectedRationale, evidence: selectedEvidence, linkedDecisions } = detail
  const { displayed: displayedSelection, resolved: resolvedSelection, baseline: repositorySelection, pending: scenarioResolutionPending, notice: scenarioNotice, setNotice: setScenarioNotice, changes: scenarioChanges, history: scenarioHistory, saved: savedScenarios, savedError: savedScenariosError, savedLoading: savedScenariosLoading, refreshSaved: refreshSavedScenarios, activeDecisionId: activeScenarioDecisionId, setActiveDecisionId: setActiveScenarioDecisionId, decisionRefs: scenarioDecisionRefs, pickerRef: scenarioDecisionPickerRef, pickerButtonRefs: scenarioDecisionPickerButtonRefs, apply: applySelections, choose: chooseOption, jumpTo: jumpToScenarioDecision } = scenario
  const { libraryOpen: scenarioLibraryOpen, setLibraryOpen: setScenarioLibraryOpen, open: showScenarioSave, setOpen: setShowScenarioSave, name: scenarioName, setName: setScenarioName, error: scenarioSaveError, setError: setScenarioSaveError } = scenario.saveForm
  const scenarioEvaluated = Boolean(graph.scenario) || Object.keys(scenarioChanges).length > 0
  const scenarioChangeItems = Object.entries(scenarioChanges).flatMap(([kind, items]) => (items ?? []).map((label) => ({ kind, label })))
  const compiledScenarioChanges = scenarioChangeItems.length ? scenarioChangeItems : Object.entries(graph.scenario?.affected ?? {}).flatMap(([kind, ids]) => (ids ?? []).map((id) => ({ kind, label: catalog.label(id) })))
  const scenarioWarnings = [...(graph.scenario?.conflicts ?? []), ...(graph.scenario?.invalid_assumptions ?? [])]
  const affectedDecisionNames = (graph.scenario?.affected_decisions ?? []).map((id) => graph.decisions.find((decision) => decision.id === id)?.title ?? id)
  const hasTemporaryChoices = graph.decisions.some((decision) => displayedSelection[decision.id] !== repositorySelection.current[decision.id])

  return <div className={`${mode === 'overlay' ? 'architecture-scenario-open' : ''}${mode === 'page' ? ' scenarios-page' : ''}`} style={{ display: mode === 'hidden' ? 'none' : undefined }}><div className="below-grid">
    <section className="panel rationale-panel">
      <div className="panel-top"><div className="panel-title-icon"><Database size={15} /></div><div><div className="panel-kicker">SELECTED COMPONENT</div><h3>{selected?.name ?? 'Select a component'}</h3></div><Button variant="icon" size="icon" className="-mr-[6px]"><MoreHorizontal size={17} /></Button></div>
      {selected ? <>
        <p className="entity-description">{selected.description ?? 'A component surfaced in source material. Add a description when the team has confirmed its role.'}</p>
        <div className="entity-tags"><span>{selected.kind}</span><span className={`state-tag ${selected.epistemic_state ?? 'inferred'}`}><i />{selected.epistemic_state ?? 'inferred'}{selected.confidence ? ` · ${Math.round(selected.confidence * 100)}%` : ''}</span>{(currentEntityDetail?.aliases ?? graph.aliases?.filter((alias) => alias.entity_id === selected.id) ?? selected.aliases ?? []).map((alias) => <span key={alias.id} className="alias-tag">“{alias.name}” <span className={alias.epistemic_state}>{alias.epistemic_state} · {Math.round(alias.confidence * 100)}%</span></span>)}</div>
        <div className="rationale-block"><div className="rationale-label"><Sparkles size={13} /> {rationaleLabel}</div><p>{selectedRationale}</p></div>
        <Button variant="choice" className="mt-[9px] w-full justify-between rounded-[6px] bg-(--theme-panel-raised) px-[8px]" disabled={!selectedEvidence} onClick={() => openEvidenceDetail(selectedEvidence)}><div className="evidence-file"><FileText size={14} /><div><strong>{evidencePath(selectedEvidence)}</strong><span>{evidenceHeading(selectedEvidence)}</span></div></div><span className="evidence-open">Open passage <ArrowUpRight size={14} /></span></Button>
        <DecisionLinkList decisions={linkedDecisions} evidence={evidenceRecords} onOpenEvidence={(item) => openEvidenceDetail(item)} onChooseOption={(decisionId, optionId) => { const decision = graph.decisions.find((item) => item.id === decisionId); if (decision) void chooseOption(decision, optionId) }} onExploreDecision={exploreDecision} disabled={scenarioResolutionPending || scanState === 'scanning'} />
      </> : <div className="empty-state">Choose a component in the map to inspect it.</div>}
    </section>

    <section className="panel scenario-panel" ref={(element) => { if (panelOpen) panelRef.current = element }}>
      <div className="scenario-head"><div><div className="panel-kicker">WHAT IF?</div><h3>Scenario playground</h3></div>{panelOpen && <Button variant="icon" size="icon" aria-label="Close What-if panel" onClick={onClosePanel}><X size={15} /></Button>}</div>
      <p className="scenario-copy">Switch options to compare a temporary preview. Repository choices stay unchanged.</p>
      <div className={`scenario-working-state ${hasTemporaryChoices ? 'changed' : ''}`} role="status"><span>{hasTemporaryChoices ? 'Exploring temporary choices' : 'Showing repository choices'}</span>{hasTemporaryChoices && <Button type="button" variant="choice" className="shrink-0 px-[9px] py-[6px] text-(length:--type-tertiary) font-semibold text-(--theme-source)" disabled={repositoryBusy || scenarioResolutionPending || scanState === 'scanning'} onClick={() => void applySelections(repositorySelection.current)}>Return to repository choices</Button>}</div>
      {scenarioHistory.length > 0 && <section className="scenario-history" aria-label="Pinned base and recent combinations"><div className="scenario-history-heading"><strong>Switch combination</strong><span>Base and recent</span></div><div className="scenario-history-list">{scenarioHistory.map((item, index) => {
        const fullLabel = describeScenarioSelection(graph, item.selections)
        const visibleLabel = index === 0 ? 'Original choices' : describeScenarioDifference(graph, item.selections, repositorySelection.current)
        return <Button type="button" variant="choice" key={item.key} className={cn('scenario-history-item', HISTORY_ITEM, index === 0 && 'border-(--theme-selected) bg-(--theme-panel-raised)')} title={fullLabel} aria-label={`${index === 0 ? 'Restore original repository choices' : 'Show combination'}: ${fullLabel}`} aria-pressed={item.key === scenarioSelectionKey(resolvedSelection.current)} disabled={scenarioResolutionPending || repositoryBusy || scanState === 'scanning'} onClick={() => void applySelections(item.selections)}>{index === 0 && <span className="scenario-history-kind">Base</span>}{visibleLabel}</Button>
      })}</div></section>}
      <section className="scenario-quick-summary" aria-label="Preview summary" role="status"><strong>{scenarioEvaluated ? 'Preview result' : 'Preview not resolved'}</strong>{scenarioEvaluated ? <div className="scenario-summary-counts"><span>{compiledScenarioChanges.length} changed</span><span>{graph.scenario?.conflicts?.length ?? 0} conflicts</span><span>{graph.scenario?.invalid_assumptions?.length ?? 0} invalid assumptions</span></div> : <span>Choose an option to compare.</span>}{compiledScenarioChanges[0] && <p>Changed: {compiledScenarioChanges[0].label}{compiledScenarioChanges.length > 1 ? ` · +${compiledScenarioChanges.length - 1} more` : ''}</p>}</section>
      {graph.decisions.length > 0 && <nav className="scenario-decision-picker" aria-label="Jump to a decision"><span className="scenario-decision-picker-label">Jump to</span><div ref={scenarioDecisionPickerRef}>{graph.decisions.map((decision) => <Button type="button" variant="choice" className={PICKER_ITEM} key={decision.id} ref={(element) => { if (element) scenarioDecisionPickerButtonRefs.current.set(decision.id, element); else scenarioDecisionPickerButtonRefs.current.delete(decision.id) }} title={decision.title} aria-label={`Jump to ${decision.title} options`} aria-current={activeScenarioDecisionId === decision.id ? 'location' : undefined} onClick={() => jumpToScenarioDecision(decision.id)}><span>{compactScenarioDecisionTitle(decision.title)}</span>{activeScenarioDecisionId === decision.id && <small className="rounded-[8px] bg-(--theme-brand-soft) px-[5px] py-[2px] text-[10px] font-bold text-(--theme-brand)">Current</small>}</Button>)}</div></nav>}
      {graph.decisions.map((decision) => {
        const activeOptionId = displayedSelection[decision.id] ?? decision.selected_option
        const decisionScope = compactScenarioDecisionTitle(decision.title).replace(/^[^:]+:\s*/, '').trim()
        return <div className="decision-select" key={decision.id} ref={(element) => { if (element) scenarioDecisionRefs.current.set(decision.id, element); else scenarioDecisionRefs.current.delete(decision.id) }} onFocusCapture={() => setActiveScenarioDecisionId(decision.id)}><div className="decision-name" role="heading" aria-level={4} tabIndex={-1}><span className="decision-dot" />{decision.title}{decision.extraction_review && <span className="review-status inferred">Delta review required</span>}</div><div className="option-switch">{decision.options.map((option) => {
          const isActive = activeOptionId === option.id
          const optionEvidence = option.evidence?.map((reference) => resolveEvidence(reference, evidenceRecords)).find((evidence): evidence is Evidence => Boolean(evidence))
          const needsDeltaReview = decision.extraction_review?.rejected_options.some((item) => item.option_id === option.id) ?? false
          return <div className={`option-choice ${isActive ? 'active' : 'inactive'}`} key={option.id}><Button type="button" variant="secondary" size="sm" className={isActive ? 'chosen' : ''} aria-pressed={isActive} disabled={scenarioResolutionPending || scanState === 'scanning'} onClick={() => { setActiveScenarioDecisionId(decision.id); void chooseOption(decision, option.id) }}><span>{option.title}</span><small>{isActive ? `Selected for ${decisionScope}` : `Not selected for ${decisionScope}`}{needsDeltaReview ? ' · Delta review required' : ''}</small>{isActive ? <Check size={12} aria-hidden="true" /> : <Minus size={12} aria-hidden="true" />}</Button>{option.rationale && <p className="option-rationale">{option.rationale}</p>}{optionEvidence && <Button type="button" variant="ghost" size="sm" className="option-source" onClick={() => openEvidenceDetail(optionEvidence)}><FileText size={12} /><span>{isActive ? 'Open source passage' : 'Evidence for this alternative'} · {evidencePath(optionEvidence)} · {evidenceHeading(optionEvidence)}</span><ArrowUpRight size={12} /></Button>}</div>
        })}</div></div>
      })}
      {scenarioResolutionPending && <p className="scenario-list-status" role="status">Resolving choices… Your last resolved graph remains in view until this finishes.</p>}
      {scenarioNotice && <Alert variant="warning" role="status" className="order-6 my-[6px] flex items-start gap-[6px] px-[8px] py-[7px] text-(length:--type-tertiary) leading-[1.45] [&>svg]:flex-none"><AlertTriangle size={14} /><AlertDescription className="flex-1 text-(length:--type-tertiary)">{scenarioNotice}</AlertDescription><Button type="button" variant="icon" size="icon" className="p-0 text-inherit" aria-label="Dismiss scenario message" onClick={() => setScenarioNotice('')}><X size={12} /></Button></Alert>}
      <section className="scenario-outcome" aria-label="Scenario comparison">
        <div className="scenario-outcome-heading"><strong>Preview result</strong><span>{scenarioEvaluated ? 'Resolved' : 'Choose an option to compare'}</span></div>
        <div className="scenario-outcome-grid">
          <div><strong>What changed</strong>{!scenarioEvaluated ? <p>Run a comparison to see changed components and relationships.</p> : compiledScenarioChanges.length ? <ul>{compiledScenarioChanges.map((item, index) => <li key={`${item.kind}-${item.label}-${index}`}><span>{item.kind}</span>{item.label}</li>)}</ul> : <p>No graph records changed for this selection.</p>}</div>
          <div><strong>Decisions affected</strong>{!scenarioEvaluated ? <p>Not evaluated yet.</p> : affectedDecisionNames.length ? <p>{affectedDecisionNames.join(' · ')}</p> : <p>No decisions affected.</p>}</div>
          <div className={scenarioWarnings.length ? 'has-warnings' : ''}><strong>Assumptions</strong>{!scenarioEvaluated ? <p>Not checked yet.</p> : scenarioWarnings.length ? <ul>{scenarioWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : <p>No invalid assumptions found.</p>}</div>
        </div>
      </section>
      <section className="scenario-library" aria-label="Named scenarios">
        <Button type="button" variant="choice" className="w-full gap-[7px] px-[9px] text-(length:--type-tertiary) font-semibold" aria-expanded={scenarioLibraryOpen} onClick={() => setScenarioLibraryOpen((open) => !open)}><GitFork size={13} /> Save or reopen a named scenario <ChevronDown size={13} className={cn('ml-auto transition-transform duration-150', scenarioLibraryOpen && 'rotate-180')} /></Button>
        {scenarioLibraryOpen && <div className="scenario-library-content"><p>Save these choices as a named scenario in this repository so others can reopen them.</p>
          {!showScenarioSave ? <Button type="button" variant="choice" className="justify-center px-[9px] py-[6px] text-center text-(length:--type-tertiary) font-semibold" disabled={!live || repositoryBusy || scenarioResolutionPending || scanState === 'scanning' || !projectRoot} onClick={() => { setShowScenarioSave(true); setScenarioSaveError('') }}>Save as named scenario</Button> : <form className="mb-[8px] flex flex-wrap items-center gap-[4px] rounded-[5px] border border-(--theme-line) bg-(--theme-panel-raised) p-[6px]" onSubmit={(event) => void scenario.saveForm.submit(event, repositoryBusy || scanState === 'scanning')}><Input aria-label="Scenario name" className="min-h-[32px] w-auto flex-1 rounded-[4px] px-[6px] py-0 text-[12px] text-(--theme-muted) shadow-none" value={scenarioName} onChange={(event) => setScenarioName(event.target.value)} placeholder="Name this scenario" autoFocus /><Button type="submit" className="min-h-[32px] rounded-[4px] border px-[9px] text-[12px] font-semibold" disabled={!live || repositoryBusy || scenarioResolutionPending || scanState === 'scanning' || !projectRoot || !scenarioName.trim()}>Save scenario</Button><Button type="button" variant="choice" className="min-h-[32px] justify-center rounded-[4px] px-[5px] py-0 text-(--theme-source)" onClick={() => setShowScenarioSave(false)} aria-label="Cancel"><X size={13} /></Button>{scenarioSaveError && <span className="basis-full text-(length:--type-caption) text-(--theme-danger)">{scenarioSaveError}</span>}</form>}
          {live && <section className="saved-scenarios" aria-label="Saved scenarios"><div className="saved-scenarios-heading"><strong>Reopen a saved scenario</strong>{savedScenarios.length > 0 && <span>{savedScenarios.length}</span>}</div>{savedScenariosError && <InlineError message={`${savedScenariosError}${savedScenarios.length > 0 ? ' Showing the last loaded list.' : ''}`}><Button type="button" variant="link" size="sm" className="min-h-0 px-0" disabled={savedScenariosLoading} onClick={() => void refreshSavedScenarios()}>Retry</Button></InlineError>}{savedScenariosLoading ? <p className="scenario-list-status" role="status">Loading saved scenarios…</p> : savedScenarios.length ? savedScenarios.map((scenario) => <Button variant="choice" className="w-full gap-[8px] px-[9px] py-[6px] text-[10px] text-(--theme-source) [&>svg]:flex-none" type="button" key={scenario.id} aria-label={`Load scenario ${scenario.name}`} disabled={scenarioResolutionPending || scanState === 'scanning'} onClick={() => { void applySelections(scenario.selections).then((warning) => { if (warning !== false) setScenarioNotice(`Loaded scenario “${scenario.name}”.${warning ? ` ${warning}` : ''}`) }) }}><span className="flex-none rounded-[4px] bg-(--theme-panel-raised) px-[6px] py-[3px] text-[8px] font-[650] tracking-[.04em] uppercase">Reopen</span><strong className="min-w-0 flex-1 text-[10px] font-semibold [overflow-wrap:anywhere]">{scenario.name}</strong><ArrowRight size={13} /></Button>) : !savedScenariosError ? <p className="scenario-list-status">No named scenarios saved yet.</p> : null}</section>}
        </div>}
      </section>
      <div className="scenario-note"><CircleHelp size={13} /> Options apply as deltas over the shared architecture.</div>
    </section>
  </div></div>
}
