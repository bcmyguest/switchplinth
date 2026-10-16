// Pure helpers over scenario selections (decision id -> option id) and their human-readable summaries.
import type { GraphData } from '../../types'

export function selectedOptions(graph: GraphData): Record<string, string> {
  return Object.fromEntries(graph.decisions.filter((decision) => decision.selected_option).map((decision) => [decision.id, decision.selected_option as string]))
}

export function scenarioSelectionKey(selections: Record<string, string>): string {
  return JSON.stringify(Object.entries(selections).sort(([left], [right]) => left.localeCompare(right)))
}

export function describeScenarioSelection(graph: GraphData, selections: Record<string, string>): string {
  const choices = graph.decisions.map((decision) => {
    const optionId = selections[decision.id] ?? decision.selected_option
    const option = decision.options.find((item) => item.id === optionId)
    return `${decision.title}: ${option?.title ?? 'No option selected'}`
  })
  return choices.length ? choices.join(' · ') : 'Repository choices'
}

export function compactScenarioDecisionTitle(title: string): string {
  return title.replace(/^(select|choose)\s+(the\s+)?/i, '').replace(/^\w/, (letter) => letter.toUpperCase())
}

export function describeScenarioDifference(graph: GraphData, selections: Record<string, string>, baseline: Record<string, string>): string {
  const changes = graph.decisions.flatMap((decision) => {
    const optionId = selections[decision.id] ?? decision.selected_option
    const baselineOptionId = baseline[decision.id] ?? decision.selected_option
    if (optionId === baselineOptionId) return []
    const option = decision.options.find((item) => item.id === optionId)
    const decisionTitle = compactScenarioDecisionTitle(decision.title)
    const optionTitle = (option?.title ?? 'No option selected').replace(/^(Amazon|Apache)\s+/i, '')
    return [`${decisionTitle}: ${optionTitle}`]
  })
  return changes.length ? changes.join(' · ') : 'Same as original choices'
}

export type RepositoryComparison = {
  /** `ready`: `changes` and `decisions` are final; `loading`: the baseline diff is in flight; `error`: it failed. */
  status: 'ready' | 'loading' | 'error'
  changes: Array<{ kind: string; label: string }>
  decisions: string[]
}

type ComparisonInput = {
  /** Displayed selections equal the repository baseline: nothing differs, whatever the resolved graph holds. */
  atBaseline: boolean
  /** The `repositoryDiff` state; absent offline (demo), which falls back to the resolved graph's own lists. */
  diff?: { status: 'idle' | 'loading' | 'error' } | { status: 'ready'; view: { components: Array<{ change: string; text: string }>; relationships: Array<{ change: string; text: string }>; decisions: Array<{ title: string }> } }
  fallbackChanges: Array<{ kind: string; label: string }>
  fallbackDecisions: string[]
}

/** The "Compared with repository choices" lists: empty at baseline, a diff against the baseline once available. */
export function repositoryComparison({ atBaseline, diff, fallbackChanges, fallbackDecisions }: ComparisonInput): RepositoryComparison {
  if (atBaseline) return { status: 'ready', changes: [], decisions: [] }
  if (!diff) return { status: 'ready', changes: fallbackChanges, decisions: fallbackDecisions }
  if (diff.status === 'ready') return { status: 'ready', changes: [...diff.view.components, ...diff.view.relationships].map((line) => ({ kind: line.change, label: line.text })), decisions: diff.view.decisions.map((decision) => decision.title) }
  if (diff.status === 'error') return { status: 'error', changes: [], decisions: [] }
  // `idle` away from the baseline means no diff is pending: use the resolved graph's own lists rather than waiting.
  if (diff.status === 'idle') return { status: 'ready', changes: fallbackChanges, decisions: fallbackDecisions }
  return { status: 'loading', changes: [], decisions: [] }
}
