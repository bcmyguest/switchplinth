// Explore: the decision assistant's query, its mode (grounded ask or delta proposal), the search answer, and the proposed
// delta with apply and discard. Propose mode targets the delta editor's decision and option through `editor.setTarget`.
import { useState, type FormEvent } from 'react'
import { proposeScenarioChange, resolveScenario, saveOptionDelta, searchArchitecture, type SearchEvidence, type SearchInactiveEntity } from '../../api'
import type { Workspace } from '../../app/useWorkspace'
import type { Claim, GraphData } from '../../types'
import type { DeltaEditor } from '../graph-editor/useDeltaEditor'
import type { ScenarioSelection } from '../scenarios/useScenarioSelection'
import type { Connections } from '../settings/useConnections'

type ExploreAnswer = { text: string; evidence: SearchEvidence[]; claims: Claim[]; entities: string[]; inactiveEntities: SearchInactiveEntity[]; whyQuery: boolean; grounded: boolean; kind?: 'answer' | 'error' }

type ExploreMode = 'ask' | 'propose'

type Proposal = { delta: NonNullable<GraphData['decisions'][number]['options'][number]['delta']>; rationale?: string; warnings?: string[] }

export type Explore = {
  query: string
  setQuery(query: string): void
  mode: ExploreMode
  setMode(mode: ExploreMode): void
  answer: ExploreAnswer | null
  proposal: Proposal | null
  proposalError: string
  searching: boolean
  /** Switches to propose mode, clears the answer and proposal, and targets the editor's decision (else the first one). */
  startPropose(): void
  submit(event: FormEvent<HTMLFormElement>): Promise<void>
  applyProposal(): Promise<void>
  discardProposal(): void
  /** Clears this module's share of the repository-switch reset: answer, proposal, proposal error, and query. */
  reset(): void
}

export function useExplore(workspace: Pick<Workspace, 'graph' | 'commitGraph'>, scenario: Pick<ScenarioSelection, 'selection' | 'resolved' | 'commit' | 'setNotice'>, editor: Pick<DeltaEditor, 'decisionId' | 'optionId' | 'invalidate' | 'setTarget'>, connections: Pick<Connections, 'active'>): Explore {
  const { graph, commitGraph } = workspace
  const { selection, resolved: resolvedSelection, setNotice: setScenarioNotice } = scenario
  const { decisionId: editingDecisionId, optionId: editingOptionId } = editor
  const activeConnection = connections.active
  const [query, setQuery] = useState('')
  const [answer, setAnswer] = useState<ExploreAnswer | null>(null)
  const [chatMode, setChatMode] = useState<ExploreMode>('ask')
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [proposalError, setProposalError] = useState('')
  const [searching, setSearching] = useState(false)

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!query.trim()) return
    setSearching(true)
    if (chatMode === 'propose') {
      const decisionId = editingDecisionId || graph.decisions[0]?.id
      const optionId = editingOptionId || graph.decisions.find((item) => item.id === decisionId)?.options[0]?.id
      if (!decisionId || !optionId) { setAnswer({ text: 'Select a decision with at least one option before proposing a change.', evidence: [], claims: [], entities: [], inactiveEntities: [], whyQuery: false, grounded: false, kind: 'error' }); setSearching(false); return }
      editor.invalidate()
      editor.setTarget(decisionId, optionId)
      try { setProposal(await proposeScenarioChange(decisionId, optionId, query, activeConnection?.id)); setAnswer(null); setProposalError('') }
      catch (error) { setAnswer({ text: `The configured model could not propose a delta: ${error instanceof Error ? error.message : 'request failed'}`, evidence: [], claims: [], entities: [], inactiveEntities: [], whyQuery: false, grounded: false, kind: 'error' }) }
    } else {
      try {
        const result = await searchArchitecture(query, resolvedSelection.current)
        setAnswer({ text: result.answer, evidence: result.evidence ?? [], claims: result.claims ?? [], entities: result.entities ?? [], inactiveEntities: result.scenario_context?.inactive_entities ?? [], whyQuery: /^\s*why\b/i.test(query), grounded: result.grounded ?? Boolean(result.evidence?.length) })
      } catch {
        setAnswer({ text: 'Live search is unavailable while the backend is offline. This demo graph does not contain a searchable repository index.', evidence: [], claims: [], entities: [], inactiveEntities: [], whyQuery: false, grounded: false, kind: 'error' })
      }
    }
    setSearching(false)
  }

  async function applyProposal() {
    if (!proposal || !editingDecisionId || !editingOptionId) return
    setSearching(true)
    try {
      await saveOptionDelta(editingDecisionId, editingOptionId, proposal.delta)
      const nextSelection = { ...selection, [editingDecisionId]: editingOptionId }
      const refreshed = await resolveScenario(nextSelection)
      commitGraph(refreshed.graph, { live: true })
      scenario.commit(refreshed.graph.scenario?.selections ?? nextSelection)
      setProposal(null)
      setScenarioNotice('AI proposal applied to the selected option delta.')
    } catch (error) { setProposalError(`Could not apply proposed delta: ${error instanceof Error ? error.message : 'request failed'}`) }
    setSearching(false)
  }

  return {
    query,
    setQuery,
    mode: chatMode,
    setMode: setChatMode,
    answer,
    proposal,
    proposalError,
    searching,
    startPropose() {
      setChatMode('propose'); setAnswer(null); setProposal(null); setProposalError(''); const decision = graph.decisions.find((item) => item.id === editingDecisionId) ?? graph.decisions[0]; editor.setTarget(decision?.id ?? '', decision?.options[0]?.id ?? '')
    },
    submit: submitQuery,
    applyProposal,
    discardProposal() {
      setProposal(null); setProposalError('')
    },
    reset() {
      setAnswer(null)
      setProposal(null)
      setProposalError('')
      setQuery('')
    },
  }
}
