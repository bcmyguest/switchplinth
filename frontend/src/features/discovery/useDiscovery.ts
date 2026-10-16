// Discovery: the mode chooser (deterministic/mock or provider extraction), the scan run with its graph refresh, the scan
// state shown by the sidebar and page heading, and the completion summary. Results from an older repository are dropped.
import { useState } from 'react'
import { extractWithProvider, getGraph, scanRepository } from '../../api'
import type { Workspace } from '../../app/useWorkspace'
import type { ScenarioSelection } from '../scenarios/useScenarioSelection'
import type { Connections } from '../settings/useConnections'
import type { ScanState } from './scanState'

type DiscoverMode = 'mock' | 'provider'

export type Discovery = {
  scanState: ScanState
  summary: string
  dismissSummary(): void
  /** Opens the mode chooser. */
  begin(): void
  run(): Promise<void>
  dialog: { open: boolean; setOpen(open: boolean): void; mode: DiscoverMode; setMode(mode: DiscoverMode): void }
  /** Clears this module's share of the repository-switch reset: the scan summary and scan state. */
  reset(): void
}

export function useDiscovery(workspace: Pick<Workspace, 'generation' | 'commitGraph'>, scenario: Pick<ScenarioSelection, 'cancelPending' | 'rebase'>, connections: Pick<Connections, 'list' | 'selectedId'>): Discovery {
  const { generation: repositoryGeneration, commitGraph } = workspace
  const [scanState, setScanState] = useState<ScanState>('idle')
  const [showDiscoverDialog, setShowDiscoverDialog] = useState(false)
  const [discoverMode, setDiscoverMode] = useState<DiscoverMode>('mock')
  const [scanSummary, setScanSummary] = useState('')

  function beginDiscover() {
    setShowDiscoverDialog(true)
  }

  async function runDiscovery() {
    const generation = repositoryGeneration.current
    scenario.cancelPending()
    setShowDiscoverDialog(false)
    setScanState('scanning')
    let completionSummary = ''
    try {
      const connection = connections.list.find((item) => item.id === connections.selectedId) ?? connections.list[0]
      if (discoverMode === 'provider' && !connection) throw new Error('Choose a configured model connection before running provider extraction.')
      const result = discoverMode === 'provider' ? await extractWithProvider(connection!.id) : await scanRepository()
      if (generation !== repositoryGeneration.current) return
      const docs = 'document_count' in result ? result.document_count ?? 0 : Array.isArray(result.documents) ? result.documents.length : 0
      if (discoverMode === 'provider') {
        const providerResult = result as Awaited<ReturnType<typeof extractWithProvider>>
        const indexNote = providerResult.index.qdrant.startsWith('unavailable:') ? ` Qdrant indexing reported: ${providerResult.index.qdrant}` : ' SQLite and Qdrant indexes refreshed.'
        const diagnosticNote = providerResult.diagnostics.length ? ` Diagnostics: ${providerResult.diagnostics.join(' ')}` : ''
        completionSummary = `${providerResult.provider} · ${providerResult.model}: scanned ${docs} Markdown source${docs === 1 ? '' : 's'}; saved ${providerResult.entity_count} entities, ${providerResult.alias_count} aliases, ${providerResult.claim_count} claims, ${providerResult.relationship_count} relationships, ${providerResult.consequence_count} consequences, and ${providerResult.decision_count} decisions.${diagnosticNote}${indexNote}`
      } else {
        const mockResult = result as Awaited<ReturnType<typeof scanRepository>>
        const indexNote = mockResult.index?.qdrant.startsWith('unavailable:') ? ` SQLite refreshed; Qdrant reported: ${mockResult.index.qdrant}` : ' SQLite and Qdrant indexes refreshed.'
        completionSummary = `Deterministic/mock: scanned ${docs} Markdown source${docs === 1 ? '' : 's'}; found ${mockResult.candidate_decision_count ?? 0} decision candidates and ${mockResult.candidate_claim_count ?? 0} claims.${indexNote}`
      }
    } catch (error) {
      if (generation !== repositoryGeneration.current) return
      setScanSummary(`Discovery failed: ${error instanceof Error ? error.message : 'connection error'}`)
      setScanState('error')
      return
    }
    try {
      const refreshedGraph = await getGraph()
      if (generation !== repositoryGeneration.current) return
      commitGraph(refreshedGraph, { live: true })
      scenario.rebase(refreshedGraph)
      setScanSummary(completionSummary)
      setScanState('done')
    } catch (error) {
      if (generation !== repositoryGeneration.current) return
      setScanSummary(`${completionSummary} Discovery completed, but the graph refresh failed: ${error instanceof Error ? error.message : 'connection error'}`)
      setScanState('refresh-error')
    }
  }

  return {
    scanState,
    summary: scanSummary,
    dismissSummary: () => setScanSummary(''),
    begin: beginDiscover,
    run: runDiscovery,
    dialog: { open: showDiscoverDialog, setOpen: setShowDiscoverDialog, mode: discoverMode, setMode: setDiscoverMode },
    reset() {
      setScanSummary('')
      setScanState('idle')
    },
  }
}
