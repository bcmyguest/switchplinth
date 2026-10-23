// Option delta editor: the YAML draft, its target decision and option, the debounced server preview, save, discard, and the
// typed operations staged from the canvas and the operation form. YAML, canvas edits, and the form all write one delta model.
// It reads `scenario.epoch()` to drop a save that a scenario apply overtook; the scenario module never calls into the editor.
import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react'
import type { Connection as FlowConnection, Edge } from '@xyflow/react'
import { parse, stringify } from 'yaml'
import { previewOptionDelta, resolveScenario, saveOptionDelta } from '../../api'
import type { Workspace } from '../../app/useWorkspace'
import type { DeltaOperation, GraphData } from '../../types'
import type { ArchitecturePanel } from '../architecture/useArchitecturePanels'
import type { ScenarioSelection } from '../scenarios/useScenarioSelection'
import { DEFAULT_DELTA, deltaOperationsFromText, entitiesForOption, operationTouchesEntity, parseDeltaForPreview, relationshipsForOption } from './deltaOperations'
import { useOperationForm, type OperationForm } from './useOperationForm'

type DeltaPreview = { source: string; decisionId: string; optionId: string; graph: GraphData; affected?: { added?: string[]; removed?: string[]; changed?: string[] }; conflicts?: string[]; invalid_assumptions?: string[] }

/** The Architecture overlay state the editor opens and closes; `useArchitecturePanelHost` owns it. */
type EditorPanelHost = {
  setPanel: Dispatch<SetStateAction<ArchitecturePanel | null>>
  /** The element that receives focus when the overlay closes. */
  openerRef: RefObject<HTMLElement | null>
}

export type DeltaEditor = {
  isOpen: boolean
  /** The target decision: the requested one when it exists, else the first decision. */
  decisionId: string | undefined
  /** The target option within `decisionId`: the requested one when it exists, else the first option. */
  optionId: string | undefined
  text: string
  error: string
  notice: string
  /** The compiled preview of the current draft; null while stale, pending, or failed. */
  preview: DeltaPreview | null
  previewBusy: boolean
  /** The typed operations parsed from the draft; empty when the YAML does not parse. */
  operations(): DeltaOperation[]
  entityChoices: ReturnType<typeof entitiesForOption>
  relationshipChoices: ReturnType<typeof relationshipsForOption>
  form: OperationForm
  open(opener?: HTMLElement): void
  /** Stable across renders. */
  close(): void
  save(): Promise<void>
  discard(): void
  /** Replaces the draft from the YAML text area. */
  edit(text: string): void
  chooseDecision(decisionId: string): void
  chooseOption(optionId: string): void
  /** Points the editor at a decision and option without loading the option's delta (proposal target). */
  setTarget(decisionId: string, optionId: string): void
  /** Drops any in-flight save. */
  invalidate(): void
  /** Stages one operation into the target option and opens the editor; focus later returns to `openerEntityId`'s node. */
  stageCanvas(operation: DeltaOperation, openerEntityId: string): void
  connect(connection: FlowConnection, openerEntityId: string): void
  deleteEdges(edges: Edge[], openerEntityId: string): void
  removeEntity(entityId: string): void
  addFromForm(): void
  removeOperation(index: number): void
  /** Clears this module's share of the repository-switch reset: the editor error and the draft. */
  reset(): void
}

export function useDeltaEditor(workspace: Pick<Workspace, 'graph' | 'live' | 'commitGraph'>, scenario: Pick<ScenarioSelection, 'selection' | 'epoch' | 'commit' | 'setNotice'>, panelHost: EditorPanelHost): DeltaEditor {
  const { graph, live, commitGraph } = workspace
  const { selection, setNotice: setScenarioNotice } = scenario
  const { setPanel: setArchitecturePanel, openerRef: panelOpenerRef } = panelHost
  const [showEditor, setShowEditor] = useState(false)
  const [editingDecisionIdState, setEditingDecisionIdState] = useState('')
  const [editingOptionIdState, setEditingOptionIdState] = useState('')
  const [deltaText, setDeltaText] = useState(DEFAULT_DELTA)
  const [editorError, setEditorError] = useState('')
  const [canvasEditNotice, setCanvasEditNotice] = useState('')
  const [deltaPreview, setDeltaPreview] = useState<DeltaPreview | null>(null)
  const [deltaPreviewBusy, setDeltaPreviewBusy] = useState(false)
  const deltaPreviewRequestSequence = useRef(0)
  const deltaSaveGeneration = useRef(0)
  const skipDeltaPreviewSource = useRef<string | null>(null)
  const form = useOperationForm()

  const editingDecisionId = graph.decisions.find((item) => item.id === editingDecisionIdState)?.id ?? graph.decisions[0]?.id
  const editingOptionId = graph.decisions.find((item) => item.id === editingDecisionId)?.options.find((item) => item.id === editingOptionIdState)?.id ?? graph.decisions.find((item) => item.id === editingDecisionId)?.options[0]?.id
  const optionEntityChoices = useMemo(() => entitiesForOption(graph, deltaOperationsFromText(deltaText)), [graph, deltaText])
  const optionRelationshipChoices = useMemo(() => relationshipsForOption(graph, deltaOperationsFromText(deltaText)), [graph, deltaText])

  useEffect(() => {
    const requestSequence = ++deltaPreviewRequestSequence.current
    if (!showEditor || !live || !editingDecisionId || !editingOptionId) {
      setDeltaPreviewBusy(false)
      return () => { deltaPreviewRequestSequence.current += 1 }
    }
    if (skipDeltaPreviewSource.current !== null) {
      const skippedSource = skipDeltaPreviewSource.current
      skipDeltaPreviewSource.current = null
      if (skippedSource === deltaText) {
        setDeltaPreviewBusy(false)
        return () => { deltaPreviewRequestSequence.current += 1 }
      }
    }

    setDeltaPreview(null)
    setEditorError('')
    const timer = window.setTimeout(() => {
      setDeltaPreviewBusy(true)
      void (async () => {
        try {
          const parsed = parseDeltaForPreview(deltaText)
          const result = await previewOptionDelta(editingDecisionId, editingOptionId, { base: parsed.base ?? 'architecture', operations: parsed.operations }, { ...selection, [editingDecisionId]: editingOptionId })
          if (deltaPreviewRequestSequence.current !== requestSequence) return
          setDeltaPreview({ ...result, source: deltaText, decisionId: editingDecisionId, optionId: editingOptionId })
        } catch (error) {
          if (deltaPreviewRequestSequence.current !== requestSequence) return
          setDeltaPreview(null)
          setEditorError(error instanceof Error ? error.message : 'Could not preview this option delta.')
        } finally {
          if (deltaPreviewRequestSequence.current === requestSequence) setDeltaPreviewBusy(false)
        }
      })()
    }, 300)
    return () => {
      window.clearTimeout(timer)
      if (deltaPreviewRequestSequence.current === requestSequence) deltaPreviewRequestSequence.current += 1
    }
  }, [showEditor, live, editingDecisionId, editingOptionId, deltaText, selection])

  const closeDeltaEditor = useCallback(() => {
    deltaSaveGeneration.current += 1
    deltaPreviewRequestSequence.current += 1
    skipDeltaPreviewSource.current = null
    setDeltaPreview(null)
    setDeltaPreviewBusy(false)
    setEditorError('')
    setShowEditor(false)
    setArchitecturePanel((panel) => panel === 'editor' ? null : panel)
  }, [setArchitecturePanel])

  async function saveDelta() {
    const saveGenerationAtStart = deltaSaveGeneration.current
    const scenarioEpochAtStart = scenario.epoch()
    setEditorError('')
    try {
      const parsed = parse(deltaText) as { base?: string; operations?: unknown[] }
      if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.operations)) throw new Error('Delta must contain an operations list.')
      const decision = graph.decisions.find((item) => item.id === editingDecisionId)
      if (!decision || !editingOptionId) throw new Error('Choose a decision and option to edit.')
      if (deltaPreviewBusy || editorError || !deltaPreview || deltaPreview.source !== deltaText || deltaPreview.decisionId !== decision.id || deltaPreview.optionId !== editingOptionId) throw new Error('Wait for a current, successful preview before saving this delta.')
      if (deltaPreview.conflicts?.length) throw new Error('Resolve preview conflicts before saving this delta.')
      const generation = deltaSaveGeneration.current
      const scenarioEpoch = scenario.epoch()
      const decisionId = decision.id
      const optionId = editingOptionId
      const savedDelta = { base: parsed.base ?? 'architecture', operations: parsed.operations as DeltaOperation[] }
      await saveOptionDelta(decisionId, optionId, savedDelta)
      if (deltaSaveGeneration.current !== generation || scenario.epoch() !== scenarioEpoch) return
      const nextSelection = { ...selection, [decisionId]: optionId }
      const refreshed = await resolveScenario(nextSelection)
      if (deltaSaveGeneration.current !== generation || scenario.epoch() !== scenarioEpoch) return
      commitGraph(refreshed.graph, { live: true })
      scenario.commit(refreshed.graph.scenario?.selections ?? nextSelection)
      setDeltaPreview(null)
      setCanvasEditNotice('')
      closeDeltaEditor()
      setScenarioNotice('Option delta saved to the repository overlay.')
    } catch (error) {
      if (deltaSaveGeneration.current === saveGenerationAtStart && scenario.epoch() === scenarioEpochAtStart) setEditorError(error instanceof Error ? error.message : 'Could not save the option delta.')
    }
  }

  /** The decision a canvas edit lands in: an open draft's target, else one whose selected option (then any option) touches the entity. */
  function canvasEditDecision(entityId: string) {
    const selectedOption = (decision: GraphData['decisions'][number]) => decision.options.find((option) => option.id === (selection[decision.id] ?? decision.selected_option))
    return (showEditor ? graph.decisions.find((item) => item.id === editingDecisionIdState) : undefined)
      ?? graph.decisions.find((item) => selectedOption(item)?.delta?.operations.some((operation) => operationTouchesEntity(operation, entityId)))
      ?? graph.decisions.find((item) => item.options.some((option) => option.delta?.operations.some((operation) => operationTouchesEntity(operation, entityId))))
      ?? graph.decisions.find((item) => item.id === editingDecisionIdState) ?? graph.decisions.find((item) => selection[item.id]) ?? graph.decisions[0]
  }

  function stageCanvasOperation(operation: DeltaOperation, openerEntityId: string) {
    const decision = canvasEditDecision(openerEntityId)
    if (!decision) {
      setScenarioNotice('Add a decision with at least one option before editing the graph.')
      return
    }
    const targetOption = (showEditor && decision.id === editingDecisionIdState ? decision.options.find((item) => item.id === editingOptionIdState) : undefined) ?? decision.options.find((item) => item.id === selection[decision.id]) ?? decision.options[0]
    if (!targetOption) {
      setScenarioNotice('This decision has no option to receive the graph edit.')
      return
    }
    const reuseDraft = showEditor && editingDecisionIdState === decision.id && editingOptionIdState === targetOption.id
    const currentOperations = reuseDraft ? deltaOperations() : targetOption.delta?.operations ?? []
    let currentBase = targetOption.delta?.base ?? 'architecture'
    if (reuseDraft) {
      try { currentBase = (parse(deltaText) as { base?: string } | null)?.base ?? currentBase } catch { /* Keep the option's existing base while the YAML is being repaired. */ }
    }
    const nextText = stringify({ base: currentBase, operations: [...currentOperations, operation] })
    setEditingDecisionIdState(decision.id)
    setEditingOptionIdState(targetOption.id)
    setDraftText(nextText)
    setDeltaPreview(null)
    setEditorError('')
    panelOpenerRef.current = [...document.querySelectorAll<HTMLElement>('.react-flow__node')].find((node) => node.dataset.id === openerEntityId) ?? null
    setShowEditor(true)
    setArchitecturePanel('editor')
    setCanvasEditNotice(`Graph edit staged in “${decision.title}” → “${targetOption.title}”. Review the preview, then save the delta.`)
  }

  function connectCanvasNodes(connection: FlowConnection, openerEntityId: string) {
    if (!connection.source || !connection.target) return
    const relationKind = form.relationKind.trim() || 'depends_on'
    if (graph.relationships.some((relation) => relation.from === connection.source && relation.to === connection.target && relation.kind === relationKind)) {
      setCanvasEditNotice('That relationship already exists in the current scenario.')
      return
    }
    const relationId = `relationship-${`${connection.source}-${relationKind}-${connection.target}`.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`
    stageCanvasOperation({ op: 'add_relationship', relationship: { id: relationId, from: connection.source, to: connection.target, kind: relationKind } }, openerEntityId)
  }

  function deleteCanvasEdges(edgesToDelete: Edge[], openerEntityId: string) {
    const operations = deltaOperations()
    for (const edge of edgesToDelete) {
      const addedIndex = operations.findIndex((operation) => operation.op === 'add_relationship' && (operation.relationship as { id?: string } | undefined)?.id === edge.id)
      if (addedIndex >= 0) {
        operations.splice(addedIndex, 1)
        setDraftText(stringify({ base: 'architecture', operations }))
        setDeltaPreview(null)
        setCanvasEditNotice('Removed the unsaved relationship from the staged delta.')
      } else {
        const relationship = graph.relationships.find((item) => item.id === edge.id)
        if (relationship) stageCanvasOperation({ op: 'remove_relationship', relationship: { id: relationship.id }, expect: { exists: true } }, openerEntityId)
      }
    }
  }

  function removeCanvasEntity(entityId: string) {
    const entity = graph.entities.find((item) => item.id === entityId)
    if (!entity) return
    stageCanvasOperation({ op: 'remove_entity', entity: { id: entity.id }, expect: { exists: true } }, entityId)
  }

  function discardDelta() {
    const option = graph.decisions.find((item) => item.id === editingDecisionId)?.options.find((item) => item.id === editingOptionId)
    const savedText = stringify(option?.delta ?? { base: 'architecture', operations: [] })
    deltaPreviewRequestSequence.current += 1
    skipDeltaPreviewSource.current = savedText === deltaText ? null : savedText
    setDeltaPreview(null)
    setDeltaPreviewBusy(false)
    setEditorError('')
    setDraftText(savedText)
    setCanvasEditNotice('')
  }

  function invalidateDeltaSave() {
    deltaSaveGeneration.current += 1
  }

  function setDraftText(text: string) {
    invalidateDeltaSave()
    setDeltaText(text)
  }

  function openDeltaEditor(opener?: HTMLElement) {
    const decision = graph.decisions.find((item) => item.id === editingDecisionIdState) ?? graph.decisions.find((item) => selection[item.id]) ?? graph.decisions[0]
    const option = decision?.options.find((item) => item.id === editingOptionIdState) ?? decision?.options.find((item) => item.id === selection[decision.id]) ?? decision?.options[0]
    if (decision && option) {
      invalidateDeltaSave()
      setEditingDecisionIdState(decision.id)
      setEditingOptionIdState(option.id)
      setDraftText(stringify(option.delta ?? { base: 'architecture', operations: [] }))
    }
    panelOpenerRef.current = opener ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null)
    setShowEditor(true)
    setArchitecturePanel('editor')
    setEditorError('')
  }

  function updateEditorDecision(decisionId: string) {
    const decision = graph.decisions.find((item) => item.id === decisionId)
    const option = decision?.options.find((item) => item.id === selection[decision.id]) ?? decision?.options[0]
    invalidateDeltaSave()
    setEditingDecisionIdState(decisionId)
    setEditingOptionIdState(option?.id ?? '')
    setDraftText(stringify(option?.delta ?? { base: 'architecture', operations: [] }))
    setDeltaPreview(null)
    setCanvasEditNotice('')
  }

  function updateEditorOption(optionId: string) {
    const option = graph.decisions.find((item) => item.id === editingDecisionId)?.options.find((item) => item.id === optionId)
    invalidateDeltaSave()
    setEditingOptionIdState(optionId)
    setDraftText(stringify(option?.delta ?? { base: 'architecture', operations: [] }))
    setDeltaPreview(null)
    setCanvasEditNotice('')
  }

  function deltaOperations(): DeltaOperation[] {
    return deltaOperationsFromText(deltaText)
  }

  function appendDeltaOperation(operation: DeltaOperation) {
    let base = 'architecture'
    try { base = (parse(deltaText) as { base?: string } | null)?.base ?? base } catch { /* The YAML editor will show its parse error at save time. */ }
    setDraftText(stringify({ base, operations: [...deltaOperations(), operation] }))
    setDeltaPreview(null)
  }

  function addOperationFromForm() {
    if (form.kind === 'add_entity' && form.entityName.trim()) {
      const id = form.entityId || form.entityName.toLowerCase().replace(/[^a-z0-9]+/g, '-')
      appendDeltaOperation({ op: 'add_entity', entity: { id, name: form.entityName.trim(), kind: form.entityKind } })
      form.setEntityId('')
      form.setEntityName('')
    } else if (form.kind === 'remove_entity') {
      const entity = optionEntityChoices.find((item) => item.id === form.entityId)
      if (entity) appendDeltaOperation({ op: 'remove_entity', entity: { id: entity.id }, expect: { exists: true } })
    } else if (form.kind === 'add_relationship' && form.from && form.to) {
      const id = `relationship-${`${form.from}-${form.relationKind}-${form.to}`.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`
      appendDeltaOperation({ op: 'add_relationship', relationship: { id, from: form.from, to: form.to, kind: form.relationKind } })
    } else if (form.kind === 'remove_relationship') {
      const relationship = optionRelationshipChoices.find((item) => item.id === form.relationId)
      if (relationship) appendDeltaOperation({ op: 'remove_relationship', relationship: { id: relationship.id }, expect: { exists: true } })
    }
  }

  function removeDeltaOperation(index: number) {
    let base = 'architecture'
    try { base = (parse(deltaText) as { base?: string } | null)?.base ?? base } catch { /* Preserve the default base until the YAML is repaired. */ }
    setDraftText(stringify({ base, operations: deltaOperations().filter((_, itemIndex) => itemIndex !== index) }))
    setDeltaPreview(null)
  }

  return {
    isOpen: showEditor,
    decisionId: editingDecisionId,
    optionId: editingOptionId,
    text: deltaText,
    error: editorError,
    notice: canvasEditNotice,
    preview: deltaPreview,
    previewBusy: deltaPreviewBusy,
    operations: deltaOperations,
    entityChoices: optionEntityChoices,
    relationshipChoices: optionRelationshipChoices,
    form,
    open: openDeltaEditor,
    close: closeDeltaEditor,
    save: saveDelta,
    discard: discardDelta,
    edit(text) {
      setDraftText(text)
      setDeltaPreview(null)
    },
    chooseDecision: updateEditorDecision,
    chooseOption: updateEditorOption,
    setTarget(decisionId, optionId) {
      setEditingDecisionIdState(decisionId)
      setEditingOptionIdState(optionId)
    },
    invalidate: invalidateDeltaSave,
    stageCanvas: stageCanvasOperation,
    connect: connectCanvasNodes,
    deleteEdges: deleteCanvasEdges,
    removeEntity: removeCanvasEntity,
    addFromForm: addOperationFromForm,
    removeOperation: removeDeltaOperation,
    reset() {
      setEditorError('')
      setDraftText(DEFAULT_DELTA)
    },
  }
}
