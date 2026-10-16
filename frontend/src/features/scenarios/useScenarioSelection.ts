// Scenario selection: the chosen option per decision, the resolved and repository (baseline) selections, request
// sequencing, the demo fallback, the session history, saved named scenarios, and the What-if decision picker.
// The delta editor checks `epoch()` instead of this module calling into the editor.
import { useEffect, useRef, useState, type FormEvent, type RefObject } from 'react'
import { listScenarios, resolveScenario, saveScenario } from '../../api'
import { demoGraph } from '../../demo'
import { resolveDemoScenario } from '../../scenario-preview'
import type { Workspace } from '../../app/useWorkspace'
import type { Decision, DeltaOperation, GraphData, SavedScenario } from '../../types'
import { describeScenarioSelection, scenarioSelectionKey, selectedOptions } from './scenarioSelection'

const INITIAL_SELECTIONS: Record<string, string> = { 'decision-messaging': 'option-kafka', 'decision-database': 'option-postgres' }

type Selections = Record<string, string>
type ScenarioHistoryItem = { key: string; label: string; selections: Selections }
type ScenarioChanges = { added?: string[]; removed?: string[]; changed?: string[] }

type ScenarioSaveForm = {
  libraryOpen: boolean
  setLibraryOpen: (update: (open: boolean) => boolean) => void
  open: boolean
  setOpen: (open: boolean) => void
  name: string
  setName: (name: string) => void
  error: string
  setError: (error: string) => void
  /** Saves the resolved selection under the form name. `blocked` covers guards owned elsewhere (repository switch, scan). */
  submit(event: FormEvent<HTMLFormElement>, blocked: boolean): Promise<void>
}

export type ScenarioSelection = {
  /** The requested selection; it runs ahead of the graph while a resolve is pending. */
  selection: Selections
  /** The selection the visible graph shows: the resolved one while a resolve is pending. */
  displayed: Selections
  /** The last successfully resolved selection. */
  resolved: { readonly current: Selections }
  /** The repository-selected choices: the return target and the history base. */
  baseline: { readonly current: Selections }
  pending: boolean
  notice: string
  setNotice: (notice: string) => void
  changes: ScenarioChanges
  history: ScenarioHistoryItem[]
  saved: SavedScenario[]
  savedError: string
  savedLoading: boolean
  refreshSaved(generation?: number): Promise<void>
  saveForm: ScenarioSaveForm
  activeDecisionId: string
  setActiveDecisionId: (decisionId: string) => void
  decisionRefs: RefObject<Map<string, HTMLDivElement>>
  pickerRef: RefObject<HTMLDivElement | null>
  pickerButtonRefs: RefObject<Map<string, HTMLButtonElement>>
  /** Resolves `next`. Returns the conflict text on success and false when the request failed, went stale, or was invalid. */
  apply(next: Selections, localDelta?: DeltaOperation[]): Promise<string | false>
  choose(decision: Decision, optionId: string): Promise<void>
  /** Scrolls a decision's options into view and focuses its active choice. */
  jumpTo(decisionId: string): void
  /** Records a selection that another module resolved (delta save, proposal). */
  commit(selections: Selections): void
  /** Takes `graph`'s selected options as the resolved selection and the baseline, and reseeds the history. */
  rebase(graph: GraphData): void
  /** Drops an in-flight resolve and shows the resolved selection again. */
  cancelPending(): void
  /** Runs before a repository switch opens a project: drops in-flight resolve and saved-list requests. */
  beforeSwitch(): void
  /** Clears this module's per-repository state after a repository opens. */
  reset(): void
  /** Bumped by every `apply`. A delta save captured before a bump is stale. */
  epoch(): number
}

type ScenarioDependencies = {
  /** Reports a resolved graph and the entity the caller should prefer when the current one is gone. */
  onResolved(graph: GraphData, preferredEntityId: string | undefined): void
}

export function useScenarioSelection(workspace: Pick<Workspace, 'graph' | 'live' | 'projectRoot' | 'generation' | 'catalog' | 'commitGraph'>, dependencies: ScenarioDependencies): ScenarioSelection {
  const [selection, setSelection] = useState(INITIAL_SELECTIONS)
  const [scenarioNotice, setScenarioNotice] = useState('')
  const [savedScenarios, setSavedScenarios] = useState<SavedScenario[]>([])
  const [savedScenariosError, setSavedScenariosError] = useState('')
  const [savedScenariosLoading, setSavedScenariosLoading] = useState(false)
  const [scenarioResolutionPending, setScenarioResolutionPending] = useState(false)
  const [showScenarioSave, setShowScenarioSave] = useState(false)
  const [scenarioName, setScenarioName] = useState('')
  const [scenarioSaveError, setScenarioSaveError] = useState('')
  const [scenarioChanges, setScenarioChanges] = useState<ScenarioChanges>({})
  const [scenarioLibraryOpen, setScenarioLibraryOpen] = useState(false)
  const [activeScenarioDecisionId, setActiveScenarioDecisionId] = useState('')
  const [scenarioHistory, setScenarioHistory] = useState<ScenarioHistoryItem[]>(() => [{ key: scenarioSelectionKey(INITIAL_SELECTIONS), label: describeScenarioSelection(demoGraph, INITIAL_SELECTIONS), selections: INITIAL_SELECTIONS }])
  const scenarioRequestSequence = useRef(0)
  const scenarioListSequence = useRef(0)
  const resolvedSelection = useRef<Selections>(INITIAL_SELECTIONS)
  const repositorySelection = useRef<Selections>(INITIAL_SELECTIONS)
  const applyEpoch = useRef(0)
  const scenarioDecisionRefs = useRef(new Map<string, HTMLDivElement>())
  const scenarioDecisionPickerRef = useRef<HTMLDivElement | null>(null)
  const scenarioDecisionPickerButtonRefs = useRef(new Map<string, HTMLButtonElement>())
  const { graph, live, projectRoot, generation: repositoryGeneration, catalog, commitGraph } = workspace

  function revealScenarioDecisionChip(decisionId: string) {
    const scroller = scenarioDecisionPickerRef.current
    const chip = scenarioDecisionPickerButtonRefs.current.get(decisionId)
    if (!scroller || !chip) return
    const scrollerBounds = scroller.getBoundingClientRect()
    const chipBounds = chip.getBoundingClientRect()
    const leftDelta = chipBounds.left - scrollerBounds.left
    const rightDelta = chipBounds.right - scrollerBounds.right
    if (leftDelta < 0) scroller.scrollTo({ left: scroller.scrollLeft + leftDelta, behavior: 'smooth' })
    else if (rightDelta > 0) scroller.scrollTo({ left: scroller.scrollLeft + rightDelta, behavior: 'smooth' })
  }

  useEffect(() => {
    if (activeScenarioDecisionId) revealScenarioDecisionChip(activeScenarioDecisionId)
  }, [activeScenarioDecisionId])

  async function refreshSavedScenarios(generation = repositoryGeneration.current) {
    const requestSequence = ++scenarioListSequence.current
    setSavedScenariosLoading(true)
    try {
      const scenarios = await listScenarios()
      if (generation !== repositoryGeneration.current || requestSequence !== scenarioListSequence.current) return
      setSavedScenarios(scenarios)
      setSavedScenariosError('')
    } catch (error) {
      if (generation !== repositoryGeneration.current || requestSequence !== scenarioListSequence.current) return
      setSavedScenariosError(error instanceof Error ? error.message : 'Could not load saved scenarios.')
    } finally {
      if (generation === repositoryGeneration.current && requestSequence === scenarioListSequence.current) setSavedScenariosLoading(false)
    }
  }

  async function applySelections(next: Selections, localDelta: DeltaOperation[] = []): Promise<string | false> {
    const requestSequence = ++scenarioRequestSequence.current
    const generation = repositoryGeneration.current
    applyEpoch.current += 1
    const invalidSelection = Object.entries(next).find(([decisionId, optionId]) => {
      const decision = graph.decisions.find((item) => item.id === decisionId)
      return !decision || !decision.options.some((option) => option.id === optionId)
    })
    if (invalidSelection) {
      const [decisionId, optionId] = invalidSelection
      setSelection(resolvedSelection.current)
      setScenarioResolutionPending(false)
      setScenarioNotice(`Could not apply this scenario: “${decisionId} → ${optionId}” is not a known decision option. The current graph and choices are unchanged.`)
      return false
    }
    setSelection(next)
    setScenarioResolutionPending(true)
    setScenarioNotice('')
    try {
      const resolved = await resolveScenario(next)
      if (requestSequence !== scenarioRequestSequence.current || generation !== repositoryGeneration.current) return false
      const committedSelections = resolved.graph.scenario?.selections ?? next
      catalog.rememberScenario(graph, resolved.graph)
      const addedEntity = localDelta.find((operation) => operation.op === 'add_entity')?.entity
      const preferredEntityId = addedEntity && typeof addedEntity === 'object' && 'id' in addedEntity && typeof addedEntity.id === 'string' ? addedEntity.id : undefined
      dependencies.onResolved(resolved.graph, resolved.graph.entities.find((entity) => entity.id === preferredEntityId)?.id)
      commitGraph(resolved.graph, { live: true })
      resolvedSelection.current = committedSelections
      setSelection(committedSelections)
      rememberScenarioCombination(resolved.graph, committedSelections)
      setScenarioChanges(Object.fromEntries(Object.entries(resolved.affected ?? {}).map(([kind, ids]) => [kind, ids?.map((id) => catalog.label(id))])))
      const warning = [...(resolved.conflicts ?? []), ...(resolved.invalid_assumptions ?? [])].join(' · ')
      setScenarioNotice(warning)
      setScenarioResolutionPending(false)
      return warning
    } catch {
      if (requestSequence !== scenarioRequestSequence.current || generation !== repositoryGeneration.current) return false
      if (live) {
        setSelection(resolvedSelection.current)
        setScenarioResolutionPending(false)
        setScenarioNotice('The backend could not resolve this scenario. The current graph is unchanged.')
        return false
      }
      const resolvedDemoGraph = resolveDemoScenario(demoGraph, next)
      const demoLabel = catalog.rememberDemoScenario(demoGraph, resolvedDemoGraph)
      const preferredEntityId = Object.entries(next).flatMap(([decisionId, optionId]) => {
        const decision = resolvedDemoGraph.decisions.find((item) => item.id === decisionId)
        return decision?.options.find((option) => option.id === optionId)?.delta?.operations.filter((operation) => operation.op === 'add_entity').map((operation) => (operation.entity as { id?: string } | undefined)?.id ?? '') ?? []
      }).find((id) => resolvedDemoGraph.entities.some((entity) => entity.id === id))
      dependencies.onResolved(resolvedDemoGraph, preferredEntityId)
      const affected = resolvedDemoGraph.scenario?.affected ?? {}
      setScenarioChanges(Object.fromEntries(Object.entries(affected).map(([kind, ids]) => [kind, ids?.map((id) => demoLabel(id))])))
      commitGraph(resolvedDemoGraph, { live: false })
      resolvedSelection.current = next
      setSelection(next)
      setScenarioResolutionPending(false)
      setScenarioNotice('Demo scenario only · this change is not saved.')
      rememberScenarioCombination(resolvedDemoGraph, next)
      return ''
    }
  }

  function rememberScenarioCombination(sourceGraph: GraphData, selections: Selections) {
    const entry = { key: scenarioSelectionKey(selections), label: describeScenarioSelection(sourceGraph, selections), selections }
    setScenarioHistory((current) => {
      const baselineKey = scenarioSelectionKey(repositorySelection.current)
      const baseline = current.find((item) => item.key === baselineKey) ?? {
        key: baselineKey,
        label: describeScenarioSelection(sourceGraph, repositorySelection.current),
        selections: repositorySelection.current,
      }
      const recent = [entry, ...current.filter((item) => item.key !== entry.key && item.key !== baselineKey)].slice(0, 4)
      return [baseline, ...recent]
    })
  }

  async function chooseOption(decision: Decision, optionId: string) {
    const option = decision.options.find((item) => item.id === optionId)
    await applySelections({ ...selection, [decision.id]: optionId }, option?.delta?.operations ?? [])
  }

  function jumpToScenarioDecision(decisionId: string) {
    const section = scenarioDecisionRefs.current.get(decisionId)
    if (!section) return
    setActiveScenarioDecisionId(decisionId)
    section.scrollIntoView({ behavior: 'smooth', block: 'center' })
    window.requestAnimationFrame(() => {
      const target = section.querySelector<HTMLButtonElement>('button[aria-pressed]:not(:disabled)') ?? section.querySelector<HTMLDivElement>('.decision-name')
      target?.focus({ preventScroll: true })
    })
  }

  async function saveCurrentScenario(event: FormEvent<HTMLFormElement>, blocked: boolean) {
    event.preventDefault()
    if (!scenarioName.trim()) return
    if (!live || blocked || scenarioResolutionPending || !projectRoot) return
    setScenarioSaveError('')
    const generation = repositoryGeneration.current
    const selections = resolvedSelection.current
    try {
      await saveScenario(scenarioName.trim(), selections, projectRoot)
      if (generation !== repositoryGeneration.current) return
      setScenarioNotice(`Saved scenario “${scenarioName.trim()}”.`)
      setScenarioName('')
      setShowScenarioSave(false)
      void refreshSavedScenarios(generation)
    } catch (error) { if (generation === repositoryGeneration.current) setScenarioSaveError(error instanceof Error ? error.message : 'Could not save the scenario.') }
  }

  function commit(selections: Selections) {
    resolvedSelection.current = selections
    setSelection(selections)
  }

  function rebase(nextGraph: GraphData) {
    const nextSelection = selectedOptions(nextGraph)
    resolvedSelection.current = nextSelection
    repositorySelection.current = nextSelection
    setSelection(nextSelection)
    setScenarioHistory([{ key: scenarioSelectionKey(nextSelection), label: describeScenarioSelection(nextGraph, nextSelection), selections: nextSelection }])
  }

  function cancelPending() {
    scenarioRequestSequence.current += 1
    setScenarioResolutionPending(false)
    setSelection(resolvedSelection.current)
  }

  function beforeSwitch() {
    scenarioRequestSequence.current += 1
    scenarioListSequence.current += 1
    setScenarioResolutionPending(false)
    setSavedScenariosLoading(false)
  }

  function reset() {
    resolvedSelection.current = {}
    repositorySelection.current = {}
    setScenarioHistory([])
    setSelection({})
    setScenarioChanges({})
    setScenarioNotice('')
    setSavedScenarios([])
    setSavedScenariosError('')
  }

  return {
    selection,
    displayed: scenarioResolutionPending ? resolvedSelection.current : selection,
    resolved: resolvedSelection,
    baseline: repositorySelection,
    pending: scenarioResolutionPending,
    notice: scenarioNotice,
    setNotice: setScenarioNotice,
    changes: scenarioChanges,
    history: scenarioHistory,
    saved: savedScenarios,
    savedError: savedScenariosError,
    savedLoading: savedScenariosLoading,
    refreshSaved: refreshSavedScenarios,
    saveForm: {
      libraryOpen: scenarioLibraryOpen,
      setLibraryOpen: setScenarioLibraryOpen,
      open: showScenarioSave,
      setOpen: setShowScenarioSave,
      name: scenarioName,
      setName: setScenarioName,
      error: scenarioSaveError,
      setError: setScenarioSaveError,
      submit: saveCurrentScenario,
    },
    activeDecisionId: activeScenarioDecisionId,
    setActiveDecisionId: setActiveScenarioDecisionId,
    decisionRefs: scenarioDecisionRefs,
    pickerRef: scenarioDecisionPickerRef,
    pickerButtonRefs: scenarioDecisionPickerButtonRefs,
    apply: applySelections,
    choose: chooseOption,
    jumpTo: jumpToScenarioDecision,
    commit,
    rebase,
    cancelPending,
    beforeSwitch,
    reset,
    epoch: () => applyEpoch.current,
  }
}
