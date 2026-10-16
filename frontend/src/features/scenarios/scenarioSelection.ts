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
