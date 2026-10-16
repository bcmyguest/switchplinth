// Repository chooser and switch. A switch starts a new workspace generation, opens the project, and only then calls each
// feature controller's `reset()`; a failed open resets nothing. Every step after an await is dropped when another switch
// has started.
import { useState } from 'react'
import { getConnections, getGraph, getRepositories, openProject } from '../../api'
import type { Workspace } from '../../app/useWorkspace'
import type { ComponentDetailController } from '../architecture/useComponentDetail'
import type { Discovery } from '../discovery/useDiscovery'
import type { Explore } from '../explore/useExplore'
import type { FactsReview } from '../facts/useFactsReview'
import type { DeltaEditor } from '../graph-editor/useDeltaEditor'
import type { ScenarioSelection } from '../scenarios/useScenarioSelection'
import type { Connections } from '../settings/useConnections'

type Repository = { path: string; name: string }

/** The per-repository feature controllers a switch resets, in reset order. */
type RepositoryDependents = {
  scenario: Pick<ScenarioSelection, 'beforeSwitch' | 'reset' | 'rebase' | 'refreshSaved'>
  componentDetail: Pick<ComponentDetailController, 'reset' | 'select'>
  explore: Pick<Explore, 'reset'>
  editor: Pick<DeltaEditor, 'close' | 'reset'>
  facts: Pick<FactsReview, 'reset'>
  discovery: Pick<Discovery, 'reset'>
}

type RepositoryPickerState = {
  open: boolean
  setOpen: (open: boolean) => void
  repositories: Repository[]
  error: string
  switchTo(path: string): Promise<void>
}

export type RepositorySwitch = {
  /** Opens the picker and lists the repositories under the mounted workspace. */
  open(): Promise<void>
  /** True while a switch is in flight. */
  busy: boolean
  dialog: RepositoryPickerState & { busy: boolean }
}

export function useRepositorySwitch(workspace: Pick<Workspace, 'generation' | 'nextGeneration' | 'setLive' | 'setProject' | 'commitGraph' | 'catalog'>, connections: Pick<Connections, 'load' | 'reset'>, dependents: RepositoryDependents): RepositorySwitch {
  const [showRepositoryPicker, setShowRepositoryPicker] = useState(false)
  const [repositories, setRepositories] = useState<Repository[]>([])
  const [repositoryBusy, setRepositoryBusy] = useState(false)
  const [repositoryError, setRepositoryError] = useState('')

  async function openRepositoryChooser() {
    setRepositoryError('')
    setShowRepositoryPicker(true)
    try {
      const result = await getRepositories()
      setRepositories(result.repositories)
    } catch (error) {
      setRepositoryError(`Could not list available repositories: ${error instanceof Error ? error.message : 'connection error'}`)
      setRepositories([])
    }
  }

  async function switchRepository(path: string) {
    const generation = workspace.nextGeneration()
    const { scenario, componentDetail, explore, editor, facts, discovery } = dependents
    scenario.beforeSwitch()
    editor.close()
    workspace.setLive(false)
    setRepositoryBusy(true)
    setRepositoryError('')
    try {
      const { project } = await openProject(path)
      if (generation !== workspace.generation.current) return
      workspace.setProject(project)
      workspace.commitGraph({ entities: [], relationships: [], decisions: [], evidence: [], claims: [], aliases: [] })
      connections.reset()
      scenario.reset()
      componentDetail.reset()
      explore.reset()
      editor.reset()
      facts.reset()
      discovery.reset()
      workspace.setLive(true)
      setShowRepositoryPicker(false)
      try {
        const [nextGraph, nextConnections] = await Promise.all([getGraph(), getConnections()])
        if (generation !== workspace.generation.current) return
        workspace.catalog.replace(nextGraph)
        workspace.commitGraph(nextGraph)
        connections.load(nextConnections)
        scenario.rebase(nextGraph)
        componentDetail.select(nextGraph.entities[0]?.id ?? '')
        void scenario.refreshSaved(generation)
      } catch (error) {
        if (generation !== workspace.generation.current) return
        setShowRepositoryPicker(true)
        setRepositoryError(`Opened ${project.name}, but could not refresh its graph or connections: ${error instanceof Error ? error.message : 'connection error'}. Choose this repository again to retry.`)
      }
    } catch (error) {
      if (generation !== workspace.generation.current) return
      workspace.setLive(true)
      setRepositoryError(`Could not open repository: ${error instanceof Error ? error.message : 'connection error'}`)
    } finally {
      if (generation === workspace.generation.current) setRepositoryBusy(false)
    }
  }

  return {
    open: openRepositoryChooser,
    busy: repositoryBusy,
    dialog: { open: showRepositoryPicker, setOpen: setShowRepositoryPicker, repositories, busy: repositoryBusy, error: repositoryError, switchTo: switchRepository },
  }
}
