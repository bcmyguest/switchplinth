// Workspace core: the current graph, backend liveness, the open project, the label catalog, and the repository generation.
// It loads the graph once on mount and falls back to the demo graph when the backend is unreachable.
import { useEffect, useRef, useState } from 'react'
import { getGraph, getProject } from '../api'
import { demoGraph } from '../demo'
import type { GraphData } from '../types'
import { createLabelCatalog, type LabelCatalog } from './labelCatalog'

export type Workspace = {
  graph: GraphData
  live: boolean
  projectName: string
  projectRoot: string
  catalog: LabelCatalog
  /**
   * Bumped by every repository switch. An async path captures `generation.current` before its first await and drops its
   * result when the value has moved on.
   */
  generation: { readonly current: number }
  /** Starts a new repository generation and returns it. */
  nextGeneration(): number
  /** Refetches the graph and marks the backend live. Rejects when the fetch fails; it does not check the generation. */
  refreshGraph(): Promise<void>
  /** Shows `graph`; sets liveness only when `options` is given. */
  commitGraph(graph: GraphData, options?: { live: boolean }): void
  setLive(live: boolean): void
  setProject(project: { name: string; root: string }): void
}

/**
 * `onInitialGraph` runs once, after the mount-time graph load succeeds for the still-current generation. The handler from
 * the first render is used.
 */
export function useWorkspace(onInitialGraph: (graph: GraphData, generation: number) => void): Workspace {
  const [graph, setGraph] = useState<GraphData>(demoGraph)
  const [live, setLive] = useState(false)
  const [projectName, setProjectName] = useState('platform')
  const [projectRoot, setProjectRoot] = useState('')
  const [catalog] = useState(createLabelCatalog)
  const generation = useRef(0)
  const initialGraphHandler = useRef(onInitialGraph)

  useEffect(() => {
    const loadGeneration = generation.current
    void getGraph().then((data) => {
      if (loadGeneration !== generation.current) return
      catalog.remember(data)
      setGraph(data)
      setLive(true)
      void getProject().then((project) => { if (loadGeneration === generation.current) { setProjectName(project.name); setProjectRoot(project.root) } }).catch(() => undefined)
      initialGraphHandler.current(data, loadGeneration)
    }).catch(() => { if (loadGeneration === generation.current) { setGraph(demoGraph); setLive(false) } })
  }, [catalog])

  async function refreshGraph() {
    const refreshed = await getGraph()
    setGraph(refreshed)
    setLive(true)
  }

  function commitGraph(next: GraphData, options?: { live: boolean }) {
    setGraph(next)
    if (options) setLive(options.live)
  }

  function setProject(project: { name: string; root: string }) {
    setProjectName(project.name)
    setProjectRoot(project.root)
  }

  return {
    graph,
    live,
    projectName,
    projectRoot,
    catalog,
    generation,
    nextGeneration: () => ++generation.current,
    refreshGraph,
    commitGraph,
    setLive,
    setProject,
  }
}
