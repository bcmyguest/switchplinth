// Pure presentation of a scenario diff (`POST /api/v1/scenarios/diff`): every ID becomes a display name, every status a
// word, so the view renders strings only and never needs the graph that produced them.
import type { Decision, ImpactDependent, ScenarioDiff } from '../../types'

const DECISION_REASONS: Record<string, string> = {
  selection_changed: 'choice switched',
  options_reference_changed_elements: 'an option touches a changed element',
}

type DiffLine = { change: 'Added' | 'Removed' | 'Changed'; text: string }
type ProblemLine = { change: 'Appeared' | 'Disappeared'; kind: 'Conflict' | 'Invalid assumption'; text: string }
type DownstreamDependent = { name: string; depth: number; path: string; status: 'Rewired' | 'Dangling' | 'Direct' | 'Indirect'; details: string[] }
type ImpactParent = { type: 'entity' | 'relationship'; change: 'removed' | 'replaced' }
type DownstreamItem = { label: string; change: 'Removed' | 'Replaced'; dependents: DownstreamDependent[]; truncated: boolean }

export type ScenarioDiffView = {
  /** One "Decision: before → after" line per switched decision. */
  switched: string[]
  components: DiffLine[]
  relationships: DiffLine[]
  problems: ProblemLine[]
  decisions: Array<{ title: string; reasons: string }>
  downstream: DownstreamItem[]
  maxDepth: number
}

/** Names for IDs the diff mentions only by ID. `label` covers entities; `relationshipKinds` covers relationships on impact paths. */
export type DiffNaming = { label(id: string): string; decisions: Decision[]; relationshipKinds: ReadonlyMap<string, string> }

function humanKind(kind: string): string {
  return kind.replaceAll('_', ' ')
}

function optionTitle(decision: Decision | undefined, optionId: string | null): string {
  if (!optionId) return 'no option'
  return decision?.options.find((option) => option.id === optionId)?.title ?? optionId
}

export function presentScenarioDiff(diff: ScenarioDiff, naming: DiffNaming): ScenarioDiffView {
  const entityNames = new Map<string, string>()
  for (const entity of [...diff.entities.added, ...diff.entities.removed, ...diff.entities.changed.map((item) => item.after)]) entityNames.set(entity.id, entity.name)
  const kinds = new Map(naming.relationshipKinds)
  for (const relationship of [...diff.relationships.added, ...diff.relationships.removed, ...diff.relationships.changed.map((item) => item.before)]) kinds.set(relationship.id, relationship.kind)
  const name = (id: string) => entityNames.get(id) ?? naming.label(id)
  const relationshipText = (relationship: { from: string; to: string; kind: string }) => `${name(relationship.from)} → ${name(relationship.to)} (${humanKind(relationship.kind)})`

  const components: DiffLine[] = [
    ...diff.entities.added.map((entity) => ({ change: 'Added' as const, text: entity.name })),
    ...diff.entities.removed.map((entity) => ({ change: 'Removed' as const, text: entity.name })),
    ...diff.entities.changed.map(({ before, after }) => ({ change: 'Changed' as const, text: before.name === after.name ? `${after.name} (${before.kind === after.kind ? 'description' : `${before.kind} → ${after.kind}`})` : `${before.name} → ${after.name}` })),
  ]
  const relationships: DiffLine[] = [
    ...diff.relationships.added.map((relationship) => ({ change: 'Added' as const, text: relationshipText(relationship) })),
    ...diff.relationships.removed.map((relationship) => ({ change: 'Removed' as const, text: relationshipText(relationship) })),
    ...diff.relationships.changed.map(({ before, after }) => ({ change: 'Changed' as const, text: `${relationshipText(before)} → ${relationshipText(after)}` })),
  ]
  const problems: ProblemLine[] = ([['Conflict', diff.conflicts], ['Invalid assumption', diff.invalid_assumptions]] as const).flatMap(([kind, set]) => [
    ...set.appeared.map((text) => ({ change: 'Appeared' as const, kind, text })),
    ...set.disappeared.map((text) => ({ change: 'Disappeared' as const, kind, text })),
  ])
  const switched = diff.selection_changes.map((change) => {
    const decision = naming.decisions.find((item) => item.id === change.decision_id)
    return `${decision?.title ?? change.decision_id}: ${optionTitle(decision, change.before_option)} → ${optionTitle(decision, change.after_option)}`
  })

  /** A removed or replaced relationship, named by its before-scenario endpoints. */
  function relationshipLabel(id: string, kind: string): string {
    const relationship = diff.relationships.removed.find((candidate) => candidate.id === id) ?? diff.relationships.changed.find((candidate) => candidate.id === id)?.before
    return relationship ? relationshipText(relationship) : humanKind(kind)
  }

  function pathText(path: string[]): string {
    return path.map((id, index) => index % 2 ? `—${humanKind(kinds.get(id) ?? 'relates to')}→` : name(id)).join(' ')
  }

  /**
   * Text for a depth-1 dependent, whose path is [dependent, relationship, target]: it is the source of the removed or
   * replaced relationship itself, or its edge points straight at the replaced entity.
   */
  function directText(parent: ImpactParent, path: string[]): string {
    const [, relationshipId, target] = path
    const edge = `${humanKind(kinds.get(relationshipId) ?? 'relates to')} edge`
    const verb = parent.change === 'removed' ? 'removes' : 'replaces'
    return parent.type === 'relationship' ? `This choice ${verb} its ${edge} to ${name(target)}.` : `Its ${edge} points at ${name(target)}, which this choice ${verb}.`
  }

  function dependent(item: ImpactDependent, parent: ImpactParent): DownstreamDependent {
    const details = item.missing_endpoints.map((endpoint) => endpoint.status === 'rewired'
      ? `Its ${humanKind(endpoint.kind)} edge to ${name(endpoint.missing_entity_id)} now goes to ${endpoint.rewired_to.map((target) => name(target.to)).join(', ')}.`
      : `Its ${humanKind(endpoint.kind)} edge still points at ${name(endpoint.missing_entity_id)}, which this choice removes.`)
    if (!item.present_after) details.push(`${item.name} is also absent after this choice.`)
    const status = item.points_at_missing ? 'Dangling' : item.rewired ? 'Rewired' : item.depth === 1 ? 'Direct' : 'Indirect'
    if (status === 'Direct') details.push(directText(parent, item.path))
    if (status === 'Indirect') details.push('Depends on it through the path; none of its own edges was lost.')
    return { name: item.name, depth: item.depth, path: pathText(item.path), status, details }
  }

  return {
    switched,
    components,
    relationships,
    problems,
    decisions: diff.affected_decisions.map((decision) => ({ title: decision.title, reasons: decision.reasons.map((reason) => DECISION_REASONS[reason] ?? humanKind(reason)).join(' · ') })),
    downstream: diff.impact.items.map((item) => ({
      label: item.type === 'entity' ? name(item.id) : relationshipLabel(item.id, item.name),
      change: item.change === 'removed' ? 'Removed' : 'Replaced',
      dependents: item.dependents.map((entry) => dependent(entry, item)),
      truncated: item.truncated,
    })),
    maxDepth: diff.impact.max_depth,
  }
}
